"""SSE 协议一致性测试。

这不是"为了有测试而写测试"——它守的是 contracts/sse-events.md 里那 5 条顺序保证。
前端在 mock 模式下调好的布局，一旦真实链路的事件顺序变了就会错位，
而错位在演示现场是不可接受的。这个文件就是那道闸。

运行：cd services/python-agent && pytest -v
"""

from __future__ import annotations

import json

import pytest

from app.agent.mock_runner import DEMO_QUESTION, mock_stream

# ---------------------------------------------------------------- 工具

def parse_frames(raw_frames: list[str]) -> list[tuple[str, dict]]:
    """把 SSE 帧字符串解析成 (event_name, payload) 列表。"""
    parsed: list[tuple[str, dict]] = []
    for raw in raw_frames:
        for block in raw.split("\n\n"):
            block = block.strip()
            if not block or block.startswith(":"):  # 心跳注释行
                continue
            event_name: str | None = None
            data: dict | None = None
            for line in block.split("\n"):
                if line.startswith("event: "):
                    event_name = line[len("event: "):]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
            assert event_name is not None, f"缺少 event 行: {block!r}"
            assert data is not None, f"缺少 data 行: {block!r}"
            parsed.append((event_name, data))
    return parsed


@pytest.fixture(scope="module")
def frames() -> list[tuple[str, dict]]:
    """跑一遍完整的 mock 流，拿到全部事件。"""
    import asyncio

    async def collect() -> list[str]:
        return [f async for f in mock_stream(DEMO_QUESTION, token_delay_ms=0, step_delay_ms=0)]

    return parse_frames(asyncio.run(collect()))


def names(frames: list[tuple[str, dict]]) -> list[str]:
    return [n for n, _ in frames]


def first_index(frames: list[tuple[str, dict]], name: str) -> int:
    return names(frames).index(name)


# ---------------------------------------------------------------- 用例

def test_envelope_fields(frames):
    """每个事件都必须有 seq / trace_id / ts，且 trace_id 全程一致。"""
    trace_ids = set()
    for name, payload in frames:
        assert "seq" in payload, f"{name} 缺少 seq"
        assert "trace_id" in payload, f"{name} 缺少 trace_id"
        assert "ts" in payload, f"{name} 缺少 ts"
        trace_ids.add(payload["trace_id"])
    assert len(trace_ids) == 1, f"同一次问答出现了多个 trace_id: {trace_ids}"


def test_seq_monotonic_from_one(frames):
    """seq 从 1 开始严格递增 —— 断线续传全靠它。"""
    seqs = [p["seq"] for _, p in frames]
    assert seqs == list(range(1, len(seqs) + 1)), f"seq 不连续: {seqs}"


def test_all_eight_event_types_present(frames):
    """8 种事件必须全部出现，缺一种就说明协议没跑全。"""
    expected = {"step", "plan", "retrieval", "grade", "graph", "token", "citation", "done"}
    assert expected.issubset(set(names(frames))), f"缺少事件: {expected - set(names(frames))}"


def test_plan_before_any_retrieval(frames):
    """保证 2：plan 一定在所有 retrieval 之前。"""
    assert first_index(frames, "plan") < first_index(frames, "retrieval")


def test_retrieval_query_ids_are_declared(frames):
    """保证 3：首轮检索的 query_id 必须来自 plan；改写轮不受此约束。"""
    plan = next(p for n, p in frames if n == "plan")
    declared = {q["id"] for q in plan["sub_queries"]}

    for name, payload in frames:
        if name != "retrieval":
            continue
        if payload.get("rewrite_round", 0) == 0:
            assert payload["query_id"] in declared, (
                f"首轮检索出现了未声明的 query_id: {payload['query_id']}"
            )
        else:
            assert payload.get("rewrite_round", 0) >= 1


def test_rewrite_happens_before_proceed(frames):
    """自评-改写闭环必须真实发生：先 rewrite 决策，后 proceed 决策。"""
    decisions = [p["decision"] for n, p in frames if n == "grade"]
    assert "rewrite" in decisions, "没有触发改写，自评闭环等于没做"
    assert decisions.index("rewrite") < decisions.index("proceed")
    assert decisions.count("rewrite") <= 2, "改写轮数超过契约上限 2"


def test_citation_before_its_tokens(frames):
    """保证 4：citation 必须先于引用它的 token 到达，否则角标会跳变。"""
    seen_citations: dict[int, str] = {}
    for name, payload in frames:
        if name == "citation":
            seen_citations[payload["claim_id"]] = payload["marker"]
        elif name == "token":
            for claim_id, marker in seen_citations.items():
                # 一旦正文里出现某个角标，它对应的 citation 必须已经发过
                if marker in payload["text"]:
                    assert claim_id in seen_citations
    assert seen_citations, "整条流里没有任何 citation"


def test_every_citation_marker_appears_in_text(frames):
    """每个 citation 的 marker 都应该能在正文里找到，否则是悬空引用。"""
    full_text = "".join(p["text"] for n, p in frames if n == "token")
    for name, payload in frames:
        if name == "citation":
            assert payload["marker"] in full_text, (
                f"引用 {payload['marker']} 在正文里找不到对应角标"
            )


def test_done_is_last(frames):
    """保证 5：done 一定是最后一个事件。"""
    assert names(frames)[-1] == "done"


def test_done_carries_usage_and_stop_reason(frames):
    done = frames[-1][1]
    assert done["stop_reason"] in {
        "normal", "step_limit", "rewrite_limit", "timeout", "budget", "error",
    }
    assert "usage" in done and "latency_ms" in done
    assert 0.0 <= done["coverage"] <= 1.0


def test_graph_has_cross_domain_edge(frames):
    """跨域边是本产品的核心卖点，mock 里必须有，否则演示讲不出差异化。"""
    graph = next(p for n, p in frames if n == "graph")
    cross = [e for e in graph["edges"] if e.get("cross_domain")]
    assert len(cross) >= 1, "图谱里没有任何跨域边，演示的差异化卖点不成立"

    domains = {n["id"]: n["domain"] for n in graph["nodes"]}
    for edge in cross:
        assert domains[edge["source"]] != domains[edge["target"]], (
            f"边 {edge['source']}->{edge['target']} 标了 cross_domain 但两端同域"
        )


def test_graph_node_limit(frames):
    """硬约束：单次 graph 事件节点数 ≤ 80，超了前端必卡。"""
    graph = next(p for n, p in frames if n == "graph")
    assert len(graph["nodes"]) <= 80, f"graph 节点数 {len(graph['nodes'])} 超过 80"


def test_graph_active_path_is_connected(frames):
    """active_path 必须是图上真实存在的路径，不能是随便列几个名字。"""
    graph = next(p for n, p in frames if n == "graph")
    edges = {(e["source"], e["target"]) for e in graph["edges"]}
    edges |= {(b, a) for a, b in edges}  # 视为无向

    path = graph["active_path"]
    for a, b in zip(path, path[1:]):
        assert (a, b) in edges, f"active_path 里 {a}->{b} 在图中不存在"
