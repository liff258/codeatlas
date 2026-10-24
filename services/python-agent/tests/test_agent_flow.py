"""Agent 编排的契约一致性测试。

不需要真实模型、不需要数据库：用 FakeLLM 和 FakeRetriever 替换掉外部依赖，
验证 `agent_stream` 产出的事件序列是否符合 contracts/sse-events.md 第 5 节。

这一层测试的价值在于：编排逻辑（顺序保证、引用先于 token、done 收尾）
是最容易写错也最难在界面上看出来的地方。比如 citation 晚于 token 到达，
界面会先闪一下裸的 [1] 再变成角标——肉眼很难复现，但断言一抓一个准。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import graph as graph_mod  # noqa: E402
from app.agent.llm import LLMResult, extract_json  # noqa: E402
from app.rag.retrieve import RetrievedChunk  # noqa: E402


# ---------------------------------------------------------------- 假依赖


class FakeLLM:
    """按调用顺序返回预置响应，模拟一整轮 Agent 交互。"""

    def __init__(self, *, coverage: float = 0.82, answer: list[str] | None = None):
        self.coverage = coverage
        self.answer = answer or ["SATB 是快照标记[1]，", "它依赖写屏障[2]。"]
        self._json_queue: list[dict] = [
            {"intent": "compare", "need_retrieval": True},
            {
                "hops": 2,
                "sub_queries": [
                    {"id": "q1", "text": "SATB 原始快照", "entities": ["SATB"]},
                    {"id": "q2", "text": "G1 写屏障", "entities": ["G1"]},
                ],
            },
            {"coverage": coverage, "low_score_ids": [], "reason": "证据充分"},
            {
                "nodes": [
                    {"id": "SATB", "label": "SATB", "type": "算法"},
                    {"id": "G1", "label": "G1 收集器", "type": "组件"},
                ],
                "edges": [{"source": "G1", "target": "SATB", "rel": "使用"}],
            },
        ]
        self.model = "fake"

    @property
    def usage(self):
        from app.agent.events import Usage

        return Usage(input_tokens=100, output_tokens=50, cost_cny=0.0)

    async def json_call(self, system, user, **kw) -> LLMResult:
        payload = self._json_queue.pop(0) if self._json_queue else {}
        return LLMResult(text="", data=payload)

    async def stream_call(self, system, user, **kw):
        for piece in self.answer:
            yield piece

    async def close(self) -> None:
        pass


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]):
        self._chunks = chunks

    def search(self, query, *, top_k=20, top_n=12, rerank=True):
        return self._chunks


def make_chunk(cid: int, *, subject: str = "JVM") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        parent_chunk_id=None,
        content=f"SATB 通过写屏障记录并发标记期间的引用变更（第 {cid} 条）。",
        heading_path=f"JVM > G1 > SATB-{cid}",
        subject=subject,
        doc_id=cid,
        doc_name=f"文档{cid}",
        score=0.9 - cid * 0.01,
        bm25_rank=cid,
        vec_rank=cid,
        preview="",
    )


async def collect(question: str = "G1 的 SATB 是什么", **llm_kw) -> list[tuple[str, dict]]:
    """跑一遍 agent_stream，把 SSE 帧解析成 (event, data)。"""

    events: list[tuple[str, dict]] = []
    buf = ""

    async for frame in graph_mod.agent_stream(question=question, trace_id="t_test"):
        buf += frame
        while "\n\n" in buf:
            raw, buf = buf.split("\n\n", 1)
            event, data = "", []
            for line in raw.split("\n"):
                if line.startswith(":"):
                    continue
                idx = line.find(":")
                if idx == -1:
                    continue
                f, v = line[:idx], line[idx + 1 :]
                if v.startswith(" "):
                    v = v[1:]
                if f == "event":
                    event = v
                elif f == "data":
                    data.append(v)
            if event and data:
                events.append((event, extract_json("\n".join(data)) or {}))
    return events


@pytest.fixture
def patched(monkeypatch):
    """把 LLM 和检索都换成假的。"""
    fake = FakeLLM()

    monkeypatch.setattr(graph_mod, "LLMClient", lambda *a, **k: fake)

    def fake_build_retriever():
        return FakeRetriever([make_chunk(i) for i in range(1, 5)])

    # graph.py 里是延迟导入的，patch 源模块
    import app.rag.retrieve as retrieve_mod

    monkeypatch.setattr(retrieve_mod, "build_retriever", fake_build_retriever)

    # 重排也要绕开（否则会去加载 2.2GB 模型）
    import app.rag.rerank as rerank_mod

    class NoRerank:
        def rerank(self, query, chunks, top_n=12):
            for c in chunks:
                c.rerank_score = 0.9
            return chunks

    monkeypatch.setattr(rerank_mod, "get_reranker", lambda: NoRerank())
    return fake


# ---------------------------------------------------------------- 契约断言


@pytest.mark.asyncio
async def test_event_sequence_is_contract_compliant(patched):
    events = await collect()
    names = [e for e, _ in events]

    assert names[0] == "step", "第一个事件必须是 step(running)"
    assert names[-1] == "done", "done 必须是最后一个事件"
    assert names.count("done") == 1

    # plan 必须在所有 retrieval 之前
    assert "plan" in names
    first_plan = names.index("plan")
    first_retrieval = names.index("retrieval")
    assert first_plan < first_retrieval

    # 每个 retrieval 的 query_id 必须能在 plan 里找到（首轮）
    plan_data = next(d for e, d in events if e == "plan")
    plan_ids = {s["id"] for s in plan_data["sub_queries"]}
    for e, d in events:
        if e == "retrieval" and d.get("rewrite_round", 0) == 0:
            assert d["query_id"] in plan_ids


@pytest.mark.asyncio
async def test_seq_is_monotonic(patched):
    events = await collect()
    seqs = [d["seq"] for _, d in events]
    assert seqs == sorted(seqs), "seq 必须单调递增"
    assert seqs[0] == 1, "seq 从 1 开始"
    assert len(set(seqs)) == len(seqs), "seq 不能重复"


@pytest.mark.asyncio
async def test_trace_id_consistent(patched):
    events = await collect()
    assert {d["trace_id"] for _, d in events} == {"t_test"}


@pytest.mark.asyncio
async def test_citation_before_its_token(patched):
    """契约 4.7：citation 必须先于引用它的 token 到达。

    否则前端会先渲染裸的 [1]，再跳变成角标。
    """
    events = await collect()
    first_citation_at = None
    for i, (e, d) in enumerate(events):
        if e == "citation" and first_citation_at is None:
            first_citation_at = i
        if e == "token" and "[" in d.get("text", "") and first_citation_at is None:
            pytest.fail(f"token 里出现了引用标记，但此前没有 citation 事件：{d['text']!r}")

    assert first_citation_at is not None, "答案里有 [1][2]，应该产生 citation 事件"


@pytest.mark.asyncio
async def test_graph_event_has_cross_domain_edge(patched):
    """两个实体同属 JVM 域，不该出现跨域边；但要验证 cross_domain 字段被正确计算。"""
    events = await collect()
    graphs = [d for e, d in events if e == "graph"]
    assert graphs, "应该发出 graph 事件"
    for edge in graphs[0]["edges"]:
        assert "cross_domain" in edge


@pytest.mark.asyncio
async def test_done_carries_usage_and_coverage(patched):
    events = await collect()
    done = next(d for e, d in events if e == "done")
    assert done["stop_reason"] == "normal"
    assert done["coverage"] > 0
    assert done["usage"]["input_tokens"] > 0
    assert done["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_low_coverage_triggers_rewrite_then_gives_up(monkeypatch):
    """覆盖率一直不够时，必须改写、并在轮数用尽后正常收尾（不能死循环）。"""
    fake = FakeLLM(coverage=0.1)
    # 第一轮 grade 低 → 改写 → 再 grade 还是低 → 达到 max_rewrite 后给 up
    fake._json_queue = [
        {"intent": "concept", "need_retrieval": True},
        {"hops": 1, "sub_queries": [{"id": "q1", "text": "查询", "entities": ["SATB"]}]},
        {"coverage": 0.1, "reason": "不够"},
        {"sub_queries": [{"id": "q2", "text": "换个说法查", "entities": []}]},
        {"coverage": 0.1, "reason": "还是不够"},
    ]

    monkeypatch.setattr(graph_mod, "LLMClient", lambda *a, **k: fake)
    import app.rag.rerank as rerank_mod
    import app.rag.retrieve as retrieve_mod

    monkeypatch.setattr(
        retrieve_mod, "build_retriever", lambda: FakeRetriever([make_chunk(i) for i in range(1, 3)])
    )

    class NoRerank:
        def rerank(self, query, chunks, top_n=12):
            return chunks

    monkeypatch.setattr(rerank_mod, "get_reranker", lambda: NoRerank())

    events = await collect()
    names = [e for e, _ in events]

    assert names[-1] == "done"
    # rewriter 是 step 事件里的 node 字段，不是独立的事件名
    rewrite_steps = [d for e, d in events if e == "step" and d.get("node") == "rewriter"]
    assert rewrite_steps, "覆盖率不足应该触发改写"
    done = next(d for e, d in events if e == "done")
    assert done["rewrite_count"] >= 1
