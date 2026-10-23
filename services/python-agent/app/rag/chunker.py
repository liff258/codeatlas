"""父子块切片。

为什么要父子块（这是 RAG 里最划算的一个技巧）：
    检索要的是**短**——256 token 的块向量更聚焦，命中率明显高于 1024 token 的块，
    因为长块会把主题稀释掉。
    生成要的是**全**——只给 256 token，模型看不到上下文，答案会断章取义。

    所以：用 child 检索，命中后把它所属的 parent 喂给模型。
    代价是存储翻一倍，收益是召回率和答案质量同时提升。

参数来自 contracts/db-schema.sql 的约定：child 256 / parent 1024 / overlap 64。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.rag.markdown import Block, parse_markdown
from app.rag.text import content_hash, count_tokens, split_sentences

ChunkLevel = Literal["parent", "child"]

CHILD_TOKENS = 256
PARENT_TOKENS = 1024
OVERLAP_TOKENS = 64

# 单个 block 超过这个倍数就直接独占一个 chunk，不再尝试合并。
# 超长代码块（比如一整个类）切开没有任何意义。
_OVERSIZE_FACTOR = 2.5


@dataclass
class Chunk:
    level: ChunkLevel
    content: str
    token_count: int
    heading_path: str
    ordinal: int
    content_hash: str


@dataclass
class ChunkGroup:
    """一个 parent 和它下面的 children。入库时先插 parent 拿 id，再插 children。"""

    parent: Chunk
    children: list[Chunk] = field(default_factory=list)


class _HeadingStack:
    """维护 "第3章 > 3.2 G1 > 3.2.4 SATB" 这样的标题路径。

    不能简单地把标题拼起来：文档里经常出现跳级（## 下面直接 ####），
    也不能假设层级连续。用栈按 level 弹栈才是对的。
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, title: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title))

    @property
    def path(self) -> str:
        return " > ".join(t for _, t in self._stack)


def _split_oversize(text: str, budget: int, overlap: int) -> list[str]:
    """超长段落按句子切，并保留一点重叠。

    重叠的意义：答案正好卡在两个 chunk 交界处时，只切不叠会把一句话劈成两半，
    两边都读不出完整意思。
    """
    sentences = split_sentences(text)
    if not sentences:
        return [text]

    out: list[str] = []
    cur: list[str] = []
    cur_tokens = 0

    for sent in sentences:
        st = count_tokens(sent)
        if cur and cur_tokens + st > budget:
            out.append("".join(cur).strip())
            # 回退：保留末尾若干句作为下一段的开头
            tail: list[str] = []
            tail_tokens = 0
            for s in reversed(cur):
                s_tokens = count_tokens(s)
                if tail_tokens + s_tokens > overlap:
                    break
                tail.insert(0, s)
                tail_tokens += s_tokens
            cur = tail
            cur_tokens = tail_tokens
        cur.append(sent)
        cur_tokens += st

    if cur:
        out.append("".join(cur).strip())

    return [x for x in out if x]


def _split_by_lines(text: str, budget: int) -> list[str]:
    """按行累积切分。用于代码段内部的兜底——一整段代码还是太长时的最后一招。"""
    out: list[str] = []
    buf: list[str] = []
    tokens = 0

    for line in text.split("\n"):
        lt = count_tokens(line)
        if buf and tokens + lt > budget:
            out.append("\n".join(buf))
            buf, tokens = [], 0
        buf.append(line)
        tokens += lt

    if buf:
        out.append("\n".join(buf))

    return [x for x in out if x.strip()]


def _split_code_block(text: str, budget: int) -> list[str]:
    """超长代码块：按空行切成逻辑段，每段重新补回围栏。

    为什么不直接按行切：代码的语义单位是「函数 / 语句块」，空行是作者自己划的边界，
    按行硬切会把一个方法劈成两半，检索到了也读不懂。
    切完每段都带上 ```lang 围栏，保证单独拿出来也是合法可读的代码。
    """
    lines = text.split("\n")
    if not lines:
        return [text]

    head = lines[0].strip()
    fence = head[:3] or "```"
    lang = head[3:].strip()

    body = lines[1:]
    while body and body[-1].strip().startswith(fence):
        body.pop()

    # 先按空行切成逻辑段
    segments: list[str] = []
    cur: list[str] = []
    for line in body:
        if not line.strip() and cur:
            segments.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    if cur:
        segments.append("\n".join(cur))

    # 再把逻辑段按预算合并
    merged: list[str] = []
    buf: list[str] = []
    tokens = 0
    for seg in segments:
        st = count_tokens(seg)
        # 单个逻辑段就超预算：先落盘已有的，再把这一段按行硬切
        if st > budget:
            if buf:
                merged.append("\n".join(buf))
                buf, tokens = [], 0
            merged.extend(_split_by_lines(seg, budget))
            continue
        if buf and tokens + st > budget:
            merged.append("\n".join(buf))
            buf, tokens = [], 0
        buf.append(seg)
        tokens += st
    if buf:
        merged.append("\n".join(buf))

    return [f"{fence}{lang}\n{p}\n{fence}" for p in merged if p.strip()]


def _split_table(text: str, budget: int) -> list[str]:
    """超长表格：按行切，但每段都重复表头。

    表格丢了表头就没法读了——"3 字节 4 字节" 这种数据行单独拿出来毫无意义。
    """
    lines = text.split("\n")
    if len(lines) < 3:
        return [text]

    header = lines[:2]
    rows = lines[2:]
    header_tokens = count_tokens("\n".join(header))

    out: list[str] = []
    buf: list[str] = []
    tokens = header_tokens

    for row in rows:
        rt = count_tokens(row)
        if buf and tokens + rt > budget:
            out.append("\n".join(header + buf))
            buf, tokens = [], header_tokens
        buf.append(row)
        tokens += rt

    if buf:
        out.append("\n".join(header + buf))

    return [x for x in out if x.strip()]


def chunk_markdown(
    text: str,
    *,
    child_tokens: int = CHILD_TOKENS,
    parent_tokens: int = PARENT_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[ChunkGroup]:
    """把一份 Markdown 切成 parent/child 两级块。"""
    blocks = parse_markdown(text)
    if not blocks:
        return []

    groups: list[ChunkGroup] = []
    stack = _HeadingStack()

    # 当前正在累积的 child 缓冲
    buf: list[str] = []
    buf_tokens = 0
    buf_heading = ""
    # 当前 parent 下已完成的 children
    pending_children: list[Chunk] = []
    pending_parent_tokens = 0
    pending_parent_heading = ""
    ordinal = 0

    def flush_parent() -> None:
        nonlocal pending_children, pending_parent_tokens, pending_parent_heading, ordinal
        if not pending_children:
            return
        parent_text = "\n\n".join(c.content for c in pending_children)
        parent = Chunk(
            level="parent",
            content=parent_text,
            token_count=count_tokens(parent_text),
            heading_path=pending_parent_heading or pending_children[0].heading_path,
            ordinal=ordinal,
            content_hash=content_hash(parent_text),
        )
        ordinal += 1
        groups.append(ChunkGroup(parent=parent, children=pending_children))
        pending_children = []
        pending_parent_tokens = 0
        pending_parent_heading = ""

    def flush_child() -> None:
        nonlocal buf, buf_tokens, buf_heading, pending_parent_tokens, pending_parent_heading, ordinal
        if not buf:
            return
        body = "\n\n".join(buf).strip()
        buf = []
        buf_tokens = 0
        if not body:
            return

        child = Chunk(
            level="child",
            content=body,
            token_count=count_tokens(body),
            heading_path=buf_heading,
            ordinal=ordinal,
            content_hash=content_hash(body),
        )
        ordinal += 1

        if not pending_parent_heading:
            pending_parent_heading = buf_heading
        pending_children.append(child)
        pending_parent_tokens += child.token_count

        # parent 攒满就落盘
        if pending_parent_tokens >= parent_tokens:
            flush_parent()

    for block in blocks:
        if block.kind == "heading":
            # 标题切换 = 语义段落切换，当前缓冲必须结束
            flush_child()
            stack.push(block.level, block.text)
            # 标题本身作为下一段的第一行：检索时标题是很强的信号，
            # 只存正文的话，"3.2.4 SATB" 这种关键上下文就丢了
            buf.append(f"{'#' * block.level} {block.text}")
            buf_tokens += count_tokens(block.text) + 2
            buf_heading = stack.path
            continue

        if not buf_heading:
            buf_heading = stack.path or "（无标题）"

        bt = count_tokens(block.text)

        # 超长块（代码 / 表格 / 大段落）单独处理
        if bt > child_tokens * _OVERSIZE_FACTOR:
            flush_child()
            if block.kind == "code":
                pieces = _split_code_block(block.text, child_tokens)
            elif block.kind == "table":
                pieces = _split_table(block.text, child_tokens)
            else:
                pieces = _split_oversize(block.text, child_tokens, overlap)
            for piece in pieces:
                buf = [piece]
                buf_tokens = count_tokens(piece)
                flush_child()
            continue

        # 常规块：能塞就塞，塞不下先落盘
        if buf and buf_tokens + bt > child_tokens:
            flush_child()
        buf.append(block.text)
        buf_tokens += bt

    flush_child()
    flush_parent()

    return groups
