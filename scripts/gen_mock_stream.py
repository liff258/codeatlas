"""把 Python 的 mock_runner 导成前端回放用的 stream.jsonl。

为什么要有这个脚本：
    前端 VITE_MOCK=1 模式要回放一份「和真实链路一模一样」的流。
    如果手工编一份假 JSON，改契约的时候一定忘了同步，
    结果就是 mock 模式下调好的布局，切到真实后端全部错位。

    所以这里直接跑 mock_runner，把 SSE 帧逐条解析成 {event, data} 写盘。
    mock_runner 改了，重跑一次本脚本，前端自动跟上。

用法：
    cd services/python-agent
    python ../../scripts/gen_mock_stream.py

产物：
    web/src/mock/stream.jsonl   一行一个 {"event": "...", "data": {...}}
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 允许从仓库根目录或 services/python-agent 目录运行
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGENT_DIR = ROOT / "services" / "python-agent"
sys.path.insert(0, str(AGENT_DIR))

from app.agent.mock_runner import DEMO_QUESTION, mock_stream  # noqa: E402

OUT = ROOT / "web" / "src" / "mock" / "stream.jsonl"


def parse_frames(raw: str) -> list[dict]:
    """把一段 SSE 文本解析成 [{event, data}]。

    这里刻意用和前端 sse.ts 完全相同的容错策略：
    冒号后有无空格都认。这样一旦哪天两边行为不一致，本脚本的产物会立刻暴露问题。
    """
    records: list[dict] = []
    event = ""
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event, data_lines
        if event and data_lines:
            try:
                records.append({"event": event, "data": json.loads("\n".join(data_lines))})
            except json.JSONDecodeError as e:  # pragma: no cover
                raise SystemExit(f"[gen_mock_stream] 无法解析 {event} 的 data：{e}") from e
        event = ""
        data_lines = []

    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line == "":
            flush()
            continue
        if line.startswith(":"):
            continue
        idx = line.find(":")
        field = line if idx == -1 else line[:idx]
        value = "" if idx == -1 else line[idx + 1 :]
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)

    flush()
    return records


async def main() -> None:
    chunks: list[str] = []
    # 零延迟：导数据不需要真的等 22ms 一个 token
    async for frame in mock_stream(DEMO_QUESTION, trace_id="t_mock01", token_delay_ms=0, step_delay_ms=0):
        chunks.append(frame)

    records = parse_frames("".join(chunks))
    if not records:
        raise SystemExit("[gen_mock_stream] 解析出 0 条事件，检查 mock_runner 是否正常")

    # 契约 §5 的顺序保证，在这里顺手验一遍
    types = [r["event"] for r in records]
    assert types[0] == "step", f"首个事件必须是 step，实际是 {types[0]}"
    assert types[-1] == "done", f"末尾必须是 done，实际是 {types[-1]}"
    assert "plan" in types and "token" in types and "graph" in types, "缺少关键事件类型"

    seqs = [r["data"]["seq"] for r in records]
    assert seqs == list(range(1, len(seqs) + 1)), "seq 必须从 1 连续递增"

    trace_ids = {r["data"]["trace_id"] for r in records}
    assert trace_ids == {"t_mock01"}, f"trace_id 被中途改写：{trace_ids}"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    from collections import Counter

    stat = Counter(types)
    print(f"✅ 写入 {OUT}")
    print(f"   {len(records)} 条事件 / {len(types)} 帧")
    print("   " + "  ".join(f"{k}×{v}" for k, v in stat.items()))


if __name__ == "__main__":
    asyncio.run(main())
