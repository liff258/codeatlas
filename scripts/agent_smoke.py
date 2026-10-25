"""Agent 冒烟脚本：不开前端、不开 Java，直接跑 Python 侧的 Agent。

为什么需要它：
    调 Agent 时如果只能通过浏览器看效果，改一行 prompt 要等前端刷新、
    还要猜是哪一步出的问题。这个脚本把 SSE 事件流解析成时间轴，
    一眼能看出"卡在哪个节点、每个节点花了多久、降级了没有"。

用法：
    python scripts/agent_smoke.py --ping
        只发一次最小请求，验证 key 和模型名对不对（最省 token 的检查）

    python scripts/agent_smoke.py --node router --question "HashMap 扩容机制"
        只跑一个节点，打印它解析出来的 JSON

    python scripts/agent_smoke.py --question "向量检索为什么不能用 B+ 树加速"
        跑完整链路，打印事件时间轴

    python scripts/agent_smoke.py --question "..." --verbose
        额外打印每个事件的完整 data
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))


def _load_env() -> None:
    """让脚本能独立跑：手动把仓库根的 .env 灌进环境变量。

    服务启动时由 pydantic-settings 读 .env，但脚本直接跑 Python 时
    不一定在正确的 cwd，所以这里显式加载一次。
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    import os

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _parse_sse(frame: str) -> tuple[str, dict] | None:
    """解析一个 SSE 帧 → (event, data)。"""
    event = ""
    data_lines = []
    for line in frame.split("\n"):
        if line.startswith(":"):
            continue
        idx = line.find(":")
        if idx == -1:
            continue
        field, value = line[:idx], line[idx + 1 :]
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
    if not event or not data_lines:
        return None
    try:
        return event, json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None


def _summarize(event: str, d: dict) -> str:
    """每个事件挑最有信息量的字段，避免刷屏。"""
    if event == "step":
        detail = f"  ↳ {d['detail']}" if d.get("detail") else ""
        return f"{d['node']:<10} {d['status']:<9} {d['label']}{detail}"
    if event == "plan":
        subs = " / ".join(s["text"][:20] for s in d.get("sub_queries", []))
        return f"intent={d['intent']} hops={d['hops']}  [{subs}]"
    if event == "retrieval":
        return f"{d['query_id']} round={d.get('rewrite_round', 0)}  {len(d['chunks'])} 条"
    if event == "grade":
        return (
            f"coverage={d['coverage']:.2f} (阈值 {d['threshold']}) "
            f"→ {d['decision']}  {d.get('reason', '')[:40]}"
        )
    if event == "graph":
        cross = sum(1 for e in d.get("edges", []) if e.get("cross_domain"))
        return f"{len(d['nodes'])} 节点 / {len(d['edges'])} 边（跨域 {cross} 条）path={d.get('active_path')}"
    if event == "citation":
        return f"[{d['claim_id']}] → {d['chunk_ids']}  《{d['source']['doc_name']}》"
    if event == "token":
        return f"{len(d['text'])} 字"
    if event == "done":
        u = d.get("usage", {})
        return (
            f"stop={d['stop_reason']} coverage={d.get('coverage', 0):.2f} "
            f"rewrite={d.get('rewrite_count', 0)} {d.get('latency_ms', 0)}ms "
            f"tokens={u.get('input_tokens', 0)}+{u.get('output_tokens', 0)}"
        )
    if event == "error":
        return f"{d['code']}: {d['message']}"
    return ""


async def ping() -> int:
    from app.agent.llm import LLMClient, LLMError
    from app.config import settings

    print(f"base_url : {settings.llm_base_url}")
    print(f"model    : {settings.agent_model}")
    print(f"api_key  : {'已配置（' + str(len(settings.llm_api_key)) + ' 字符）' if settings.llm_api_key else '❌ 未配置'}")

    if not settings.llm_api_key:
        print("\n请先在 .env 里设置 LLM_API_KEY（智谱 bigmodel.cn 的 key）")
        return 1

    t0 = time.time()
    try:
        client = LLMClient()
        result = await client.json_call("只输出 JSON", '输出 {"ok": true}', max_tokens=100)
        print(f"\n✓ 调用成功，耗时 {(time.time()-t0)*1000:.0f}ms")
        print(f"  返回：{result.text[:80]}")
        print(f"  解析：{result.data}  降级={result.degraded}")
        print(f"  用量：{client.usage.model_dump()}")
        await client.close()
        return 0 if not result.degraded else 2
    except LLMError as e:
        print(f"\n✗ {e.code}: {e}")
        if e.code == "INTERNAL" and "模型调用失败" in str(e):
            print("  常见原因：模型名写错（应为 glm-4.5-flash）、key 无效、或账户未实名")
        return 1


async def run_node(node: str, question: str) -> int:
    from app.agent import nodes
    from app.agent.llm import LLMClient

    client = LLMClient()
    try:
        if node == "router":
            r = await nodes.route(client, question, [])
            print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
        elif node == "planner":
            r = await nodes.plan(client, question, "concept")
            print(json.dumps(r.__dict__, ensure_ascii=False, indent=2, default=str))
        elif node == "grader":
            print("grader 需要证据，请用全链路模式")
            return 1
        elif node == "retriever":
            from app.agent.events import SubQuery
            from app.rag.retrieve import build_retriever

            retriever = build_retriever()
            ev = nodes.retrieve(
                retriever, [SubQuery(id="q1", text=question, entities=[])], query_for_rerank=question
            )
            for i, e in enumerate(ev, 1):
                print(f"  [{i}] {e.score:.3f} {e.domain:8} {e.heading_path[:50]}")
                print(f"       {e.content[:80]}")
        else:
            print(f"未知节点：{node}（可选 router / planner / retriever）")
            return 1
        return 0
    finally:
        await client.close()


async def run_full(question: str, verbose: bool) -> int:
    from app.agent.graph import agent_stream

    t0 = time.time()
    buf = ""
    counts: dict[str, int] = {}
    answer = []

    print(f"问题：{question}\n" + "=" * 74)

    async for frame in agent_stream(question=question, trace_id="t_smoke"):
        buf += frame
        while "\n\n" in buf:
            raw, buf = buf.split("\n\n", 1)
            parsed = _parse_sse(raw)
            if not parsed:
                continue
            event, data = parsed
            counts[event] = counts.get(event, 0) + 1

            # token 事件太多，只在 verbose 时逐条打印
            if event == "token":
                answer.append(data["text"])
                if verbose:
                    print(f"{time.time()-t0:7.2f}s  token      {data['text']!r}")
                continue

            print(f"{time.time()-t0:7.2f}s  {event:<10} {_summarize(event, data)}")
            if verbose and event not in ("step",):
                print(" " * 11 + json.dumps(data, ensure_ascii=False)[:200])

    print("=" * 74)
    print("统计：" + "  ".join(f"{k}×{v}" for k, v in sorted(counts.items())))
    print(f"总耗时：{(time.time()-t0):.1f}s")
    print("\n答案：\n" + "".join(answer)[:800])
    return 0


def main() -> int:
    _load_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--ping", action="store_true", help="只验证 key 和模型名")
    ap.add_argument("--node", help="只跑一个节点：router / planner / retriever")
    ap.add_argument("--question", default="向量检索为什么不能用 B+ 树加速？那 RAG 的召回率该怎么提？")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.ping:
        return asyncio.run(ping())
    if args.node:
        return asyncio.run(run_node(args.node, args.question))
    return asyncio.run(run_full(args.question, args.verbose))


if __name__ == "__main__":
    raise SystemExit(main())
