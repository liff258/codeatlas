#!/usr/bin/env python
"""P0 端到端验收：浏览器 → Java 网关 → Python Agent → Postgres。

检查三件事：
1. 网关能同时探通数据库与 Agent
2. SSE 流经过 Java 转发后，事件顺序与协议一致，且 message_id 被正确注入
3. 助手消息真的落库了，trace_id 对得上

运行（需先起 docker compose、python-agent、java-gateway）：
    python scripts/e2e_check.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://codeatlas:codeatlas_dev@localhost:5433/codeatlas",
)

QUESTION = "向量检索为什么不能用 B+ 树加速？那 RAG 的召回率该怎么提？"

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes = 0

    def ok(self, label: str, detail: str = "") -> None:
        self.passes += 1
        print(f"  {GREEN}✓{RESET} {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def fail(self, label: str, detail: str = "") -> None:
        self.failures.append(f"{label}: {detail}")
        print(f"  {RED}✗{RESET} {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def check(self, cond: bool, label: str, detail: str = "") -> bool:
        (self.ok if cond else self.fail)(label, detail)
        return cond


def parse_sse(lines) -> list[tuple[str, dict]]:
    """解析 SSE 帧。

    ⚠️ 必须容忍 `event:step` 和 `event: step` 两种写法：
    Java 的 SseEmitter 输出前者，Python 手写的输出后者，两者都符合 SSE 规范
    （规范只要求「冒号后若有一个空格则去掉」，不要求必须有空格）。
    任何只认一种格式的客户端，都会在换一层实现时静默收不到事件。
    """
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for line in lines:
        if not line or line.startswith(":"):  # 空行 / 心跳注释
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            events.append((name or "?", json.loads(value)))
            name = None
    return events


def main() -> int:
    c = Checker()

    print("\n[1/3] 健康检查")
    try:
        r = httpx.get(f"{GATEWAY}/api/health", timeout=10)
        body = r.json()
        data = body.get("data", {})
        c.check(body.get("code") == 0, "网关返回 code=0")
        c.check(data.get("gateway") == "up", "gateway 状态", str(data.get("gateway")))
        c.check(data.get("db") == "ok", "数据库连通", str(data.get("db")))
        c.check(data.get("agent") == "ok", "Agent 服务连通", str(data.get("agent")))
        print(f"  {DIM}agent_mode={data.get('agent_mode')}{RESET}")
    except Exception as exc:  # noqa: BLE001
        c.fail("健康检查请求失败", repr(exc))
        print(f"\n{RED}网关未启动或不可达：{GATEWAY}{RESET}")
        return 1

    print("\n[2/3] SSE 流（经 Java 转发）")
    events: list[tuple[str, dict]] = []
    t0 = time.time()
    try:
        with httpx.stream(
            "POST",
            f"{GATEWAY}/api/chat/stream",
            json={"question": QUESTION},
            timeout=120,
        ) as resp:
            c.check(resp.status_code == 200, "HTTP 200", str(resp.status_code))
            c.check(
                resp.headers.get("content-type", "").startswith("text/event-stream"),
                "Content-Type 为 text/event-stream",
                resp.headers.get("content-type", ""),
            )
            events = parse_sse(resp.iter_lines())
    except Exception as exc:  # noqa: BLE001
        c.fail("流式请求失败", repr(exc))
        return 1
    elapsed = time.time() - t0

    if not events:
        c.fail("没有收到任何事件")
        return 1

    kinds = [n for n, _ in events]
    required = {"step", "plan", "retrieval", "grade", "graph", "token", "citation", "done"}
    c.check(required.issubset(set(kinds)), "8 种事件齐全", f"缺失 {required - set(kinds)}")
    c.check(kinds[-1] == "done", "done 是最后一个事件", kinds[-1])
    c.check(kinds.count("done") == 1, "done 只出现一次", str(kinds.count("done")))

    seqs = [p["seq"] for _, p in events]
    c.check(seqs == list(range(1, len(seqs) + 1)), "seq 从 1 严格递增", f"共 {len(seqs)} 个")
    c.check(
        len({p["trace_id"] for _, p in events}) == 1,
        "trace_id 全程一致",
        events[0][1]["trace_id"],
    )
    c.check(elapsed > 0.5, "确实是流式（总耗时 > 0.5s）", f"{elapsed:.2f}s")

    done = events[-1][1]
    trace_id = done["trace_id"]
    c.check(done.get("stop_reason") == "normal", "stop_reason=normal", str(done.get("stop_reason")))
    c.check("message_id" in done, "done 注入了 message_id", str(done.get("message_id")))
    c.check(done.get("rewrite_count", 0) >= 1, "自评-改写闭环发生过", str(done.get("rewrite_count")))

    graph = next(p for n, p in events if n == "graph")
    cross = [e for e in graph["edges"] if e.get("cross_domain")]
    c.check(len(cross) >= 1, "图谱含跨域边", f"{len(cross)} 条")

    print(f"  {DIM}事件数 {len(events)} | token {kinds.count('token')} | 耗时 {elapsed:.2f}s{RESET}")

    print("\n[3/3] 落库校验")
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, role, length(content) AS len, trace_id "
                    "FROM message WHERE trace_id = :t AND role = 'assistant'"
                ),
                {"t": trace_id},
            ).fetchone()
            c.check(row is not None, "助手消息已落库", trace_id)
            if row:
                c.check(row.len > 100, "消息内容完整", f"{row.len} 字")
                c.check(row.id == done.get("message_id"), "message_id 与库中一致", str(row.id))

            user_row = conn.execute(
                text("SELECT count(*) FROM message WHERE session_id = "
                     "(SELECT session_id FROM message WHERE id = :id) AND role = 'user'"),
                {"id": row.id if row else 0},
            ).scalar()
            c.check(user_row and user_row >= 1, "用户提问也已落库")
    except Exception as exc:  # noqa: BLE001
        c.fail("数据库校验失败", repr(exc))

    print("\n" + "=" * 60)
    if c.failures:
        print(f"{RED}失败 {len(c.failures)} 项 / 通过 {c.passes} 项{RESET}")
        for f in c.failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}P0 端到端验收全部通过（{c.passes} 项）{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
