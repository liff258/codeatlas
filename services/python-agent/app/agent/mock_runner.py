"""P0 阶段的假 Agent：按 contracts/sse-events.md 输出完整事件序列。

作用不是"占位"，而是三件事：
1. 让前端在没有任何模型依赖的情况下，把流式渲染 / 思考面板 / 图谱动画全部做完
2. 让 Java 网关在 Python 还没接真模型时，就能把透传链路调通
3. 直接充当 web/src/mock/stream.jsonl 的数据源（VITE_MOCK=1 回放用）

内容用的是演示主线那道跨域题，所以这份 mock 同时也是演示视频的脚本。

⚠️ 这里的事件顺序必须与 contracts/sse-events.md 第 5 节完全一致，
   否则前端在 mock 模式下调好的布局，切到真实链路会错位。
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator

from app.agent.events import (
    ChunkHit,
    EventStream,
    GraphEdge,
    GraphNode,
    SourceRef,
    SubQuery,
    Usage,
)

# ---------------------------------------------------------------- 演示内容

DEMO_QUESTION = "向量检索为什么不能用 B+ 树加速？那 RAG 的召回率该怎么提？"

DEMO_ANSWER = (
    "B+ 树解决的是**一维有序数据**的查找问题：所有键按大小排成一条线，"
    "查询时沿树做二分，所以等值查询和范围查询都能做到 O(log n)。\n\n"
    "这个前提在向量检索里不成立。1024 维向量之间没有「大小」这种全序关系，只有距离。"
    "没有全序，就没有可以二分的东西，B+ 树的结构直接失效。\n\n"
    "这就是为什么向量检索必须用 ANN 近似最近邻索引。HNSW 把向量组织成一张多层图："
    "上层稀疏、跨度大，负责快速跳到目标区域；下层稠密、精度高，负责局部收敛。"
    "查询时从顶层贪心下降，用一点召回率换几个数量级的加速。\n\n"
    "所以两者不是「谁更快」的关系，而是解决不同问题的两种结构：B+ 树保证精确，HNSW 保证可用。\n\n"
    "至于 RAG 召回率怎么提，换索引只是一部分。收益最大的三处："
    "一是混合检索，向量管语义、BM25 管关键词，用 RRF 融合；"
    "二是 rerank，先粗排 20 条再用 cross-encoder 精排到 5 条；"
    "三是切片策略，小块检索、大块生成。"
)

# 引用锚点：正文里的段落序号 → 出处
DEMO_CITATIONS = [
    (
        1,
        "B+ 树是一维有序结构，所有键按大小排列，因此等值查询和范围查询都能沿树二分，复杂度 O(log n)。",
        SourceRef(doc_id=4, doc_name="JavaGuide · MySQL", heading_path="MySQL > 索引 > B+ 树"),
        ["c_031"],
    ),
    (
        2,
        "高维向量之间不存在可比较的全序关系，只有距离度量，因此基于比较的树形索引（B+ 树、红黑树）无法直接适用。",
        SourceRef(doc_id=21, doc_name="【自写】向量检索 vs B+ 树", heading_path="2. 为什么树形索引失效"),
        ["c_102"],
    ),
    (
        3,
        "HNSW 构建多层可导航小世界图，上层稀疏用于快速跳转，下层稠密用于精确收敛，查询自顶向下贪心搜索。",
        SourceRef(doc_id=12, doc_name="HNSW 原论文摘录", heading_path="3. 分层图结构"),
        ["c_148"],
    ),
    (
        5,
        "提升 RAG 召回质量的三个主要手段：混合检索（向量+关键词 RRF 融合）、重排序（cross-encoder）、以及父子块切片策略。",
        SourceRef(doc_id=15, doc_name="LlamaIndex · Production RAG", heading_path="优化 > 检索质量"),
        ["c_205"],
    ),
]


def _split_for_stream(text: str, size: int = 14) -> list[str]:
    """把答案切成适合流式渲染的小片。

    优先在标点处断开，避免把一个词从中间劈开导致光标位置跳动。
    """
    pieces: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= size and (ch in "，。；：！？、\n" or len(buf) >= size + 8):
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces


def _new_trace_id() -> str:
    return "t_" + secrets.token_hex(3)


# ---------------------------------------------------------------- 事件编排

def _build_graph_payload() -> tuple[list[GraphNode], list[GraphEdge], list[str]]:
    nodes = [
        GraphNode(id="RAG", label="RAG", type="概念", subject="RAG", domain="ai", weight=6),
        GraphNode(id="向量检索", label="向量检索", type="概念", subject="向量检索", domain="ai", weight=5),
        GraphNode(id="HNSW", label="HNSW", type="算法", subject="向量检索", domain="ai", weight=4),
        GraphNode(id="ANN", label="ANN 近似最近邻", type="概念", subject="向量检索", domain="ai", weight=3),
        GraphNode(id="rerank", label="重排序", type="组件", subject="RAG", domain="ai", weight=3),
        GraphNode(id="混合检索", label="混合检索", type="概念", subject="RAG", domain="ai", weight=2),
        GraphNode(id="B+树", label="B+ 树索引", type="算法", subject="MySQL", domain="backend", weight=5),
        GraphNode(id="MySQL索引", label="MySQL 索引", type="概念", subject="MySQL", domain="backend", weight=4),
    ]
    edges = [
        GraphEdge(source="RAG", target="向量检索", rel="使用"),
        GraphEdge(source="向量检索", target="HNSW", rel="使用"),
        GraphEdge(source="向量检索", target="ANN", rel="属于"),
        GraphEdge(source="RAG", target="rerank", rel="使用"),
        GraphEdge(source="RAG", target="混合检索", rel="使用"),
        GraphEdge(source="B+树", target="MySQL索引", rel="属于"),
        # ★ 跨域边：这两条是整个演示的核心证据
        GraphEdge(source="RAG", target="B+树", rel="对比", weight=0.8, cross_domain=True),
        GraphEdge(source="向量检索", target="B+树", rel="对比", weight=0.9, cross_domain=True),
    ]
    # 推理路径：RAG → 向量检索 →(跨域)→ B+ 树
    active_path = ["RAG", "向量检索", "B+树"]
    return nodes, edges, active_path


async def mock_stream(
    question: str,
    session_id: int | None = None,
    history: list[dict] | None = None,
    token_delay_ms: int = 22,
    step_delay_ms: int = 120,
) -> AsyncIterator[str]:
    """产出完整的 SSE 事件序列。"""
    es = EventStream(_new_trace_id())
    started = asyncio.get_event_loop().time()

    # ---------- 1. 意图路由 ----------
    yield es.step("router", "running", "判断问题意图")
    await asyncio.sleep(step_delay_ms / 1000)
    yield es.step(
        "router",
        "ok",
        "意图：跨域概念对比（concept + compare）",
        detail="mock 模式：忽略真实输入，固定输出演示主线",
    )

    # ---------- 2. 查询规划 ----------
    yield es.step("planner", "running", "拆解子查询")
    await asyncio.sleep(step_delay_ms / 1000)
    sub_queries = [
        SubQuery(id="q1", text="B+ 树为什么适合等值查询和范围查询", entities=["B+树", "MySQL索引"]),
        SubQuery(id="q2", text="向量检索为什么需要 ANN 索引", entities=["向量检索", "ANN"]),
        SubQuery(id="q3", text="HNSW 分层图结构与 B+ 树的差异", entities=["HNSW", "B+树"]),
        SubQuery(id="q4", text="RAG 召回率优化 rerank 混合检索", entities=["RAG", "rerank"]),
    ]
    yield es.plan("concept", 2, sub_queries)

    # ---------- 3. 并行检索（第一轮）----------
    yield es.step("retriever", "running", "混合检索 4 个子查询")
    await asyncio.sleep(step_delay_ms / 1000)

    yield es.retrieval("q1", "hybrid", [
        ChunkHit(id="c_031", doc_id=4, score=0.88, vec_rank=1, bm25_rank=1, rrf_score=0.032,
                 heading_path="MySQL > 索引 > B+ 树", preview="B+ 树是一种多路平衡查找树，所有数据都在叶子节点…"),
        ChunkHit(id="c_034", doc_id=4, score=0.71, vec_rank=3, bm25_rank=2, rrf_score=0.021,
                 heading_path="MySQL > 索引 > 索引失效场景", preview="范围查询、等值查询能走索引，但函数运算会失效…"),
    ])
    await asyncio.sleep(0.08)

    yield es.retrieval("q2", "hybrid", [
        ChunkHit(id="c_102", doc_id=21, score=0.79, vec_rank=1, bm25_rank=3, rrf_score=0.029,
                 heading_path="2. 为什么树形索引失效", preview="高维空间里没有全序，基于比较的树结构无法直接适用…"),
        ChunkHit(id="c_140", doc_id=12, score=0.64, vec_rank=5, bm25_rank=6, rrf_score=0.014,
                 heading_path="2. 近似最近邻", preview="ANN 通过牺牲少量召回率换取数量级的查询加速…"),
    ])
    await asyncio.sleep(0.08)

    yield es.retrieval("q3", "hybrid", [
        ChunkHit(id="c_148", doc_id=12, score=0.52, vec_rank=8, bm25_rank=11, rrf_score=0.009,
                 heading_path="3. 分层图结构", preview="HNSW 上层稀疏、下层稠密，查询自顶向下贪心搜索…"),
    ])
    await asyncio.sleep(0.08)

    yield es.retrieval("q4", "hybrid", [
        ChunkHit(id="c_205", doc_id=15, score=0.68, vec_rank=2, bm25_rank=4, rrf_score=0.026,
                 heading_path="优化 > 检索质量", preview="混合检索用 RRF 融合向量与关键词结果，再交给 reranker 精排…"),
    ])

    # ---------- 4. 证据自评（第一轮：不够）----------
    yield es.step("grader", "running", "评估证据覆盖度")
    await asyncio.sleep(step_delay_ms / 1000)
    yield es.grade(
        coverage=0.42,
        threshold=0.6,
        decision="rewrite",
        rewrite_n=0,
        low_score_chunk_ids=["c_148"],
        reason="HNSW 与 B+ 树的结构差异只有一条弱相关证据，不足以支撑「对比」结论",
    )

    # ---------- 5. 查询改写 ----------
    yield es.step("rewriter", "ok", "改写查询：补充术语与中英对照")
    await asyncio.sleep(step_delay_ms / 1000)

    yield es.step("retriever", "running", "重检索 1 个子查询")
    await asyncio.sleep(0.1)
    yield es.retrieval("q5", "hybrid", [
        ChunkHit(id="c_150", doc_id=12, score=0.86, vec_rank=1, bm25_rank=2, rrf_score=0.031,
                 heading_path="3. 分层图结构 > 搜索过程", preview="greedy search 从 entry point 出发，逐层下降…"),
        ChunkHit(id="c_103", doc_id=21, score=0.74, vec_rank=3, bm25_rank=5, rrf_score=0.018,
                 heading_path="3. 两者的取舍", preview="树结构保证精确，图结构保证可用，这是精确与近似的取舍…"),
    ], rewrite_round=1)

    # ---------- 6. 证据自评（第二轮：够了）----------
    yield es.grade(
        coverage=0.78,
        threshold=0.6,
        decision="proceed",
        rewrite_n=1,
        reason="补充到 HNSW 搜索过程与结构对比后，证据足够支撑结论",
    )

    # ---------- 7. 图谱 ----------
    nodes, edges, active_path = _build_graph_payload()
    yield es.graph(nodes, edges, active_path)

    # ---------- 8. 生成 ----------
    yield es.step("generator", "running", "组织答案并绑定引用")
    await asyncio.sleep(step_delay_ms / 1000)

    cite_map = {claim_id: (quote, source, chunk_ids) for claim_id, quote, source, chunk_ids in DEMO_CITATIONS}

    # 按段落生成：每段先发 citation，再逐片发 token。
    # 不要靠扫描 "\n\n" 来判断段落边界——分片时换行符可能被切开，判定会错位。
    paragraphs = [p for p in DEMO_ANSWER.split("\n\n") if p.strip()]
    for idx, para in enumerate(paragraphs, start=1):
        if idx in cite_map:
            quote, source, chunk_ids = cite_map[idx]
            # 契约要求：citation 必须先于它引用的 token 到达
            yield es.citation(idx, f"[{idx}]", chunk_ids, quote, source)
        text = para + (f"[{idx}]" if idx in cite_map else "") + "\n\n"
        for piece in _split_for_stream(text):
            yield es.token(piece)
            await asyncio.sleep(token_delay_ms / 1000)

    yield es.step("generator", "ok", "生成完成")

    # ---------- 9. 结束 ----------
    elapsed_ms = int((asyncio.get_event_loop().time() - started) * 1000)
    yield es.done(
        stop_reason="normal",
        coverage=0.78,
        rewrite_count=1,
        latency_ms=elapsed_ms,
        usage=Usage(input_tokens=9840, output_tokens=1480, cost_cny=0.021),
        insufficient_evidence=False,
    )
