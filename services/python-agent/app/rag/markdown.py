"""Markdown 块级解析。

为什么不用 python-markdown / mistune：
    这两个库都会把文档摊平成 HTML，我们还得再从 HTML 里把结构抠回来。
    而且它们不在 contracts/deps.md 的白名单里。

    真正需要的只有一件事：**识别出哪些行不能被切开**（代码块、表格），
    以及标题层级。这个用 60 行状态机就够了，比引入一个通用解析器更可控。

输出是一串 Block，供 chunker 按 token 预算重新组装。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["heading", "code", "table", "list", "quote", "para"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]{3,}\|?\s*$")


@dataclass
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # 仅 heading 用


def parse_markdown(text: str) -> list[Block]:
    """把 Markdown 拆成块序列。

    三条硬规则：
    1. 代码块一旦开始，直到闭合围栏为止整段是**一个** block —— 代码被切开就没法读了
    2. 表格整段是一个 block，同理
    3. 标题单独成块，用来切分语义段落
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    blocks: list[Block] = []
    buf: list[str] = []
    i = 0
    n = len(lines)

    def flush_para() -> None:
        if not buf:
            return
        body = "\n".join(buf).strip()
        if body:
            blocks.append(Block("para", body))
        buf.clear()

    while i < n:
        line = lines[i]

        # ---- 代码块 ----
        m = _FENCE.match(line)
        if m:
            flush_para()
            fence = m.group(1)
            code_lines = [line]
            i += 1
            while i < n:
                code_lines.append(lines[i])
                if lines[i].strip().startswith(fence):
                    i += 1
                    break
                i += 1
            blocks.append(Block("code", "\n".join(code_lines)))
            continue

        # ---- 空行：段落结束 ----
        if not line.strip():
            flush_para()
            i += 1
            continue

        # ---- 标题 ----
        m = _HEADING.match(line)
        if m:
            flush_para()
            blocks.append(Block("heading", m.group(2).strip(), level=len(m.group(1))))
            i += 1
            continue

        # ---- 表格：从含 | 的行开始，连续吃 ----
        if "|" in line and (i + 1 < n and _TABLE_SEP.match(lines[i + 1])):
            flush_para()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            blocks.append(Block("table", "\n".join(table_lines)))
            continue

        # ---- 列表：连续列表项合成一个 block，保持条目完整 ----
        if _LIST.match(line):
            flush_para()
            list_lines = [line]
            i += 1
            while i < n and (_LIST.match(lines[i]) or (lines[i].startswith("  ") and lines[i].strip())):
                list_lines.append(lines[i])
                i += 1
            blocks.append(Block("list", "\n".join(list_lines)))
            continue

        # ---- 引用 ----
        if _QUOTE.match(line):
            flush_para()
            quote_lines = [line]
            i += 1
            while i < n and _QUOTE.match(lines[i]):
                quote_lines.append(lines[i])
                i += 1
            blocks.append(Block("quote", "\n".join(quote_lines)))
            continue

        buf.append(line)
        i += 1

    flush_para()
    return blocks
