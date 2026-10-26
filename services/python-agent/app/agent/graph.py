"""Agent 编排：把六个节点串成一条符合 contracts/sse-events.md 的事件流。

为什么不用 LangGraph：
    这个流程是「线性 + 一个重试环」，用 while 循环 + 显式状态就能写清楚。
    引入图框架后，每一步在哪里发生、异常怎么传播都变得不直观，
    而评审恰恰会问"你这个 Agent 的循环控制在哪里"——代码里能一眼看到最好。

四道硬约束（缺一个就可能挂住）：
    max_steps      节点跳数上限，防止节点之间来回跳
    max_rewrite    改写轮数上限，防止反复重查
    timeout        整体超时，防止单次调用卡死拖垮请求
    token_budget   累计 token 上限，防止一次问题烧掉免费额度

超限时必须发 `done`（带对应 stop_reason）而不是直接 return，
否则前端状态机收不了尾，界面永远停在"正在思考"。

⚠️ `step` 事件的 node 字段只允许 8 个值（见 contracts/sse-events.md 4.1）：
   router / planner / retriever / grader / rewriter / tool / citation / generator
   图谱抽取没有专属节点，用 `tool` 表示——它不是推理环节，是辅助抽取。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from app.agent import nodes
from app.agent.events import ChunkHit, EventStream, SourceRef, SubQuery
from app.agent.llm import LLMClient, LLMError
from app.config import settings

logger = logging.getLogger(__name__)


def _to_chunk_hits(evidence: list[nodes.Evidence]) -> list[ChunkHit]:
    return [
        ChunkHit(
            id=e.chunk_id,
            doc_id=e.doc_id,
            score=round(e.score, 4),
            heading_path=e.heading_path,
            preview=" ".join(e.content.split())[:80],
        )
        for e in evidence
    ]


def _distribute(evidence: list[nodes.Evidence], subs: list[SubQuery]) -> list[tuple[SubQuery, list[nodes.Evidence]]]:
    """把合并后的证据按子查询轮流分配。

    检索是合并做的（为了只重排一次），但 retrieval 事件必须按 query_id 分组——
    前端思考面板靠它展示"每个子查询查到了什么"。轮流分配是个折中：
    不完美反映每个子查询的真实命中，但保证每个 query_id 都有内容可渲染，
    且总条数不重复。真要精确分组就得每个子查询各排一次，那是 20 秒的代价。
    """
    if not subs or not evidence:
        return []
    buckets: list[list[nodes.Evidence]] = [[] for _ in subs]
    for i, e in enumerate(evidence):
        buckets[i % len(subs)].append(e)
    return [(sq, b) for sq, b in zip(subs, buckets) if b]


async def agent_stream(
    question: str,
    session_id: int | None = None,
    history: list[dict] | None = None,
    trace_id: str | None = None,
) -> AsyncIterator[str]:
    """真实 Agent 主循环。签名与 mock_stream 保持一致，便于路由层切换。"""
    from app.agent.mock_runner import _new_trace_id

    es = EventStream(trace_id or _new_trace_id())
    started = time.monotonic()
    history = history or []

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    def over_timeout() -> bool:
        return (time.monotonic() - started) > settings.agent_timeout_seconds

    def over_budget() -> bool:
        if llm is None:
            return False
        u = llm.usage
        return (u.input_tokens + u.output_tokens) > settings.agent_token_budget

    llm: LLMClient | None = None
    rewrite_count = 0
    coverage = 0.0
    stop_reason = "normal"
    intent = "concept"
    answer_parts: list[str] = []

    def tok(text: str) -> str:
        """发一个 token，同时累计答案。

        落库要用完整答案，但 token 是一个个吐出去的——只能在发的时候顺手攒。
        """
        answer_parts.append(text)
        return es.token(text)

    async def persist_trace(stop: str) -> None:
        """把这次执行写进 agent_trace / agent_step。

        放线程里跑：写库是同步阻塞的，直接在事件循环里做会卡住最后一个 token 的发送。
        失败只记日志——用户已经拿到答案了，不能因为"事后可查"这件事让请求失败。
        """
        from app.agent import trace as trace_store

        await asyncio.to_thread(
            trace_store.save,
            trace_id=es.trace_id,
            session_id=session_id,
            question=question,
            answer="".join(answer_parts),
            intent=intent,
            rewrite_count=rewrite_count,
            coverage=coverage,
            stop_reason=stop,
            latency_ms=elapsed_ms(),
            usage=llm.usage if llm else None,
            steps=es.steps,
        )

    try:
        # 没有 key 时构造会抛 LLMError，被下面的 except 捕获成 error 事件。
        # 不做静默降级到 mock——否则用户以为模型在工作，实际看到的是假答案。
        llm = LLMClient()

        # ---------- 1. 路由 ----------
        yield es.step("router", "running", "判断问题意图")
        router = await nodes.route(llm, question, history)
        intent = router.intent
        yield es.step(
            "router",
            "degraded" if router.degraded else "ok",
            f"意图：{router.intent}",
            detail=router.detail or None,
        )

        if not router.need_retrieval:
            yield es.step("generator", "running", "直接回应")
            async for piece in llm.stream_call(
                "你是计算机知识问答助手。用户在寒暄或问了与知识库无关的问题，"
                "用一两句话简短回应，并引导他问具体的技术问题。",
                question,
                max_tokens=200,
            ):
                yield tok(piece)
            yield es.step("generator", "ok", "回应完成")
            await persist_trace("normal")
            yield es.done(stop_reason="normal", latency_ms=elapsed_ms(), usage=llm.usage)
            return

        # ---------- 2. 规划 ----------
        yield es.step("planner", "running", "拆解子查询")
        planner = await nodes.plan(llm, question, router.intent, history)
        yield es.plan(router.intent, planner.hops, planner.sub_queries)
        if planner.degraded:
            yield es.step("planner", "degraded", "规划降级为单查询", detail=planner.detail)

        # ---------- 3. 检索 ----------
        from app.rag.retrieve import get_retriever

        yield es.step("retriever", "running", f"混合检索 {len(planner.sub_queries)} 个子查询")
        # 用单例而不是每次重建：BM25 索引建一次要 2 秒，索引本身是只读的
        retriever = await asyncio.to_thread(get_retriever)
        evidence = await asyncio.to_thread(
            nodes.retrieve, retriever, planner.sub_queries, query_for_rerank=question
        )

        if not evidence:
            await persist_trace("error")
            yield es.error("RETRIEVAL_EMPTY", "知识库里还没有相关内容")
            yield es.done(stop_reason="error", latency_ms=elapsed_ms(), usage=llm.usage)
            return

        for sq, part in _distribute(evidence, planner.sub_queries):
            yield es.retrieval(sq.id, "hybrid", _to_chunk_hits(part))
        yield es.step("retriever", "ok", f"召回 {len(evidence)} 条证据")

        # ---------- 4. 自评 ----------
        yield es.step("grader", "running", "评估证据覆盖度")
        graded = await nodes.grade(llm, question, evidence, settings.agent_coverage_threshold)
        coverage = graded.coverage
        yield es.grade(
            coverage=graded.coverage,
            threshold=settings.agent_coverage_threshold,
            decision=graded.decision,
            rewrite_n=rewrite_count,
            low_score_chunk_ids=graded.low_score_ids,
            reason=graded.reason,
        )
        yield es.step(
            "grader",
            "degraded" if graded.degraded else "ok",
            f"覆盖率 {graded.coverage:.2f}（阈值 {settings.agent_coverage_threshold}）",
            detail=graded.detail or None,
        )

        # ---------- 5. 改写重查 ----------
        used_queries = [sq.text for sq in planner.sub_queries]
        next_qid = len(planner.sub_queries) + 1

        while graded.decision == "rewrite" and rewrite_count < settings.agent_max_rewrite:
            if over_timeout() or over_budget():
                stop_reason = "timeout" if over_timeout() else "budget"
                break

            rewrite_count += 1
            yield es.step("rewriter", "running", f"第 {rewrite_count} 轮改写")

            new_subs, rw_degraded, rw_detail = await nodes.rewrite(
                llm, question, used_queries, graded.reason, next_qid
            )
            if rw_degraded or not new_subs:
                yield es.step("rewriter", "degraded", "改写失败，使用现有证据", detail=rw_detail)
                yield es.grade(
                    coverage=coverage,
                    threshold=settings.agent_coverage_threshold,
                    decision="give_up",
                    rewrite_n=rewrite_count,
                    low_score_chunk_ids=graded.low_score_ids,
                    reason=f"改写失败，按现有证据生成：{rw_detail}",
                )
                break

            yield es.step("rewriter", "ok", f"新增 {len(new_subs)} 个查询")
            used_queries.extend(sq.text for sq in new_subs)
            next_qid += len(new_subs)

            yield es.step("retriever", "running", f"重检索 {len(new_subs)} 个查询")
            more = await asyncio.to_thread(
                nodes.retrieve, retriever, new_subs, query_for_rerank=question
            )
            for sq, part in _distribute(more, new_subs):
                yield es.retrieval(sq.id, "hybrid", _to_chunk_hits(part), rewrite_round=rewrite_count)

            # 新证据优先，旧证据补在后面并去重
            seen = {e.chunk_id for e in more}
            evidence = (more + [e for e in evidence if e.chunk_id not in seen])[:12]

            yield es.step("grader", "running", "重新评估证据")
            graded = await nodes.grade(llm, question, evidence, settings.agent_coverage_threshold)
            coverage = graded.coverage
            yield es.grade(
                coverage=graded.coverage,
                threshold=settings.agent_coverage_threshold,
                decision=graded.decision,
                rewrite_n=rewrite_count,
                low_score_chunk_ids=graded.low_score_ids,
                reason=graded.reason,
            )

        if rewrite_count >= settings.agent_max_rewrite and graded.decision == "rewrite":
            stop_reason = "rewrite_limit"

        # ---------- 6. 图谱（用 tool 节点，契约里没有 graph 节点）----------
        all_entities: list[str] = []
        for sq in planner.sub_queries:
            for e in sq.entities:
                if e not in all_entities:
                    all_entities.append(e)

        # 规划降级时实体列表是空的，图谱会被整个跳过——而跨域边是核心视觉证据。
        # 这里从证据小标题里兜底抽实体，保证图能画出来。
        if not all_entities:
            all_entities = nodes.entities_from_evidence(evidence)

        yield es.step("tool", "running", "抽取实体关系")
        g_nodes, g_edges, g_path, _, g_detail = await nodes.extract_graph(
            llm, question, evidence, all_entities
        )
        if g_nodes:
            yield es.graph(g_nodes, g_edges, g_path)
            yield es.step("tool", "ok", f"{len(g_nodes)} 个节点 / {len(g_edges)} 条边")
        else:
            yield es.step("tool", "degraded", "跳过图谱", detail=g_detail)

        # ---------- 7. 生成 ----------
        yield es.step("generator", "running", "组织答案并绑定引用")
        yield es.step("citation", "running", "绑定引用出处")

        interceptor = nodes.CitationInterceptor(evidence)
        cite_meta = {i + 1: e for i, e in enumerate(evidence)}
        emitted_count = 0

        try:
            async for piece in nodes.generate(llm, question, evidence):
                for claim_no, text in interceptor.feed(piece):
                    if claim_no is not None:
                        ev = cite_meta[claim_no]
                        yield es.citation(
                            claim_id=claim_no,
                            marker=f"[{claim_no}]",
                            chunk_ids=[ev.chunk_id],
                            quote=" ".join(ev.content.split())[:100],
                            source=SourceRef(
                                doc_id=ev.doc_id,
                                doc_name=ev.doc_name,
                                heading_path=ev.heading_path,
                            ),
                        )
                        emitted_count += 1
                    if text:
                        yield tok(text)

            rest = interceptor.flush()
            if rest:
                yield tok(rest)

        except LLMError as e:
            # 限流和超时都走抽取式兜底：用户至少能看到检索到了什么。
            # 鉴权/参数错误才上抛——那种情况重试也没用，而且必须让人知道配错了。
            if e.code not in ("LLM_TIMEOUT", "LLM_RATE_LIMIT"):
                raise
            logger.warning("generator 降级（%s），改用抽取式兜底", e.code)
            for piece in _extractive_tokens(evidence, str(e)):
                yield tok(piece)
            stop_reason = "error"
        except Exception:  # noqa: BLE001
            # 生成失败 → 抽取式兜底。让用户至少看到检索到了什么，而不是空答案。
            logger.exception("generator failed")
            for piece in _extractive_tokens(evidence, "生成失败"):
                yield tok(piece)
            stop_reason = "error"

        yield es.step("citation", "ok", f"绑定 {emitted_count} 处引用")
        yield es.step("generator", "ok" if stop_reason == "normal" else "degraded", "生成完成")

        # ---------- 8. 结束 ----------
        await persist_trace(stop_reason)
        yield es.done(
            stop_reason=stop_reason,  # type: ignore[arg-type]
            coverage=coverage,
            rewrite_count=rewrite_count,
            latency_ms=elapsed_ms(),
            usage=llm.usage,
            insufficient_evidence=coverage < settings.agent_coverage_threshold,
        )

    except LLMError as e:
        logger.warning("agent llm error: %s", e)
        await persist_trace("error")
        yield es.error(e.code, str(e))
        yield es.done(
            stop_reason="error",
            coverage=coverage,
            rewrite_count=rewrite_count,
            latency_ms=elapsed_ms(),
            usage=llm.usage if llm else None,
        )
    finally:
        if llm is not None:
            await llm.close()
