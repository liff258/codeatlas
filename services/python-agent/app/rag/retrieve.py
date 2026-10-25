"""混合检索：BM25 + 向量，用 RRF 融合。

为什么用 RRF 而不是加权分数：
    BM25 的分数是无界的（实测 10~50），余弦距离是 0~2，两者量纲完全不同。
    想加权就得先归一化，而归一化本身就要拍参数——min-max 会被离群值带偏，
    z-score 假设分布，两种都不稳。

    RRF 只看排名不看分数：
        score(d) = Σ 1 / (k + rank_i(d))
    好处是零参数（k 取经验值 60）、对两路的分数量纲完全免疫，
    而且在「一路强一路弱」时表现稳定。这是工业界的默认选择，不是因为它最好，
    而是因为它最不容易出错。

为什么两路都要：
    BM25 强在精确词命中（"ConcurrentHashMap" 这种专有名词），
    弱在语义（问"怎么保证线程安全"，文档里写的是"并发安全"就匹配不上）。
    向量反过来。互补性很明显。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.rag.bm25_index import BM25Index, Hit as BM25Hit
from app.rag.vector_index import VectorHit

# RRF 的平滑常数。60 是原论文的经验值，作用是压低头部排名的绝对优势，
# 让两路的中段结果也有机会浮上来。
RRF_K = 60


@dataclass
class FusedHit:
    chunk_id: int
    rrf_score: float
    bm25_rank: int | None = None
    bm25_score: float | None = None
    vec_rank: int | None = None
    vec_distance: float | None = None

    @property
    def sources(self) -> str:
        """这一条是被哪几路召回的。调试和演示时很有用。"""
        parts = []
        if self.bm25_rank is not None:
            parts.append("bm25")
        if self.vec_rank is not None:
            parts.append("vector")
        return "+".join(parts)


def rrf_fuse(
    bm25_hits: list[BM25Hit],
    vector_hits: list[VectorHit],
    *,
    k: int = RRF_K,
    top_n: int = 20,
) -> list[FusedHit]:
    """倒数排名融合。纯函数，可以单独测。

    同一 chunk 被两路同时召回时，分数相加——这正是我们想要的：
    两路都认为相关的，可信度应该高于只有一路认为相关的。
    """
    table: dict[int, FusedHit] = {}

    for h in bm25_hits:
        table[h.chunk_id] = FusedHit(
            chunk_id=h.chunk_id,
            rrf_score=1.0 / (k + h.rank),
            bm25_rank=h.rank,
            bm25_score=h.score,
        )

    for h in vector_hits:
        item = table.get(h.chunk_id)
        if item is None:
            item = FusedHit(chunk_id=h.chunk_id, rrf_score=0.0)
            table[h.chunk_id] = item
        item.vec_rank = h.rank
        item.vec_distance = h.distance
        item.rrf_score += 1.0 / (k + h.rank)

    ranked = sorted(table.values(), key=lambda x: x.rrf_score, reverse=True)
    return ranked[:top_n]


@dataclass
class RetrievedChunk:
    """检索结果的完整形态，够前端直接渲染。"""

    chunk_id: int
    parent_chunk_id: int | None
    content: str
    heading_path: str
    subject: str | None
    doc_id: int
    doc_name: str
    score: float            # RRF 融合分
    bm25_rank: int | None
    vec_rank: int | None
    preview: str = field(default="")
    # 重排分（0~1）。没开重排或该条没进重排窗口时为 None。
    # 单独存一个字段而不是覆盖 score，是为了能对比"融合排第几 / 重排排第几"。
    rerank_score: float | None = None


class HybridRetriever:
    """两路召回 + RRF 融合。

    BM25 索引在内存里（启动时建一次），向量在 pgvector 里（每次查库）。
    """

    def __init__(self, bm25: BM25Index, provider=None) -> None:
        self._bm25 = bm25
        self._provider = provider  # 懒加载，避免没装 torch 时连 BM25 都用不了

    @property
    def provider(self):
        if self._provider is None:
            from app.rag.embedding import get_provider

            self._provider = get_provider()
        return self._provider

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        top_n: int = 12,
        rerank: bool = True,
    ) -> list[RetrievedChunk]:
        from app.rag.vector_index import search as vec_search

        bm25_hits = self._bm25.search(query, top_k=top_k)

        vec_hits: list[VectorHit] = []
        try:
            qvec = self.provider.encode([query], is_query=True)[0]
            vec_hits = vec_search(qvec, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            # 向量这一路挂了不该让整个检索失败——降级成纯 BM25，
            # 并且把原因写进日志，不然排查时会以为"向量效果不好"。
            print(f"[retrieve] 向量检索降级：{type(e).__name__}: {e}")

        fused = rrf_fuse(bm25_hits, vec_hits, top_n=top_n)
        chunks = self._hydrate(fused)

        if rerank and chunks:
            chunks = self._rerank(query, chunks)

        return chunks

    def _rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """重排。失败时退回融合顺序，不抛异常。

        重排是「锦上添花」的一步，它挂了不该让整个检索失败——
        融合后的结果本来就能用，只是排序没那么准。
        """
        try:
            from app.rag.rerank import get_reranker

            return get_reranker().rerank(query, chunks)
        except Exception as e:  # noqa: BLE001
            print(f"[retrieve] 重排降级：{type(e).__name__}: {e}")
            return chunks

    def _hydrate(self, hits: list[FusedHit]) -> list[RetrievedChunk]:
        if not hits:
            return []

        from sqlalchemy import text

        from app.infra.db import SessionLocal

        ids = [h.chunk_id for h in hits]
        with SessionLocal() as db:
            rows = db.execute(
                text(
                    """
                    SELECT c.id, c.parent_chunk_id, c.content, c.heading_path, c.subject,
                           d.id AS doc_id, d.filename
                    FROM chunk c
                    JOIN document d ON d.id = c.document_id
                    WHERE c.id = ANY(:ids)
                    """
                ),
                {"ids": ids},
            ).all()

        by_id = {r[0]: r for r in rows}
        out: list[RetrievedChunk] = []

        for h in hits:
            r = by_id.get(h.chunk_id)
            if r is None:
                continue
            content = r[2]
            out.append(
                RetrievedChunk(
                    chunk_id=r[0],
                    parent_chunk_id=r[1],
                    content=content,
                    heading_path=r[3] or "",
                    subject=r[4],
                    doc_id=r[5],
                    doc_name=r[6],
                    score=h.rrf_score,
                    bm25_rank=h.bm25_rank,
                    vec_rank=h.vec_rank,
                    preview=" ".join(content.split())[:80],
                )
            )

        return out


def build_retriever() -> HybridRetriever:
    """每次调用都重新建 BM25 索引。

    只适合脚本和测试。服务里请用 get_retriever()——5456 条文档建索引要 2 秒，
    每个请求重建一次纯属浪费。
    """
    from app.rag.bm25_index import build_from_db

    return HybridRetriever(build_from_db())


_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    """进程内单例。索引是只读的，可以安全共享。"""
    global _retriever
    if _retriever is None:
        _retriever = build_retriever()
    return _retriever


def reset_retriever() -> None:
    """重新入库后调用，让索引反映最新数据。"""
    global _retriever
    _retriever = None
