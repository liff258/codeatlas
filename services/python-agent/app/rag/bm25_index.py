"""BM25 关键词索引（内存）。

为什么不用 Postgres 的全文检索：
    PG 原生不支持中文分词，需要 zhparser / pg_jieba 扩展，而官方 postgres 镜像里没有，
    自己编译要装 SCWS，在 Windows 上基本走不通。这是「10 分钟复现」的直接杀手。

    改成 Python 侧 jieba + rank_bm25，纯内存，4772 个 chunk 构建不到 2 秒，
    启动时建一次即可。代价是索引不能跨进程共享，但我们是单实例服务，无所谓。

分词策略：中英文分开处理。
    中文走 jieba 的搜索引擎模式（粒度更细，召回更高）。
    英文/技术词整体保留——把 ConcurrentHashMap 切成 Concurrent / Hash / Map 会让
    这个词的区分度直接归零，而它恰恰是最重要的检索信号。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

# 加载领域词典。jieba 是全局状态，导入时加载一次即可。
# 不加的话 "红黑树" 会被切成 "比红" + "黑树快" 这种鬼东西，BM25 直接失效。
_DICT = Path(__file__).with_name("dict.txt")
if _DICT.exists():
    jieba.load_userdict(str(_DICT))

# 技术词：字母数字 + 常见符号（C++ / C# / B+ / .NET / Spring-Boot / v1.5）
# 后缀允许接一个中文名词，否则 "B+树" 会被切成 "b+" + "树"，
# 而 "B+树 vs B树" 恰恰是最关键的一组区分——丢掉 "树" 就分不出来了。
_MIX_SUFFIX = r"(?:树|表|锁|池|队列|缓存)"
_TECH = re.compile(rf"[a-z0-9+#._-]+{_MIX_SUFFIX}?")
# 把 "b+ 树" 这种中间带空格的写法归一成 "b+树"，再交给 _TECH 整体匹配
_MIX = re.compile(rf"([a-z0-9]+\+?)\s*({_MIX_SUFFIX[3:-1]})")
# 用于 split 的分隔捕获组
_SPLIT = re.compile(rf"([a-z0-9+#._-]+{_MIX_SUFFIX}?)")


def tokenize(text: str) -> list[str]:
    """中英混合分词。纯函数，可以单独测。"""
    text = text.lower()
    # "b+ 树" → "b+树"，让后面的整体匹配能命中
    text = _MIX.sub(r"\1\2", text)

    tokens: list[str] = []

    for seg in _SPLIT.split(text):
        if not seg or not seg.strip():
            continue
        if _TECH.fullmatch(seg):
            # 纯技术词整体保留；单个字母没有区分度，丢掉
            if len(seg) >= 2:
                tokens.append(seg)
            continue
        # 中文片段交给 jieba
        for w in jieba.cut_for_search(seg):
            w = w.strip()
            if len(w) >= 2 and not w.isspace():
                tokens.append(w)

    return tokens


@dataclass
class Hit:
    chunk_id: int
    score: float
    rank: int


class BM25Index:
    """child chunk 的关键词索引。

    只索引 child：检索单位就是 child，parent 是给生成用的，不参与打分。
    """

    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self.ids: list[int] = []
        corpus: list[list[str]] = []

        for chunk_id, content in rows:
            toks = tokenize(content)
            if not toks:
                continue
            self.ids.append(chunk_id)
            corpus.append(toks)

        self._bm25 = BM25Okapi(corpus) if corpus else None

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query: str, top_k: int = 20) -> list[Hit]:
        if self._bm25 is None:
            return []

        q = tokenize(query)
        if not q:
            return []

        scores = self._bm25.get_scores(q)
        # 只取正分：BM25 对完全无关的文档会给 0 或极小的负值，混进来只会稀释结果
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(scores) if s > 0),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        return [Hit(chunk_id=self.ids[i], score=s, rank=r + 1) for r, (i, s) in enumerate(ranked)]


def build_from_db() -> BM25Index:
    """从库里拉全部 child chunk 建索引。"""
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT id, content FROM chunk WHERE level = 'child' ORDER BY id")
        ).all()

    return BM25Index([(r[0], r[1]) for r in rows])
