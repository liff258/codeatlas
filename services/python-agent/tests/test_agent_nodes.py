"""Agent 节点与引用拦截器的单测。

不需要网络、不需要数据库、不需要真实模型——用 FakeLLM 喂预置响应。

重点覆盖三类「静默失败」：
1. JSON 解析：模型输出带围栏/尾逗号/中文引号时能否救回来，截断时是否老实放弃
2. 引用拦截：标记被流式切成两片时是否还能正确绑定，幻觉编号是否被识别
3. 跨域边：必须由 domain 计算，不能被模型输出的布尔值带偏
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import nodes  # noqa: E402
from app.agent.llm import LLMResult, extract_json  # noqa: E402
from app.agent.nodes import CitationInterceptor, Evidence  # noqa: E402


# ---------------------------------------------------------------- 假 LLM


class FakeLLM:
    """只实现 json_call / stream_call，返回预置内容。"""

    def __init__(self, payload: str | dict | None = None, *, stream: list[str] | None = None):
        self.payload = payload
        self._stream = stream or []
        self.calls = 0

    async def json_call(self, system: str, user: str, **kwargs) -> LLMResult:
        self.calls += 1
        if isinstance(self.payload, dict):
            return LLMResult(text="", data=self.payload)
        text = self.payload or ""
        data = extract_json(text)
        return LLMResult(
            text=text,
            data=data,
            degraded=data is None,
            detail="" if data else "解析失败",
        )

    async def stream_call(self, system: str, user: str, **kwargs):
        for piece in self._stream:
            yield piece


def ev(i: int, *, subject: str = "JVM", domain: str = "backend", content: str = "") -> Evidence:
    return Evidence(
        chunk_id=f"c_{i}",
        raw_id=i,
        doc_id=1,
        doc_name=f"doc{i}",
        heading_path=f"h{i}",
        content=content or f"内容 {i}",
        score=0.9,
        subject=subject,
        domain=domain,
    )


# ---------------------------------------------------------------- JSON 容错


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_chatter():
    """模型经常在 JSON 前后加一句废话。"""
    assert extract_json('好的，以下是结果：\n{"a": 1}\n希望有帮助。') == {"a": 1}


def test_extract_json_trailing_comma():
    assert extract_json('{"a": 1,}') == {"a": 1}


def test_extract_json_smart_quotes():
    """中文引号包字符串是国产模型的高频错误。"""
    assert extract_json('{“a”: “b”}') == {"a": "b"}


def test_extract_json_nested():
    data = extract_json('{"a": {"b": [1, 2]}, "c": 3}')
    assert data == {"a": {"b": [1, 2]}, "c": 3}


def test_extract_json_truncated_returns_none():
    """输出被 max_tokens 截断时，括号不闭合 → 老实返回 None，不要瞎猜。"""
    assert extract_json('{"a": 1, "b": {"c": 2') is None


def test_extract_json_brace_inside_string():
    """字符串里的 } 不能被当成结构闭合。"""
    assert extract_json('{"a": "x}y"}') == {"a": "x}y"}


def test_extract_json_no_object():
    assert extract_json("完全不是 JSON") is None
    assert extract_json("") is None


# ---------------------------------------------------------------- 引用拦截


def test_interceptor_simple_marker():
    ic = CitationInterceptor([ev(1), ev(2)])
    out = ic.feed("结论是这样的[1]。")
    assert (1, "[1]") in out
    assert "".join(t for _, t in out) == "结论是这样的[1]。"


def test_interceptor_marker_split_across_chunks():
    """流式会把 [1] 切成 "[1" + "]"。拦截器必须等凑齐再判断。"""
    ic = CitationInterceptor([ev(1)])
    first = ic.feed("看这里[1")
    # 第一个 chunk 里不该出现 citation（标记还不完整）
    assert all(n is None for n, _ in first)

    second = ic.feed("]，很重要。")
    assert any(n == 1 for n, _ in second)
    # 文本不能丢
    assert "".join(t for _, t in first + second) == "看这里[1]，很重要。"


def test_interceptor_out_of_range_marker():
    """幻觉编号 [99] 要原样保留在正文里，但不发 citation。

    保留而不是删掉，是因为前端会给它显示「无出处」——
    悄悄删掉会让读者以为这句话没有引用需求，反而更误导。
    """
    ic = CitationInterceptor([ev(1)])
    out = ic.feed("乱引用[99]")
    assert all(n is None for n, _ in out)
    assert "".join(t for _, t in out) == "乱引用[99]"


def test_interceptor_no_duplicate_citation():
    """同一个编号出现两次，citation 只发一次。"""
    ic = CitationInterceptor([ev(1)])
    first = ic.feed("[1]")
    second = ic.feed("又见[1]")
    assert any(n == 1 for n, _ in first)
    assert all(n is None for n, _ in second)


def test_interceptor_non_numeric_bracket():
    ic = CitationInterceptor([ev(1)])
    out = ic.feed("[注]这是脚注")
    assert all(n is None for n, _ in out)
    assert "".join(t for _, t in out) == "[注]这是脚注"


def test_interceptor_flush_returns_remainder():
    """流结束时缓冲区里可能还压着半个标记，必须吐出来。"""
    ic = CitationInterceptor([ev(1)])
    ic.feed("结尾[1")
    assert ic.flush() == "[1"


# ---------------------------------------------------------------- 节点降级


@pytest.mark.asyncio
async def test_route_degrades_on_bad_json():
    r = await nodes.route(FakeLLM("这不是 JSON"), "问题", [])
    assert r.degraded is True
    assert r.intent == "concept"
    assert r.need_retrieval is True  # 降级时绝不能猜 chitchat


@pytest.mark.asyncio
async def test_route_parses_valid():
    r = await nodes.route(FakeLLM({"intent": "compare", "need_retrieval": True}), "问题", [])
    assert r.intent == "compare"
    assert r.degraded is False


@pytest.mark.asyncio
async def test_plan_falls_back_to_single_query():
    r = await nodes.plan(FakeLLM("坏的"), "原始问题", "concept")
    assert r.degraded is True
    assert len(r.sub_queries) == 1
    assert r.sub_queries[0].text == "原始问题"


@pytest.mark.asyncio
async def test_plan_caps_sub_queries():
    """模型可能吐出 10 个子查询，必须截到 4 个——否则重排会变慢。"""
    payload = {"hops": 2, "sub_queries": [{"id": f"q{i}", "text": f"查询{i}", "entities": []} for i in range(10)]}
    r = await nodes.plan(FakeLLM(payload), "问题", "concept")
    assert len(r.sub_queries) == 4
    assert [s.id for s in r.sub_queries] == ["q1", "q2", "q3", "q4"]


@pytest.mark.asyncio
async def test_grade_heuristic_fallback_uses_scores():
    """自评解析失败时，用重排分估覆盖率——不能固定给 0.5 糊弄。"""
    good = [ev(1), ev(2), ev(3)]
    for e in good:
        e.score = 0.9
    r = await nodes.grade(FakeLLM("坏的"), "问题", good, threshold=0.6)
    assert r.degraded is True
    assert r.coverage > 0.8
    assert r.decision == "proceed"


@pytest.mark.asyncio
async def test_grade_low_scores_trigger_rewrite():
    weak = [ev(1)]
    weak[0].score = 0.2
    r = await nodes.grade(FakeLLM("坏的"), "问题", weak, threshold=0.6)
    assert r.decision == "rewrite"


@pytest.mark.asyncio
async def test_rewrite_rejects_duplicate_queries():
    """改写必须带来新查询，重复上一轮的查询是无效改写。"""
    payload = {"sub_queries": [{"id": "q5", "text": "已经查过的", "entities": []}]}
    subs, degraded, _ = await nodes.rewrite(
        FakeLLM(payload), "问题", ["已经查过的"], "缺证据", next_id=5
    )
    assert subs == []
    assert degraded is True


# ---------------------------------------------------------------- 图谱


@pytest.mark.asyncio
async def test_graph_cross_domain_computed_not_trusted():
    """跨域边必须由 domain 计算。

    这里故意让模型输出一个跨域边的组合，但两个实体同域 ——
    结果必须是非跨域，证明代码没有信任模型的判断。
    """
    evidence = [
        ev(1, subject="JVM", domain="backend", content="G1 收集器使用 SATB"),
        ev(2, subject="JVM", domain="backend", content="SATB 依赖写屏障"),
    ]
    payload = {
        "nodes": [
            {"id": "G1", "label": "G1", "type": "组件"},
            {"id": "SATB", "label": "SATB", "type": "算法"},
        ],
        "edges": [{"source": "G1", "target": "SATB", "rel": "使用", "cross_domain": True}],
    }
    nodes_out, edges_out, path, degraded, _ = await nodes.extract_graph(
        FakeLLM(payload), "问题", evidence, ["G1", "SATB"]
    )
    assert degraded is False
    assert len(nodes_out) == 2
    # 模型说 true，但两个都是 backend → 必须是 false
    assert edges_out[0].cross_domain is False


@pytest.mark.asyncio
async def test_graph_detects_real_cross_domain():
    evidence = [
        ev(1, subject="RAG", domain="ai", content="RAG 使用向量检索"),
        ev(2, subject="MySQL", domain="backend", content="B+ 树用于索引"),
    ]
    payload = {
        "nodes": [
            {"id": "RAG", "label": "RAG", "type": "概念"},
            {"id": "B+树", "label": "B+ 树", "type": "算法"},
        ],
        "edges": [{"source": "RAG", "target": "B+树", "rel": "对比"}],
    }
    _, edges_out, path, _, _ = await nodes.extract_graph(
        FakeLLM(payload), "问题", evidence, ["RAG", "B+树"]
    )
    assert edges_out[0].cross_domain is True
    # 推理路径应优先走跨域边——这是演示时要讲的那条链
    assert path == ["RAG", "B+树"]


@pytest.mark.asyncio
async def test_graph_drops_invented_entities():
    """模型编出来的实体（不在给定列表里）必须丢弃。"""
    payload = {
        "nodes": [
            {"id": "RAG", "label": "RAG", "type": "概念"},
            {"id": "模型瞎编的", "label": "X", "type": "概念"},
        ],
        "edges": [],
    }
    nodes_out, _, _, _, _ = await nodes.extract_graph(
        FakeLLM(payload), "问题", [ev(1)], ["RAG"]
    )
    assert [n.id for n in nodes_out] == ["RAG"]


@pytest.mark.asyncio
async def test_graph_skips_when_no_entities():
    n, e, p, degraded, detail = await nodes.extract_graph(FakeLLM("{}"), "问题", [ev(1)], [])
    assert n == [] and e == []
    assert degraded is True
    assert "实体" in detail
