"""Agent 轨迹落库。

为什么值得写：
    1. `/api/traces/{traceId}` 是契约里定义的接口，没有落库它就是死接口。
    2. 演示时被问"你这步为什么这么慢"，翻 trace 比翻日志快得多——
       日志是文本流，trace 有结构化的 node / status / duration_ms。
    3. 降级率是可量化的质量指标：跑了 100 次，其中多少次 grader 降级了？
       没有落库就永远只能靠印象。

表所有权（CLAUDE.md 不变量 2）：agent_trace / agent_step 归 Python 写。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.infra.db import SessionLocal

logger = logging.getLogger(__name__)


def _fill_durations(steps: list[dict], total_ms: int) -> list[dict]:
    """用相邻 step 的时间戳算每步耗时。

    为什么不在每个节点内部自己计时：
        那样要改 8 个节点的签名，而且节点不知道自己"结束"的确切时刻——
        它的结束就是下一个事件产生的时刻。用相邻时间戳做差是同一件事的另一种表述，
        但只需要在事件层记录一次。

    最后一步的结束时间用整条链路的总耗时兜底。
    """
    out: list[dict] = []
    for i, s in enumerate(steps):
        ts = s.get("ts") or 0
        nxt = steps[i + 1].get("ts") if i + 1 < len(steps) else None
        duration = int(nxt - ts) if nxt else max(0, total_ms - int(ts - (steps[0].get("ts") or ts)))
        out.append({**s, "duration_ms": max(0, duration)})
    return out


def save(
    *,
    trace_id: str,
    session_id: int | None,
    question: str,
    answer: str,
    intent: str | None,
    rewrite_count: int,
    coverage: float,
    stop_reason: str,
    latency_ms: int,
    usage: Any = None,
    steps: list[dict] | None = None,
) -> None:
    """写一条 trace 和它的所有 step。

    整体吞异常：轨迹是"事后可查"的附加价值，不能因为它写失败就让用户拿不到答案。
    这是刻意的取舍——和「检索失败要如实报错」不同，那时候用户没有答案；
    这时候答案已经在路上了。
    """
    steps = steps or []
    filled = _fill_durations(steps, latency_ms)

    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    """
                    INSERT INTO agent_trace (
                        trace_id, session_id, question, answer, intent,
                        rewrite_count, step_count, coverage, latency_ms,
                        token_input, token_output, stop_reason
                    ) VALUES (
                        :trace_id, :session_id, :question, :answer, :intent,
                        :rewrite_count, :step_count, :coverage, :latency_ms,
                        :token_input, :token_output, :stop_reason
                    )
                    ON CONFLICT (trace_id) DO UPDATE SET
                        answer = EXCLUDED.answer,
                        coverage = EXCLUDED.coverage,
                        latency_ms = EXCLUDED.latency_ms,
                        token_input = EXCLUDED.token_input,
                        token_output = EXCLUDED.token_output,
                        stop_reason = EXCLUDED.stop_reason
                    """
                ),
                {
                    "trace_id": trace_id[:40],
                    "session_id": session_id,
                    "question": question,
                    "answer": answer,
                    "intent": intent,
                    "rewrite_count": rewrite_count,
                    "step_count": len(filled),
                    "coverage": round(float(coverage), 3),
                    "latency_ms": latency_ms,
                    "token_input": getattr(usage, "input_tokens", 0) or 0,
                    "token_output": getattr(usage, "output_tokens", 0) or 0,
                    "stop_reason": stop_reason,
                },
            )

            # 重放同一条 trace 时先清掉旧 step，避免 seq 重复堆叠
            db.execute(
                text("DELETE FROM agent_step WHERE trace_id = :tid"),
                {"tid": trace_id[:40]},
            )
            for s in filled:
                db.execute(
                    text(
                        """
                        INSERT INTO agent_step (trace_id, seq, node, status, payload, duration_ms)
                        VALUES (:trace_id, :seq, :node, :status, CAST(:payload AS jsonb), :duration_ms)
                        """
                    ),
                    {
                        "trace_id": trace_id[:40],
                        "seq": s["seq"],
                        "node": s["node"],
                        "status": s["status"],
                        "payload": _payload_json(s),
                        "duration_ms": s["duration_ms"],
                    },
                )
            db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("trace 落库失败（不影响回答）：%s", e)


def _payload_json(step: dict) -> str:
    """把 step 的展示信息塞进 payload。

    payload 是 JSONB，契约里前端展开节点时直接读它。
    这里只放 label 和 detail——它们是给人看的，也足够回答"这一步做了什么"。
    """
    import json

    return json.dumps(
        {"label": step.get("label", ""), "detail": step.get("detail")},
        ensure_ascii=False,
    )
