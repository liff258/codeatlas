"""六个 Agent 节点。

每个节点都是「输入 → 结构化输出」的纯逻辑，不含 SSE 和编排——
这样可以用 FakeLLM 单独测，不需要网络也不需要数据库。

统一的降级原则：**节点失败不抛异常，返回带 degraded=True 的结果**。
编排层看到 degraded 就把 step 状态标成 `degraded`（前端显示黄色），
然后继续往下跑。宁可给一个粗糙的结果，也不能让整条流断在半路。

⚠️ 检索是同步阻塞的（BM25 + 向量 + 5 秒重排），必须丢到线程里跑，
否则会卡住整个事件循环，心跳都发不出去。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from app.agent import prompts
from app.agent.events import GraphEdge, GraphNode, Intent, SubQuery
from app.agent.llm import LLMClient

GradeDecision = Literal["proceed", "rewrite", "give_up"]

# 证据片段送给模型时，每条截断到这个长度。
# 太长会让 grader 的输入爆掉（12 条 × 500 字 = 6000 字），
# 太短又判断不出"这段有没有回答问题"。200 字是个平衡点。
EVIDENCE_PREVIEW_CHARS = 200


# ---------------------------------------------------------------- 数据结构


@dataclass
class RouterResult:
    intent: Intent = "concept"
    need_retrieval: bool = True
    degraded: bool = False
    detail: str = ""


@dataclass
class PlannerResult:
    hops: int = 2
    sub_queries: list[SubQuery] = field(default_factory=list)
    degraded: bool = False
    detail: str = ""


@dataclass
class Evidence:
    """一条证据。chunk_id 用契约要求的 `c_<数字>` 格式。"""

    chunk_id: str
    raw_id: int
    doc_id: int
    doc_name: str
    heading_path: str
    content: str
    score: float
    subject: str
    domain: str


@dataclass
class GradeResult:
    coverage: float = 0.0
    decision: GradeDecision = "proceed"
    low_score_ids: list[str] = field(default_factory=list)
    reason: str = ""
    degraded: bool = False
    detail: str = ""


# ---------------------------------------------------------------- 工具


@lru_cache(maxsize=1)
def _subject_domains() -> dict[str, str]:
    """学科 → 域。图谱节点的 domain 必须来自这里，不能让模型编。"""
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(text("SELECT code, domain FROM subject_taxonomy")).all()
    return {r[0]: r[1] for r in rows}


def to_chunk_ref(raw_id: int) -> str:
    return f"c_{raw_id}"


def format_evidence(items: list[Evidence]) -> str:
    """按 [1] [2] 编号列给模型。编号顺序 = 最终答案里的引用编号。"""
    lines = []
    for i, e in enumerate(items, start=1):
        body = " ".join(e.content.split())[:EVIDENCE_PREVIEW_CHARS]
        lines.append(f"[{i}] 《{e.doc_name}》{e.heading_path}\n{body}")
    return "\n\n".join(lines)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- 1. 路由


async def route(llm: LLMClient, question: str, history: list[dict]) -> RouterResult:
    hist_text = "\n".join(f"{h['role']}: {h['content'][:120]}" for h in history[-4:]) or "（无）"

    result = await llm.json_call(
        prompts.ROUTER_SYSTEM,
        prompts.ROUTER_USER.format(question=question, history=hist_text),
        max_tokens=200,
    )

    if result.degraded or not result.data:
        # 降级：当成普通概念题，继续查。不猜 chitchat——猜错会直接不检索，
        # 用户问技术问题却得到"你好，有什么可以帮你"是最糟的体验。
        return RouterResult(degraded=True, detail=result.detail or "路由输出无法解析，按概念题处理")

    intent = str(result.data.get("intent", "concept")).strip()
    if intent not in ("concept", "compare", "debug", "quiz", "chitchat"):
        intent = "concept"

    return RouterResult(
        intent=intent,  # type: ignore[arg-type]
        need_retrieval=bool(result.data.get("need_retrieval", True)),
    )


# ---------------------------------------------------------------- 2. 规划


async def plan(llm: LLMClient, question: str, intent: str) -> PlannerResult:
    result = await llm.json_call(
        prompts.PLANNER_SYSTEM,
        prompts.PLANNER_USER.format(question=question, intent=intent),
        max_tokens=700,
    )

    fallback = PlannerResult(
        hops=1,
        sub_queries=[SubQuery(id="q1", text=question, entities=[])],
        degraded=True,
        detail=result.detail or "规划输出无法解析，退化为单查询",
    )

    if result.degraded or not result.data:
        return fallback

    raw = result.data.get("sub_queries")
    if not isinstance(raw, list) or not raw:
        return fallback

    subs: list[SubQuery] = []
    for i, item in enumerate(raw[:4], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        ents = item.get("entities")
        subs.append(
            SubQuery(
                id=f"q{i}",
                text=text,
                entities=[str(e).strip() for e in ents if str(e).strip()][:5]
                if isinstance(ents, list)
                else [],
            )
        )

    if not subs:
        return fallback

    hops = result.data.get("hops", 2)
    try:
        hops = max(1, min(3, int(hops)))
    except (TypeError, ValueError):
        hops = 2

    return PlannerResult(hops=hops, sub_queries=subs)


# ---------------------------------------------------------------- 3. 检索


def retrieve(
    retriever,
    sub_queries: list[SubQuery],
    *,
    top_k: int = 20,
    pool: int = 12,
    query_for_rerank: str = "",
) -> list[Evidence]:
    """同步阻塞，调用方必须用 asyncio.to_thread 包起来。"""
    merged: dict[int, object] = {}

    for sq in sub_queries:
        for hit in retriever.search(sq.text, top_k=top_k, top_n=top_k, rerank=False):
            old = merged.get(hit.chunk_id)
            if old is None or hit.score > old.score:  # type: ignore[attr-defined]
                merged[hit.chunk_id] = hit

    if not merged:
        return []

    candidates = sorted(merged.values(), key=lambda h: h.score, reverse=True)  # type: ignore[attr-defined]
    head = candidates[:pool]

    # 统一重排一次（约 5 秒）。挂了就用融合顺序。
    try:
        from app.rag.rerank import get_reranker

        head = get_reranker().rerank(query_for_rerank, head)
    except Exception:  # noqa: BLE001
        pass

    domains = _subject_domains()
    out: list[Evidence] = []
    for h in head:
        subject = h.subject or "common"
        out.append(
            Evidence(
                chunk_id=to_chunk_ref(h.chunk_id),
                raw_id=h.chunk_id,
                doc_id=h.doc_id,
                doc_name=h.doc_name,
                heading_path=h.heading_path,
                content=h.content,
                score=float(getattr(h, "rerank_score", None) or h.score),
                subject=subject,
                domain=domains.get(subject, "common"),
            )
        )
    return out


# ---------------------------------------------------------------- 4. 自评


async def grade(llm: LLMClient, question: str, evidence: list[Evidence], threshold: float) -> GradeResult:
    result = await llm.json_call(
        prompts.GRADER_SYSTEM,
        prompts.GRADER_USER.format(
            question=question, n=len(evidence), evidence=format_evidence(evidence)
        ),
        max_tokens=400,
    )

    if result.degraded or not result.data:
        # 启发式兜底：用重排分估覆盖率。
        # 这不是随便凑数——重排分本身就是"这条证据和问题的相关度"，
        # 取前三条的均值能反映整体证据质量，比固定给 0.5 有意义。
        top = sorted((e.score for e in evidence), reverse=True)[:3]
        cov = _clamp(sum(top) / len(top) if top else 0.0)
        return GradeResult(
            coverage=cov,
            decision="proceed" if cov >= threshold else "rewrite",
            reason=f"自评输出无法解析，按重排分估算覆盖率 {cov:.2f}",
            degraded=True,
            detail=result.detail,
        )

    try:
        coverage = _clamp(float(result.data.get("coverage", 0.0)))
    except (TypeError, ValueError):
        coverage = 0.0

    low = result.data.get("low_score_ids")
    low_ids = [str(x) for x in low][:10] if isinstance(low, list) else []

    return GradeResult(
        coverage=coverage,
        decision="proceed" if coverage >= threshold else "rewrite",
        low_score_ids=low_ids,
        reason=str(result.data.get("reason", ""))[:200],
    )


# ---------------------------------------------------------------- 5. 改写


async def rewrite(
    llm: LLMClient,
    question: str,
    used_queries: list[str],
    reason: str,
    next_id: int,
) -> tuple[list[SubQuery], bool, str]:
    """返回 (新子查询, 是否降级, 降级原因)。"""
    result = await llm.json_call(
        prompts.REWRITER_SYSTEM,
        prompts.REWRITER_USER.format(
            question=question,
            used_queries="\n".join(f"- {q}" for q in used_queries) or "（无）",
            reason=reason or "证据不足",
            next_id=next_id,
        ),
        max_tokens=500,
    )

    if result.degraded or not result.data:
        return [], True, result.detail or "改写输出无法解析"

    raw = result.data.get("sub_queries")
    if not isinstance(raw, list):
        return [], True, "改写结果缺少 sub_queries 字段"

    subs: list[SubQuery] = []
    for i, item in enumerate(raw[:2], start=next_id):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or text in used_queries:  # 防止模型原地打转
            continue
        ents = item.get("entities")
        subs.append(
            SubQuery(
                id=f"q{i}",
                text=text,
                entities=[str(e).strip() for e in ents][:5] if isinstance(ents, list) else [],
            )
        )

    if not subs:
        return [], True, "改写没有产出新查询"
    return subs, False, ""


# ---------------------------------------------------------------- 6. 生成


async def generate(llm: LLMClient, question: str, evidence: list[Evidence]):
    """流式生成。逐个 delta 吐文本。"""
    async for piece in llm.stream_call(
        prompts.GENERATOR_SYSTEM,
        prompts.GENERATOR_USER.format(question=question, evidence=format_evidence(evidence)),
        max_tokens=1600,
    ):
        yield piece


# ---------------------------------------------------------------- 7. 图谱

_VALID_NODE_TYPES = ("概念", "组件", "算法", "参数", "问题")
_VALID_RELS = ("依赖", "属于", "对比", "导致", "解决", "使用")

GRAPH_SYSTEM = """你是知识图谱抽取器。从证据里抽出核心概念和它们之间的关系。

规则：
1. **节点只能是给定的实体**，不要新增。每个实体给一个类型和一句话标签。
2. 关系只能是：依赖 / 属于 / 对比 / 导致 / 解决 / 使用
3. 最多 8 个节点、10 条边。宁可少而准，不要多而乱。
4. 只抽证据里**确实提到**的关系，不要凭常识补充

只输出 JSON，不要任何解释文字：
{"nodes": [{"id": "HNSW", "label": "HNSW 分层图", "type": "算法"}],
 "edges": [{"source": "RAG", "target": "HNSW", "rel": "使用"}]}
"""


async def extract_graph(
    llm: LLMClient, question: str, evidence: list[Evidence], entities: list[str]
) -> tuple[list[GraphNode], list[GraphEdge], list[str], bool, str]:
    """返回 (nodes, edges, active_path, degraded, detail)。

    ⚠️ `cross_domain` 由代码算，不看模型输出。
    这是产品最核心的视觉证据，绝不能让模型随口判断对错。
    """
    if not entities:
        return [], [], [], True, "没有可用实体，跳过图谱"

    ent_list = "\n".join(f"- {e}" for e in entities[:8])
    result = await llm.json_call(
        GRAPH_SYSTEM,
        f"用户问题：{question}\n\n可用实体：\n{ent_list}\n\n证据片段：\n"
        + format_evidence(evidence[:6]),
        max_tokens=700,
    )

    if result.degraded or not result.data:
        return [], [], [], True, result.detail or "图谱抽取输出无法解析"

    # 实体 → 它出现在哪条证据里 → 那条证据的学科和域
    ent_meta: dict[str, tuple[str, str]] = {}
    for e in evidence:
        for name in entities:
            if name in ent_meta:
                continue
            if name.lower() in e.content.lower() or name in e.heading_path:
                ent_meta[name] = (e.subject, e.domain)

    nodes: list[GraphNode] = []
    seen: set[str] = set()

    raw_nodes = result.data.get("nodes")
    for item in raw_nodes if isinstance(raw_nodes, list) else []:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id", "")).strip()
        if not nid or nid in seen or nid not in entities:
            continue  # 只认给定实体，模型编的一律丢弃
        seen.add(nid)
        ntype = str(item.get("type", "概念"))
        subject, domain = ent_meta.get(nid, ("common", "common"))
        nodes.append(
            GraphNode(
                id=nid,
                label=str(item.get("label", nid))[:24],
                type=ntype if ntype in _VALID_NODE_TYPES else "概念",  # type: ignore[arg-type]
                subject=subject,
                domain=domain,  # type: ignore[arg-type]
                weight=1,
            )
        )

    if not nodes:
        return [], [], [], True, "图谱节点全部无效"

    domain_of = {n.id: n.domain for n in nodes}
    edges: list[GraphEdge] = []

    raw_edges = result.data.get("edges")
    for item in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", "")).strip()
        dst = str(item.get("target", "")).strip()
        if src not in domain_of or dst not in domain_of or src == dst:
            continue
        rel = str(item.get("rel", "使用"))
        edges.append(
            GraphEdge(
                source=src,
                target=dst,
                rel=rel if rel in _VALID_RELS else "使用",  # type: ignore[arg-type]
                weight=1.0,
                # ★ 跨域边由 domain 计算，不信任模型
                cross_domain=domain_of[src] != domain_of[dst],
            )
        )

    # 度数当权重，前端用它决定节点大小
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1
    for n in nodes:
        n.weight = degree.get(n.id, 1)

    # 推理路径：优先走跨域边，这是演示时要讲的那条链
    active_path: list[str] = []
    cross = [e for e in edges if e.cross_domain]
    if cross:
        active_path = [cross[0].source, cross[0].target]
    elif edges:
        active_path = [edges[0].source, edges[0].target]

    return nodes, edges, active_path, False, ""


# ---------------------------------------------------------------- 引用拦截


_MARKER = re.compile(r"\[(\d{1,2})\]")


class CitationInterceptor:
    """把流式文本里的 [n] 拦下来，先发 citation 再发正文。

    契约 4.7 要求 citation 必须**先于**对应 token 到达，否则角标会先渲染成裸文本再跳变。
    但流式时我们无法预知下一个字符是什么，所以需要缓冲：

    - 正常字符直接放行
    - 遇到 `[` 就暂存，最多等 4 个字符（`[12]` 最长 4 字符）
    - 凑成 `[n]` 且 n 在证据范围内 → 发 citation
    - 不是合法标记（比如 `[a]` 或 `[99]`）→ 原样吐出，不绑定引用

    `[99]` 这种越界编号是模型幻觉，**必须原样保留在正文里但不发 citation**，
    前端会给它显示「无出处」——这比悄悄删掉更诚实。
    """

    def __init__(self, evidence: list[Evidence]) -> None:
        self._evidence = evidence
        self._buf = ""
        self.emitted: set[int] = set()  # 已经发过 citation 的编号，避免重复

    def feed(self, text: str) -> list[tuple[int | None, str]]:
        """喂入一段增量文本，返回 [(要发的证据编号 或 None, 要发的文本)]。

        编号非 None 时，调用方应先发 citation 再发文本。
        """
        self._buf += text
        out: list[tuple[int | None, str]] = []

        while self._buf:
            idx = self._buf.find("[")
            if idx == -1:
                out.append((None, self._buf))
                self._buf = ""
                break

            if idx > 0:
                out.append((None, self._buf[:idx]))
                self._buf = self._buf[idx:]

            # 此时 buf 以 "[" 开头
            m = _MARKER.match(self._buf)
            if m:
                n = int(m.group(1))
                marker_text = m.group(0)
                self._buf = self._buf[len(marker_text) :]
                if 1 <= n <= len(self._evidence) and n not in self.emitted:
                    self.emitted.add(n)
                    out.append((n, marker_text))
                else:
                    out.append((None, marker_text))
                continue

            # 还没凑成完整标记，且长度不足以判断 → 继续等
            if len(self._buf) < 5:
                break

            # 明确不是标记（比如 "[注]"）→ 吐掉 "[" 继续
            out.append((None, "["))
            self._buf = self._buf[1:]

        return out

    def flush(self) -> str:
        rest = self._buf
        self._buf = ""
        return rest
