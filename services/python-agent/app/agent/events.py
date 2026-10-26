"""SSE 事件协议的唯一实现。

契约文件：contracts/sse-events.md
任何字段变更必须先在契约里改，再改这里，最后改前端 web/src/lib/sse.ts。

设计要点：
- 用 pydantic 模型约束每个事件的字段，避免手拼 dict 拼错 key
- seq 单调递增由 EventStream 统一管理，调用方不关心
- 只负责「生产」事件字符串，不关心传输（那是 api 层的事）
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 类型定义

Node = Literal[
    "router", "planner", "retriever", "grader",
    "rewriter", "tool", "citation", "generator",
]
StepStatus = Literal["running", "ok", "degraded", "failed"]
Intent = Literal["concept", "compare", "debug", "quiz", "chitchat"]
GradeDecision = Literal["proceed", "rewrite", "give_up"]
StopReason = Literal["normal", "step_limit", "rewrite_limit", "timeout", "budget", "error"]
Domain = Literal["backend", "ai", "common"]


# ---------------------------------------------------------------- 事件载荷

class _Envelope(BaseModel):
    seq: int
    trace_id: str
    ts: int


class StepEvent(_Envelope):
    node: Node
    status: StepStatus
    label: str
    detail: str | None = None


class SubQuery(BaseModel):
    id: str
    text: str
    entities: list[str] = Field(default_factory=list)


class PlanEvent(_Envelope):
    intent: Intent
    hops: int
    sub_queries: list[SubQuery]


class ChunkHit(BaseModel):
    id: str
    doc_id: int
    score: float
    vec_rank: int | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    heading_path: str = ""
    preview: str = ""


class RetrievalEvent(_Envelope):
    query_id: str
    engine: Literal["vector", "bm25", "hybrid"]
    rewrite_round: int = 0
    chunks: list[ChunkHit]


class GradeEvent(_Envelope):
    coverage: float
    threshold: float
    decision: GradeDecision
    rewrite_n: int
    low_score_chunk_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["概念", "组件", "算法", "参数", "问题"]
    subject: str
    domain: Domain
    weight: int = 1


class GraphEdge(BaseModel):
    source: str
    target: str
    rel: Literal["依赖", "属于", "对比", "导致", "解决", "使用"]
    weight: float = 1.0
    cross_domain: bool = False


class GraphEvent(_Envelope):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    active_path: list[str] = Field(default_factory=list)
    replace: bool = False


class TokenEvent(_Envelope):
    text: str


class SourceRef(BaseModel):
    doc_id: int
    doc_name: str
    heading_path: str


class CitationEvent(_Envelope):
    claim_id: int
    marker: str
    chunk_ids: list[str]
    quote: str
    source: SourceRef


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0


class DoneEvent(_Envelope):
    message_id: int | None = None
    stop_reason: StopReason = "normal"
    coverage: float = 0.0
    rewrite_count: int = 0
    latency_ms: int = 0
    usage: Usage = Field(default_factory=Usage)
    insufficient_evidence: bool = False


class ErrorEvent(_Envelope):
    code: Literal["LLM_TIMEOUT", "LLM_RATE_LIMIT", "RETRIEVAL_EMPTY", "INTERNAL"]
    message: str
    retryable: bool = True


# ---------------------------------------------------------------- 生产者

PING = ": ping\n\n"


def format_sse(event: str, payload: BaseModel) -> str:
    """序列化成 SSE 帧。ensure_ascii=False 保证中文可读（调试时很重要）。"""
    data = json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def now_ms() -> int:
    return int(time.time() * 1000)


class EventStream:
    """管理 seq 与 trace_id，对外只暴露「造事件」的方法。

    用法：
        es = EventStream("t_8f2a1c")
        yield es.step("router", "running", "判断问题意图")
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._seq = 0
        # 落库用的 step 记录。
        # 为什么不放在编排层手工收集：step 在 graph.py 里出现了二十多次，
        # 逐个手抄一定会漏，而漏掉的 trace 回放起来就是断的。
        # 在造事件的地方顺手记一份，是唯一不会漏的做法。
        self.steps: list[dict] = []

    def _env(self) -> dict[str, Any]:
        self._seq += 1
        return {"seq": self._seq, "trace_id": self.trace_id, "ts": now_ms()}

    @property
    def seq(self) -> int:
        return self._seq

    def step(self, node: Node, status: StepStatus, label: str, detail: str | None = None) -> str:
        env = self._env()
        self.steps.append(
            {
                "seq": env["seq"],
                "ts": env["ts"],
                "node": node,
                "status": status,
                "label": label,
                "detail": detail,
            }
        )
        return format_sse(
            "step", StepEvent(node=node, status=status, label=label, detail=detail, **env)
        )

    def plan(self, intent: Intent, hops: int, sub_queries: list[SubQuery]) -> str:
        return format_sse("plan", PlanEvent(intent=intent, hops=hops, sub_queries=sub_queries, **self._env()))

    def retrieval(self, query_id: str, engine: str, chunks: list[ChunkHit], rewrite_round: int = 0) -> str:
        return format_sse(
            "retrieval",
            RetrievalEvent(
                query_id=query_id,
                engine=engine,
                rewrite_round=rewrite_round,
                chunks=chunks,
                **self._env(),
            ),
        )

    def grade(
        self,
        coverage: float,
        threshold: float,
        decision: GradeDecision,
        rewrite_n: int,
        low_score_chunk_ids: list[str] | None = None,
        reason: str = "",
    ) -> str:
        return format_sse(
            "grade",
            GradeEvent(
                coverage=coverage,
                threshold=threshold,
                decision=decision,
                rewrite_n=rewrite_n,
                low_score_chunk_ids=low_score_chunk_ids or [],
                reason=reason,
                **self._env(),
            ),
        )

    def graph(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        active_path: list[str] | None = None,
        replace: bool = False,
    ) -> str:
        return format_sse(
            "graph",
            GraphEvent(nodes=nodes, edges=edges, active_path=active_path or [], replace=replace, **self._env()),
        )

    def token(self, text: str) -> str:
        return format_sse("token", TokenEvent(text=text, **self._env()))

    def citation(
        self,
        claim_id: int,
        marker: str,
        chunk_ids: list[str],
        quote: str,
        source: SourceRef,
    ) -> str:
        return format_sse(
            "citation",
            CitationEvent(
                claim_id=claim_id,
                marker=marker,
                chunk_ids=chunk_ids,
                quote=quote,
                source=source,
                **self._env(),
            ),
        )

    def done(
        self,
        stop_reason: StopReason = "normal",
        coverage: float = 0.0,
        rewrite_count: int = 0,
        latency_ms: int = 0,
        usage: Usage | None = None,
        insufficient_evidence: bool = False,
        message_id: int | None = None,
    ) -> str:
        return format_sse(
            "done",
            DoneEvent(
                message_id=message_id,
                stop_reason=stop_reason,
                coverage=coverage,
                rewrite_count=rewrite_count,
                latency_ms=latency_ms,
                usage=usage or Usage(),
                insufficient_evidence=insufficient_evidence,
                **self._env(),
            ),
        )

    def error(self, code: str, message: str, retryable: bool = True) -> str:
        return format_sse("error", ErrorEvent(code=code, message=message, retryable=retryable, **self._env()))
