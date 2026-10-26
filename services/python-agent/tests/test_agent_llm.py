"""LLM 客户端的重试行为。

单独一个文件，因为这里测的是「网络层怎么应对故障」，和节点的推理逻辑无关。

为什么这几条值得写测试：
免费额度下 429 是常态（实测一个下午撞三次），而每次 429 都会在 0.4 秒内返回、
直接打断整条 SSE 流——前端只显示"模型超时"。演示当天撞上就是翻车。
所以「限流要重试、超时不要重试」这个区分必须被钉住，不能靠人记住。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import llm as llm_mod  # noqa: E402
from app.agent.llm import LLMClient, LLMError  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """不联网的客户端：只构造对象，_post_once 会被替换掉。"""
    monkeypatch.setattr(llm_mod.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_mod.asyncio, "sleep", _no_sleep)
    return LLMClient()


async def _no_sleep(_seconds):
    """把退避的等待短路掉，否则测试要真等 5 秒。"""
    return None


@pytest.mark.asyncio
async def test_rate_limit_is_retried_then_succeeds(client, monkeypatch):
    calls = {"n": 0}

    async def fake_once(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMError("LLM_RATE_LIMIT", "模型限流")
        return "ok"

    monkeypatch.setattr(client, "_post_once", fake_once)

    out = await client._post([], stream=False, temperature=0.1, max_tokens=10)
    assert out == "ok"
    assert calls["n"] == 3, "两次限流后应该重试成功"


@pytest.mark.asyncio
async def test_rate_limit_gives_up_after_max_retries(client, monkeypatch):
    calls = {"n": 0}

    async def always_limited(*_a, **_kw):
        calls["n"] += 1
        raise LLMError("LLM_RATE_LIMIT", "模型限流")

    monkeypatch.setattr(client, "_post_once", always_limited)

    with pytest.raises(LLMError) as ei:
        await client._post([], stream=False, temperature=0.1, max_tokens=10)

    assert ei.value.code == "LLM_RATE_LIMIT"
    # 首次 + 2 次重试，不能无限重试——否则用户会一直等
    assert calls["n"] == llm_mod.RATE_LIMIT_RETRIES + 1


@pytest.mark.asyncio
async def test_timeout_is_not_retried(client, monkeypatch):
    """超时不重试：各节点超时本来就有 10~15 秒，再重试一次用户要多等一个周期。

    而且超时通常意味着模型真的慢，重试大概率还是慢——这种情况应该赶紧降级，
    让 grader 用重排分估覆盖率、让生成走抽取式兜底，而不是让用户干等。
    """
    calls = {"n": 0}

    async def always_timeout(*_a, **_kw):
        calls["n"] += 1
        raise LLMError("LLM_TIMEOUT", "模型响应超时（12s）")

    monkeypatch.setattr(client, "_post_once", always_timeout)

    with pytest.raises(LLMError) as ei:
        await client._post([], stream=False, temperature=0.1, max_tokens=10)

    assert ei.value.code == "LLM_TIMEOUT"
    assert calls["n"] == 1, "超时不该重试"


@pytest.mark.asyncio
async def test_json_call_degrades_on_rate_limit_instead_of_raising(client, monkeypatch):
    """节点层（_tolerant_json_call）只吞超时，限流要如实上报。

    这里验证的是边界：LLMClient 自己会把限流重试到底，
    重试仍失败才抛出去，由编排层决定怎么呈现——不能在这里静默变成空结果。
    """

    async def always_limited(*_a, **_kw):
        raise LLMError("LLM_RATE_LIMIT", "模型限流")

    monkeypatch.setattr(client, "_post_once", always_limited)

    with pytest.raises(LLMError):
        await client.json_call("sys", "user", max_tokens=10)


@pytest.mark.asyncio
async def test_node_degrades_on_rate_limit_instead_of_aborting(monkeypatch):
    """限流到节点层要降级，不能把整条流打断。

    实测场景：grader 撞上连续 429，重试 2 次仍失败 → 抛到编排层 → 整条流
    以 error 收尾。而这时候已经召回了 12 条证据，用户却一条答案都没看到。
    降级成「按重排分估覆盖率」至少还能继续生成。
    """
    from app.agent import nodes
    from app.agent.nodes import Evidence

    class LimitedLLM:
        async def json_call(self, *_a, **_kw):
            raise LLMError("LLM_RATE_LIMIT", "模型限流")

    evidence = [
        Evidence(chunk_id=f"c_{i}", raw_id=i, doc_id=1, doc_name="d", heading_path="h",
                 content="x", score=0.8, subject="JVM", domain="backend")
        for i in range(3)
    ]

    g = await nodes.grade(LimitedLLM(), "问题", evidence, 0.6)
    assert g.degraded is True
    assert "限流" in (g.detail or "")
    assert 0 < g.coverage <= 0.85, "降级要给出可用覆盖率，且不能声称证据充分"


@pytest.mark.asyncio
async def test_node_still_aborts_on_auth_failure(monkeypatch):
    """鉴权失败不能吞——那不是"这次不通"，是永远不通。"""
    from app.agent import nodes
    from app.agent.nodes import Evidence

    class BadKeyLLM:
        async def json_call(self, *_a, **_kw):
            raise LLMError("INTERNAL", "模型调用失败：AuthenticationError")

    evidence = [
        Evidence(chunk_id="c_1", raw_id=1, doc_id=1, doc_name="d", heading_path="h",
                 content="x", score=0.8, subject="JVM", domain="backend")
    ]

    with pytest.raises(LLMError):
        await nodes.grade(BadKeyLLM(), "问题", evidence, 0.6)
