"""素材加载与清洗。

清洗的边界很重要：
    只清「对检索无贡献、但会污染向量」的东西——图片、徽章、HTML 标签、导航链接。
    代码块和表格里的一个字符都不能动，所以清理必须感知围栏状态。

front matter 不是噪声，是元信息：
    JavaGuide 每篇都有 title / description / tag，这是最好的文档级摘要，
    直接丢掉可惜了。title 会作为标题路径的根节点，description 留在 LoadedDoc 里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.rag.text import file_hash, normalize_ws

_FENCE = re.compile(r"^\s*(```|~~~)")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]{1,200}>")
# 徽章：一堆 [![x](y)](z) 组成的行，纯装饰
_BADGE_LINE = re.compile(r"^\s*\[?!\[")
# 纯分隔线
_HR = re.compile(r"^\s*([-*_]\s*){3,}$")
# 目录锚点链接，如 [跳转到 xxx](#xxx)
_ANCHOR_ONLY = re.compile(r"^\s*[-*]\s*\[[^\]]+\]\(#[^)]*\)\s*$")


@dataclass
class LoadedDoc:
    source_id: str
    filename: str
    file_type: str
    text: str
    title: str
    description: str
    size_bytes: int
    content_hash: str


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """分离 YAML front matter，只取标量字段（够用，不引 yaml 依赖到热路径）。"""
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    raw = text[3:end]
    body = text[end + 4 :]

    meta: dict[str, str] = {}
    for line in raw.split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.+)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip("\"'")
        # 只收标量：列表/嵌套字段（tag、head）跳过
        if value and not value.startswith(("[", "{")):
            meta[key] = value

    return meta, body


def clean_markdown(text: str) -> str:
    """清掉对检索无用的噪声，代码块内原样保留。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    in_fence = False

    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        # 图片整行删掉：alt 文本信息量太低，留着反而干扰
        if _IMG.search(line) and not line.strip().startswith("#"):
            stripped = _IMG.sub("", line).strip()
            # 一行只有图片就整行丢；图片夹在文字里就只删图片语法
            if not stripped:
                continue
            line = stripped

        if _BADGE_LINE.match(line) or _HR.match(line) or _ANCHOR_ONLY.match(line):
            continue

        line = _HTML_TAG.sub("", line)

        # 去掉 markdown 链接的外壳，只留文字： [文字](url) → 文字
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)

        out.append(line)

    return normalize_ws("\n".join(out))


def load_file(path: Path, source_id: str) -> LoadedDoc:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    meta, body = _split_front_matter(text)

    if path.suffix.lower() in (".md", ".markdown"):
        cleaned = clean_markdown(body)
        file_type = "md"
    elif path.suffix.lower() == ".txt":
        cleaned = normalize_ws(body)
        file_type = "txt"
    else:
        raise ValueError(f"暂不支持的格式：{path.suffix}（{path}）")

    title = meta.get("title") or path.stem
    description = meta.get("description", "")

    # 标题作为文档第一行，保证第一个 chunk 也带上下文
    if title and not cleaned.lstrip().startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}"

    return LoadedDoc(
        source_id=source_id,
        filename=path.name,
        file_type=file_type,
        text=cleaned,
        title=title,
        description=description,
        size_bytes=len(raw),
        content_hash=file_hash(raw),
    )


def load_dir(root: Path, source_id: str) -> list[LoadedDoc]:
    """加载一个素材目录下的所有 md，按文件名排序保证 ordinal 稳定。"""
    files = sorted(
        p for p in root.rglob("*.md") if p.is_file() and p.name.upper() != "README.MD"
    )
    return [load_file(p, source_id) for p in files]
