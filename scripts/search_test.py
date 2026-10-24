"""检索效果冒烟测试。

不写断言，只打印结果——这一步的目的是**用眼睛看**召回质量，
再决定阈值、分词、融合权重怎么调。断言留给 tests/。

用法：
    python scripts/search_test.py                     # 默认 hybrid，全部示例查询
    python scripts/search_test.py --mode bm25         # 只看关键词召回（秒出，不加载模型）
    python scripts/search_test.py --mode vector       # 只看向量召回
    python scripts/search_test.py --query "HashMap 扩容" --top 5
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

from app.rag.bm25_index import build_from_db, tokenize  # noqa: E402

DEFAULT_QUERIES = [
    "MySQL 索引为什么用 B+ 树",
    "HashMap 的扩容机制",
    "G1 收集器的 SATB 是什么",
    "ConcurrentHashMap 怎么保证线程安全",
    "Redis 跳表为什么比红黑树快",
    "Spring 循环依赖三级缓存",
    "TCP 三次握手为什么不是两次",
]


def fetch_chunks(ids: list[int]) -> dict[int, tuple[str, str]]:
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    if not ids:
        return {}
    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT id, heading_path, content FROM chunk WHERE id = ANY(:ids)"),
            {"ids": ids},
        ).all()
    return {r[0]: (r[1] or "", r[2]) for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument(
        "--mode", choices=["bm25", "vector", "hybrid", "rerank"], default="hybrid"
    )
    args = ap.parse_args()

    t0 = time.time()
    bm25 = build_from_db()
    print(f"BM25 索引：{len(bm25)} 个 child chunk，构建 {(time.time()-t0)*1000:.0f}ms")

    provider = None
    if args.mode in ("vector", "hybrid", "rerank"):
        from app.rag.embedding import LocalBGEEmbedding

        t1 = time.time()
        provider = LocalBGEEmbedding()
        print(f"向量模型：{provider.model_name}（{provider.dim} 维），加载 {(time.time()-t1):.1f}s")

    reranker = None
    if args.mode == "rerank":
        from app.rag.rerank import Reranker

        t2 = time.time()
        reranker = Reranker()
        print(f"重排模型：{reranker.model_name}，加载 {(time.time()-t2):.1f}s")

    print(f"检索模式：{args.mode}\n")

    for q in args.query or DEFAULT_QUERIES:
        print("=" * 74)
        print(f"Q: {q}")
        if args.mode != "vector":
            print(f"   分词：{' / '.join(tokenize(q))}")

        t = time.time()
        ids: list[int] = []
        detail: list[str] = []

        b = bm25.search(q, top_k=20) if args.mode in ("bm25", "hybrid", "rerank") else []
        v = []
        if args.mode in ("vector", "hybrid", "rerank"):
            from app.rag.vector_index import search as vec_search

            qvec = provider.encode([q], is_query=True)[0]
            v = vec_search(qvec, top_k=20)

        if args.mode == "bm25":
            ids = [h.chunk_id for h in b[: args.top]]
            detail = [f"bm25#{h.rank}" for h in b[: args.top]]
        elif args.mode == "vector":
            ids = [h.chunk_id for h in v[: args.top]]
            detail = [f"vec#{h.rank} d={h.distance:.3f}" for h in v[: args.top]]
        elif args.mode == "hybrid":
            from app.rag.retrieve import rrf_fuse

            fused = rrf_fuse(b, v, top_n=args.top)
            ids = [h.chunk_id for h in fused]
            detail = [h.sources for h in fused]
        else:  # rerank：先融合 20 条，再重排取前 top 条
            from app.rag.retrieve import rrf_fuse

            fused = rrf_fuse(b, v, top_n=20)
            cand_ids = [h.chunk_id for h in fused]
            cand = fetch_chunks(cand_ids)
            scores = reranker.score(q, [cand.get(i, ("", ""))[1] for i in cand_ids])
            order = sorted(range(len(cand_ids)), key=lambda k: -scores[k])
            ids = [cand_ids[k] for k in order[: args.top]]
            detail = [f"rr={scores[k]:.3f}" for k in order[: args.top]]

        ms = (time.time() - t) * 1000
        chunks = fetch_chunks(ids)

        if not ids:
            print("   ⚠ 无结果\n")
            continue

        for i, cid in enumerate(ids):
            heading, content = chunks.get(cid, ("", ""))
            preview = " ".join(content.split())[:100]
            print(f"   #{i+1} [{detail[i]:<16}] {heading or '(无标题)'}")
            print(f"        {preview}…")
        print(f"   ({ms:.0f}ms)\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
