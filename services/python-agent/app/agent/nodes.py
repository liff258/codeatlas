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
from app.agent.llm import LLMClient, LLMError, LLMResult
from app.config import settings

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


# 各节点的单次调用超时。差异化设置的理由：
#   免费额度下同一个模型的延迟方差很大（实测 grader 4~17 秒），
#   统一用 30 秒意味着最坏情况要干等 30 秒才降级。
#   每个节点能容忍的等待时间不同——路由只是分类，等 10 秒不值；
#   自评要在"再等等"和"赶紧用兜底继续"之间取舍。
TIMEOUT_ROUTER = 10.0
TIMEOUT_PLANNER = 15.0
TIMEOUT_GRADER = 12.0
TIMEOUT_REWRITER = 12.0


async def _tolerant_json_call(llm: LLMClient, system: str, user: str, **kw) -> LLMResult:
    """调模型要 JSON，瞬时故障就降级，不把异常抛给编排层。

    吞掉的两类（都会让节点走兜底，流程继续）：
    - LLM_TIMEOUT：节点有自己的兜底逻辑，比如 grader 用重排分估覆盖率
    - LLM_RATE_LIMIT：免费额度下 429 是常态（实测一个下午撞三次），
      LLMClient 内部已经重试 2 次，还失败说明这一阵就是挤不进去。
      这时候把 12 条已召回的证据全丢掉、直接报错，是最糟的选择——
      用户什么都看不到。降级成"按重排分估覆盖率"至少还能给出答案。

    不吞的：鉴权失败、参数错误这类。那不是"这一次不通"，
    是"永远不通"，静默降级会让用户以为系统在工作，实际全是兜底结果。

    这个区分是被真实故障逼出来的：grader 一次超时/限流就把整条流打断，
    明明证据都到手了，却一条答案都没生成出来。
    """
    try:
        return await llm.json_call(system, user, **kw)
    except LLMError as e:
        if e.code == "LLM_TIMEOUT":
            return LLMResult(text="", data=None, degraded=True, detail=f"模型超时：{e}")
        if e.code == "LLM_RATE_LIMIT":
            return LLMResult(
                text="", data=None, degraded=True, detail=f"模型限流，已重试仍失败：{e}"
            )
        raise


@lru_cache(maxsize=1)
def _chunk_subject_index() -> tuple[tuple[str, str], ...]:
    """把 (学科, 归一化正文) 一次性载入内存。

    为什么不在 SQL 里做：
        原来对每个实体跑一次
            SELECT ... WHERE replace(lower(content),' ','') LIKE '%实体%'
        replace() 让索引用不上，等于每次全表扫 5456 行。8 个实体就是 8 次，
        实测 graph 节点因此要 19 秒。
        改成一次查询把内容拉进内存（约 3 MB），后续匹配就是纯 Python 子串查找，
        单次 10 毫秒级。
    """
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT subject, replace(lower(content), ' ', '')
                FROM chunk
                WHERE level = 'child' AND subject IS NOT NULL
                """
            )
        ).all()
    return tuple((r[0], r[1]) for r in rows)


@lru_cache(maxsize=256)
def _resolve_subject(entity: str) -> str | None:
    """实体 → 它在整个库里最常出现的学科。

    为什么不能只看"它出现在哪条证据里"：
        问「向量检索为什么不能用 B+ 树加速」时，B+ 树出现在那篇 AI 域的文章里，
        按证据推就会把它标成 ai 域，于是和「向量检索」同域，跨域边消失。
        但这个实体在库里主要出现在 MySQL 的索引文章里，它本质是 backend 的。

    用众数而不是"第一条命中的"：实体可能被多个学科提到，
    出现最多的那个才代表它的归属。
    """
    probe = _norm(entity)
    if not probe:
        return None

    try:
        index = _chunk_subject_index()
    except Exception:  # noqa: BLE001
        # 没有数据库时（单测、离线分析）退回"未知"，由调用方用证据兜底。
        # 图谱是锦上添花的功能，不该因为它让整个流程挂掉。
        return None

    counts: dict[str, int] = {}
    for subject, content in index:
        if probe in content:
            counts[subject] = counts.get(subject, 0) + 1

    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _norm(s: str) -> str:
    """去掉所有空白并转小写，用于实体名和正文的模糊匹配。

    必要性：模型抽出来的实体是「B+树」，而原文写的是「B+ 树」（中间有空格）。
    直接做子串匹配会失配，导致这个实体找不到来源证据、domain 变成 unknown，
    进而把本来同域的边误判成跨域边。
    """
    return re.sub(r"\s+", "", s).lower()


# ---------------------------------------------------------------- 1. 路由


async def route(llm: LLMClient, question: str, history: list[dict]) -> RouterResult:
    hist_text = "\n".join(f"{h['role']}: {h['content'][:120]}" for h in history[-4:]) or "（无）"

    result = await _tolerant_json_call(
        llm,
        prompts.ROUTER_SYSTEM,
        prompts.ROUTER_USER.format(question=question, history=hist_text),
        max_tokens=200,
        timeout=TIMEOUT_ROUTER,
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


async def plan(
    llm: LLMClient,
    question: str,
    intent: str,
    history: list[dict] | None = None,
) -> PlannerResult:
    # 只带最近两轮：足够消解指代，又不会让 prompt 膨胀。
    # 每条截断到 150 字——追问只需要知道"在聊什么"，不需要完整答案。
    hist_text = (
        "\n".join(f"{h['role']}: {h['content'][:150]}" for h in (history or [])[-4:]) or "（无）"
    )
    result = await _tolerant_json_call(
        llm,
        prompts.PLANNER_SYSTEM + prompts.PLANNER_REFERENCE_HINT,
        prompts.PLANNER_USER.format(question=question, intent=intent, history=hist_text),
        # 700 不够：模型会把子查询写成长句，JSON 被截断在中间，
        # 解析直接失败。实测 1000 才能稳定收尾。
        max_tokens=1000,
        timeout=TIMEOUT_PLANNER,
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
    result = await _tolerant_json_call(
        llm,
        prompts.GRADER_SYSTEM,
        # 只喂前 8 条：12 条 × 200 字 = 2400 字，实测 grader 要 15 秒。
        # 前 8 条已经覆盖了重排后最相关的部分，再往后加只会拖慢且边际收益很低。
        prompts.GRADER_USER.format(
            question=question, n=min(8, len(evidence)), evidence=format_evidence(evidence[:8])
        ),
        max_tokens=400,
        timeout=TIMEOUT_GRADER,
    )

    if result.degraded or not result.data:
        # 启发式兜底：用重排分估覆盖率。
        # 重排分本身就是"这条证据和问题的相关度"，取前三条均值比固定给 0.5 有意义。
        #
        # 但必须封顶 0.85：重排分回答的是"这条相关吗"，覆盖率问的是"够不够回答问题"，
        # 两者不是一回事。实测 bge-reranker 对相关文档普遍给 0.9+，
        # 直接当覆盖率会得到 0.97 这种比 LLM 判断（0.75）还高的数，
        # 让系统在证据不足时也显得过度自信。降级路径不该声称"证据充分"。
        top = sorted((e.score for e in evidence), reverse=True)[:3]
        cov = min(0.85, sum(top) / len(top) if top else 0.0)
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
    result = await _tolerant_json_call(
        llm,
        prompts.REWRITER_SYSTEM,
        prompts.REWRITER_USER.format(
            question=question,
            used_queries="\n".join(f"- {q}" for q in used_queries) or "（无）",
            reason=reason or "证据不足",
            next_id=next_id,
        ),
        max_tokens=500,
        timeout=TIMEOUT_REWRITER,
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


# 图谱 LLM 调用的硬超时。实测这个节点要 9~13 秒（模型输出虽短但启动慢），
# 不设上限时它会把整条链路的延迟拖到不可接受。超时就用确定性兜底。
GRAPH_TIMEOUT_SECONDS = 10.0


def entities_from_evidence(evidence: list[Evidence], limit: int = 6) -> list[str]:
    """规划节点降级时的实体兜底：从证据的小标题里取概念名。

    为什么需要：planner 超时会退化成单查询、实体列表为空，图谱就被整个跳过——
    而跨域边是这个产品最核心的视觉证据，不能因为一次 LLM 超时就不画了。

    取 heading_path 的最后一段（小标题通常就是概念名，如「G1 收集器」「HNSW」），
    去掉编号和标点。不追求精确，够画出一张有信息量的图即可。
    """
    out: list[str] = []
    seen: set[str] = set()

    for e in evidence:
        if len(out) >= limit:
            break
        raw = (e.heading_path or "").split(">")[-1].strip()
        # 去掉 "3.2 " 这类编号前缀和常见标点
        name = re.sub(r"^[\d.\s、]+", "", raw)
        name = re.sub(r"[：:，,。.（）()\[\]「」\"'`*#]", "", name).strip()
        if not name or len(name) > 24 or len(name) < 2:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)

    return out


def _infer_rel(text: str) -> str:
    """从共现文本里猜关系类型。

    兜底图谱如果一律标「使用」，会出现「向量检索 使用 B+ 树」这种明显错误的边——
    演示时评委一眼就能看出不对，反而扣分。用关键词猜一个，猜不准至少不会自相矛盾。
    """
    t = text.lower()
    if any(k in t for k in ("对比", "区别", "不同", "vs", "而不是", "不能", "无法")):
        return "对比"
    if any(k in t for k in ("属于", "是一种", "是其中", "分类")):
        return "属于"
    if any(k in t for k in ("导致", "造成", "引起", "因为", "所以")):
        return "导致"
    if any(k in t for k in ("解决", "修复", "避免", "优化")):
        return "解决"
    return "使用"


def _fallback_graph(
    entities: list[str], evidence: list[Evidence], ent_meta: dict[str, tuple[str, str]]
) -> tuple[list[GraphNode], list[GraphEdge], list[str]]:
    """不调模型的兜底图谱：节点来自实体，边来自「同一条证据里共现」。

    关系类型只能是契约里的六种，共现最接近「使用」——虽然不精确，
    但比没有图强：演示时评委要看的是「两个域之间有连线」这件事本身。
    """
    nodes: list[GraphNode] = []
    for name in entities[:8]:
        subject, domain = ent_meta.get(name, ("common", "common"))
        nodes.append(
            GraphNode(id=name, label=name, type="概念", subject=subject,
                      domain=domain, weight=1)  # type: ignore[arg-type]
        )

    domain_of = {n.id: n.domain for n in nodes}
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str]] = set()

    def _link(a: str, b: str, rel: str) -> None:
        key = (a, b) if a < b else (b, a)
        if key in seen:
            return
        seen.add(key)
        both_known = domain_of[a] != "common" and domain_of[b] != "common"
        edges.append(
            GraphEdge(source=a, target=b, rel=rel, weight=1.0,
                      cross_domain=both_known and domain_of[a] != domain_of[b])
        )

    # 第一层：同一条证据里共现 —— 强关联，关系类型从正文推断
    for e in evidence:
        hit = [n for n in entities[:8] if _norm(n) in _norm(e.content)]
        rel = _infer_rel(e.content)
        for i, a in enumerate(hit):
            for b in hit[i + 1 :]:
                _link(a, b, rel)

    # 第二层：同一篇文档里出现 —— 弱关联。
    # 为什么要这层：追问场景下实体常常分散在不同 chunk 里（一个讲 HNSW 的分层结构、
    # 一个讲 B+ 树的全序），同块共现一条边都出不来，图上就只剩一堆孤立的点。
    # 同一篇文档至少说明它们在同一主题下被讨论，比完全没有连线有信息量。
    if not edges:
        by_doc: dict[int, list[str]] = {}
        for e in evidence:
            for n in entities[:8]:
                if _norm(n) in _norm(e.content) and n not in by_doc.setdefault(e.doc_id, []):
                    by_doc[e.doc_id].append(n)
        for names in by_doc.values():
            for i, a in enumerate(names):
                for b in names[i + 1 :]:
                    _link(a, b, "使用")

    # 第三层：同一个学科内 → "属于"关系。
    # 触发场景：实体是从小标题抽的抽象概念名（"记忆与检索技术"），
    # 正文里可能写的是"记忆"和"检索"，字面对不上，前两层都连不上。
    # 但同属一个学科这件事本身是有意义的——图上至少能看出概念聚成几簇，
    # 而不是一堆没有任何连线的孤立点。
    if not edges:
        by_subject: dict[str, list[str]] = {}
        for n in nodes:
            if n.subject and n.subject != "common":
                by_subject.setdefault(n.subject, []).append(n.id)
        for names in by_subject.values():
            for i, a in enumerate(names):
                for b in names[i + 1 :]:
                    _link(a, b, "属于")

    degree: dict[str, int] = {}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1
    for n in nodes:
        n.weight = max(1, degree.get(n.id, 1))

    cross = [e for e in edges if e.cross_domain]
    path = [cross[0].source, cross[0].target] if cross else (
        [edges[0].source, edges[0].target] if edges else []
    )
    return nodes, edges[:10], path


async def extract_graph(
    llm: LLMClient, question: str, evidence: list[Evidence], entities: list[str]
) -> tuple[list[GraphNode], list[GraphEdge], list[str], bool, str]:
    """返回 (nodes, edges, active_path, degraded, detail)。

    ⚠️ `cross_domain` 由代码算，不看模型输出。
    这是产品最核心的视觉证据，绝不能让模型随口判断对错。
    """
    if not entities:
        return [], [], [], True, "没有可用实体，跳过图谱"

    # 实体 → 学科先算出来，兜底图谱也要用
    domains_map = _subject_domains()
    ent_meta_pre: dict[str, tuple[str, str]] = {}
    for name in entities:
        subj = _resolve_subject(name)
        if subj:
            ent_meta_pre[name] = (subj, domains_map.get(subj, "common"))
    for e in evidence:
        for name in entities:
            if name in ent_meta_pre:
                continue
            if _norm(name) in _norm(e.content) or _norm(name) in _norm(e.heading_path):
                ent_meta_pre[name] = (e.subject, e.domain)

    # 默认走确定性图谱：更快、而且实测效果更好（见 config.agent_llm_graph 的注释）
    if not settings.agent_llm_graph:
        fb = _fallback_graph(entities, evidence, ent_meta_pre)
        return (*fb, False, "")

    ent_list = "\n".join(f"- {e}" for e in entities[:8])
    try:
        result = await asyncio.wait_for(
            llm.json_call(
                GRAPH_SYSTEM,
                f"用户问题：{question}\n\n可用实体：\n{ent_list}\n\n证据片段：\n"
                + format_evidence(evidence[:4]),
                max_tokens=400,
            ),
            timeout=GRAPH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        fb = _fallback_graph(entities, evidence, ent_meta_pre)
        return (*fb, True, f"图谱抽取超时（{GRAPH_TIMEOUT_SECONDS:.0f}s），改用共现兜底")

    if result.degraded or not result.data:
        fb = _fallback_graph(entities, evidence, ent_meta_pre)
        return (*fb, True, result.detail or "图谱抽取输出无法解析，改用共现兜底")

    ent_meta = ent_meta_pre

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
        fb = _fallback_graph(entities, evidence, ent_meta_pre)
        return (*fb, True, "图谱节点全部无效，改用共现兜底")

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
        src_domain, dst_domain = domain_of[src], domain_of[dst]
        # ★ 跨域边由 domain 计算，不信任模型。
        # 但要注意：domain 为 common 表示「这个实体没在任何证据里找到」，
        # 那是未知而不是"另一个域"。把它算成跨域会产生假边——
        # 演示时指着一条假跨域边讲，比没有这条边糟得多。
        both_known = src_domain != "common" and dst_domain != "common"
        edges.append(
            GraphEdge(
                source=src,
                target=dst,
                rel=rel if rel in _VALID_RELS else "使用",  # type: ignore[arg-type]
                weight=1.0,
                cross_domain=both_known and src_domain != dst_domain,
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
