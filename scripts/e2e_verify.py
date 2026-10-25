"""端到端验证：Java 网关 → Python Agent → 数据库，跑一遍真实问答。

为什么单独写一个脚本：
    手工 curl 验证有两个问题——一是要记着带 X-Internal-Token，
    二是 SSE 流在终端里是一堆原始帧，看不出事件顺序对不对。
    这个脚本把整条链路的响应解析成时间轴，并断言契约里的关键约束。

用法：
    python scripts/e2e_verify.py --health          # 只查健康状态
    python scripts/e2e_verify.py                   # 全链路问答（默认走 Java 8080）
    python scripts/e2e_verify.py --direct          # 绕过 Java，直连 Python 8000
    python scripts/e2e_verify.py --question "..."  # 换问题
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
TOKEN = ENV.get("INTERNAL_TOKEN", "dev_internal_token")

PY_BASE = "http://127.0.0.1:8000"
JAVA_BASE = "http://127.0.0.1:8080"


# 环境里可能挂着失效的 HTTP_PROXY（这台机器上就有一个），
# urllib 默认会读它，导致连 localhost 也被代理拦走、返回莫名其妙的 502。
# 访问本机服务必须显式绕开。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str, headers: dict | None = None, timeout: int = 10) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def check_health() -> bool:
    ok = True

    print("=" * 70)
    print("1. Python Agent  /internal/health")
    status, body = get(f"{PY_BASE}/internal/health", {"X-Internal-Token": TOKEN})
    if status == 200:
        d = json.loads(body)
        print(f"   ✓ HTTP {status}  db={d.get('db')}  llm={d.get('llm')}  "
              f"mode={d.get('mode')}  model={d.get('model')}")
        if d.get("mode") != "live":
            print("   ⚠ mode 不是 live —— .env 里 MOCK_AGENT 还是 true")
            ok = False
        if d.get("llm") != "ok":
            print("   ⚠ LLM key 未配置")
            ok = False
    else:
        print(f"   ✗ HTTP {status}  {body[:200]}")
        print("   → 检查 Python 服务是否在 8000 端口启动")
        ok = False

    print("\n2. Java 网关  /api/health")
    status, body = get(f"{JAVA_BASE}/api/health")
    if status == 200:
        print(f"   ✓ HTTP {status}  {body[:160]}")
    else:
        print(f"   ✗ HTTP {status}  {body[:200]}")
        print("   → 检查 Java 网关是否在 8080 端口启动")
        ok = False

    return ok


def stream_events(url: str, payload: dict, headers: dict, timeout: int = 180):
    """发 POST 并逐个 yield (event, data)。

    必须做成生成器：如果先把整个流读完再返回，所有事件的时间戳都会一样，
    就看不出"卡在哪个节点"了——而排查慢的问题恰恰最需要这个信息。
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"})

    buf = ""
    # 必须用增量解码器：按字节读的时候，一个中文字符很可能被切在两个 chunk 之间，
    # 对每个 chunk 单独 decode 会把半个字符变成 U+FFFD（显示为 �）。
    # 前端用的是 TextDecoder({stream:true})，原理相同。
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    with _OPENER.open(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        while True:
            chunk = r.read(256)
            if not chunk:
                buf += decoder.decode(b"", final=True)
                break
            buf += decoder.decode(chunk)
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                event, payloads = "", []
                for line in raw.split("\n"):
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
                        payloads.append(value)
                if event and payloads:
                    try:
                        yield event, json.loads("\n".join(payloads))
                    except json.JSONDecodeError:
                        pass


def summarize(events, *, require_cross_domain: bool = False) -> tuple[bool, str, list[str]]:
    """边收边打印时间轴，同时收集契约断言所需的信息。"""
    # 用事件自带的服务端时间戳算相对时间，而不是客户端到达时间。
    # 原因：SSE 在 TCP/网关层会被缓冲，多个事件可能同时到达客户端，
    # 用到达时间会让"耗时 5 秒的节点"看起来是 0 秒，完全误导排查。
    t0: float | None = None
    collected: list[tuple[str, dict]] = []
    answer: list[str] = []

    for event, d in events:
        collected.append((event, d))
        ts = d.get("ts")
        if t0 is None and isinstance(ts, (int, float)):
            t0 = ts
        if event == "token":
            answer.append(d.get("text", ""))
            continue

        label = ""
        if event == "step":
            label = f"{d.get('node'):<10} {d.get('status'):<9} {d.get('label', '')}"
            if d.get("detail"):
                label += f"  ↳ {d['detail'][:50]}"
        elif event == "plan":
            subs = " / ".join(s.get("text", "")[:16] for s in d.get("sub_queries", []))
            label = f"intent={d.get('intent')} hops={d.get('hops')}  [{subs}]"
        elif event == "retrieval":
            label = f"{d.get('query_id')} round={d.get('rewrite_round', 0)}  {len(d.get('chunks', []))} 条"
        elif event == "grade":
            label = f"coverage={d.get('coverage', 0):.2f} → {d.get('decision')}"
        elif event == "graph":
            cross = sum(1 for e in d.get("edges", []) if e.get("cross_domain"))
            label = f"{len(d.get('nodes', []))} 节点 / {len(d.get('edges', []))} 边（跨域 {cross}）"
        elif event == "citation":
            label = f"[{d.get('claim_id')}] → {d.get('chunk_ids')} 《{d.get('source', {}).get('doc_name')}》"
        elif event == "done":
            u = d.get("usage", {})
            label = (f"stop={d.get('stop_reason')} coverage={d.get('coverage', 0):.2f} "
                     f"{d.get('latency_ms', 0)}ms tokens={u.get('input_tokens', 0)}+{u.get('output_tokens', 0)}")
        elif event == "error":
            label = f"{d.get('code')}: {d.get('message')}"
        elapsed = (d.get("ts", t0) - t0) / 1000 if isinstance(d.get("ts"), (int, float)) else 0.0
        print(f"  {elapsed:6.1f}s  {event:<10} {label}", flush=True)

    events = collected
    names = [e for e, _ in events]
    problems: list[str] = []

    # ---- 契约断言 ----
    if not names:
        problems.append("没有收到任何事件")
    else:
        if names[-1] != "done":
            problems.append(f"最后一个事件是 {names[-1]}，契约要求必须是 done")
        if names.count("done") != 1:
            problems.append(f"done 出现了 {names.count('done')} 次，应该恰好 1 次")
        if "plan" in names and "retrieval" in names and names.index("plan") > names.index("retrieval"):
            problems.append("plan 出现在 retrieval 之后")
        seqs = [d.get("seq") for _, d in events]
        if seqs != sorted(seqs):
            problems.append("seq 不是单调递增")

        # citation 必须先于含 [n] 的 token
        first_cite = names.index("citation") if "citation" in names else -1
        if first_cite != -1:
            for i, (e, d) in enumerate(events[:first_cite]):
                if e == "token" and "[" in d.get("text", ""):
                    problems.append("token 里出现了引用标记，但 citation 事件还没到")
                    break

        cross = 0
        for e, d in events:
            if e == "graph":
                cross += sum(1 for x in d.get("edges", []) if x.get("cross_domain"))
        # 跨域边不是每个问题都该有：问 Kubernetes 这种库里没有的主题，
        # 实体全落在同一个域甚至全是 unknown，没有跨域边才是正确行为。
        # 所以默认只提示，演示主线题才用 --strict-cross-domain 强制要求。
        if cross == 0:
            if require_cross_domain:
                problems.append("图谱里没有跨域边（这是产品核心卖点，演示前必须确认）")
            else:
                print("   ⚠ 本次没有跨域边（如果这是演示主线题，请加 --strict-cross-domain 复查）")

    return (not problems), "".join(answer), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--direct", action="store_true", help="绕过 Java，直连 Python")
    ap.add_argument("--question", default="向量检索为什么不能用 B+ 树加速？那 RAG 的召回率该怎么提？")
    ap.add_argument(
        "--strict-cross-domain",
        action="store_true",
        help="强制要求图谱里有跨域边。演示主线题用这个，其他题不需要",
    )
    args = ap.parse_args()

    print(f"internal_token: {'已从 .env 读取' if TOKEN != 'dev_internal_token' else '使用默认值'}\n")

    if args.health:
        return 0 if check_health() else 1

    if not check_health():
        print("\n✗ 健康检查未通过，中止")
        return 1

    print("\n" + "=" * 70)
    if args.direct:
        print("3. 直连 Python Agent  /internal/agent/stream")
        url = f"{PY_BASE}/internal/agent/stream"
        headers = {"X-Internal-Token": TOKEN}
    else:
        print("3. Java 网关  /api/chat/stream")
        url = f"{JAVA_BASE}/api/chat/stream"
        headers = {}

    print(f"   问题：{args.question}\n")

    payload = {
        "trace_id": f"t_e2e_{int(time.time())}",
        "question": args.question,
        "session_id": None,
        "history": [],
    }

    try:
        ok, answer, problems = summarize(
            stream_events(url, payload, headers),
            require_cross_domain=args.strict_cross_domain,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 请求失败：{type(e).__name__}: {e}")
        return 1

    print("\n" + "=" * 70)
    if problems:
        print("✗ 契约检查未通过：")
        for p in problems:
            print(f"   - {p}")
    else:
        print("✓ 契约检查全部通过")

    if answer:
        print("\n答案（前 600 字）：\n" + answer[:600])

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
