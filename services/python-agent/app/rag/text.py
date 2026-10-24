"""文本度量与切分工具。

token 计数为什么不用 tiktoken：
    tiktoken 是 OpenAI 的分词器，对中文的估算偏差很大（一个汉字常被算成 1.x~2 token）。
    我们真正关心的是「这段文字会不会超出 embedding / LLM 的上下文预算」，
    一个稳定的粗略估算比一个"精确但错位"的计数更有用。

    这里的估算规则：中文 1 字 ≈ 1 token，英文 1 词 ≈ 1.3 token，标点 ≈ 0.5 token。
    对 bge-m3（XLM-RoBERTa 词表）和 DeepSeek 都偏保守，宁可多切一点。
"""

from __future__ import annotations

import re

# 中日韩统一表意文字
_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 英文单词 / 数字 / 下划线串
_WORD = re.compile(r"[A-Za-z0-9_]+")
# 标点与符号
_PUNCT = re.compile(r"[^\w\s\u4e00-\u9fff]")

# 中文句末标点。分号也算——中文技术文档里分号常用来分隔并列论点，
# 在这里断句比不断更安全。
_CJK_SENT_END = "。！？；\n"
# 英文句末：后面必须跟空白，避免把 3.14 或 e.g. 切断
_EN_SENT_END = re.compile(r"(?<=[.!?])\s+")


def count_tokens(text: str) -> int:
    """估算 token 数。同一段文字多次调用结果稳定（没有随机性、没有模型依赖）。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(text))
    punct = len(_PUNCT.findall(text))
    return cjk + int(words * 1.3) + int(punct * 0.5)


def split_sentences(text: str) -> list[str]:
    """按句切分，保留标点。

    只用于「超长段落必须再切」的场景，不用于普通段落——
    普通段落整块进 chunk，语义完整性比长度均匀更重要。
    """
    if not text:
        return []

    out: list[str] = []
    buf: list[str] = []

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        if ch in _CJK_SENT_END:
            out.append("".join(buf))
            buf = []
        elif ch in ".!?" and (i + 1 >= n or text[i + 1].isspace()):
            out.append("".join(buf))
            buf = []
        i += 1

    if buf:
        out.append("".join(buf))

    return [s for s in (x.strip() for x in out) if s]


def normalize_ws(text: str) -> str:
    """折叠多余空白，但保留段落分隔（\\n\\n）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉 NUL 和其他控制字符（保留 \n 和 \t）。
    # PDF 抽取经常带进 \x00，而 PostgreSQL 的 text 字段直接拒收，
    # 报错信息是 "cannot contain NUL (0x00) bytes"，不看清楚会以为是编码问题。
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 行内多空格折叠成一个
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 三个以上连续换行折叠成两个
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_hash(text: str) -> str:
    """chunk 级去重用的哈希。先归一化再哈希，避免空白差异导致重复入库。"""
    import hashlib

    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def file_hash(data: bytes) -> str:
    """document 级去重用的哈希。"""
    import hashlib

    return hashlib.sha256(data).hexdigest()
