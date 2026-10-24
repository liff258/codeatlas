"""给所有 child chunk 生成向量并落库。

用法：
    python scripts/embed_chunks.py --dry-run        # 只检查模型能不能加载、维度对不对
    python scripts/embed_chunks.py --apply          # 真正编码并写库
    python scripts/embed_chunks.py --apply --limit 50   # 先跑 50 条验证

为什么要 --dry-run：
    bge-m3 有 2.2GB，加载要几十秒。先确认模型能起来、输出是 1024 维、
    查询和文档的相似度排序合理，再去编码 5000 多个 chunk——
    不然要等到编码完才发现维度不对，白等半小时。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))


def dry_run() -> int:
    import numpy as np

    from app.rag.embedding import LocalBGEEmbedding

    t0 = time.time()
    print("加载模型…")
    try:
        emb = LocalBGEEmbedding()
    except FileNotFoundError as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ 模型加载完成，耗时 {time.time()-t0:.1f}s")
    print(f"  模型：{emb.model_name}")
    print(f"  维度：{emb.dim}")

    if emb.dim != 1024:
        print(f"  ⚠ 维度不是 1024，与 contracts/db-schema.sql 的 vector(1024) 不符！")

    # 语义合理性检查：查询应该跟真正相关的文档更接近
    docs = [
        "HashMap 在扩容时会重新计算哈希并迁移节点，负载因子默认 0.75。",
        "Redis 的跳表通过多级索引把查找复杂度降到 O(log n)。",
        "Spring 的三级缓存用来解决单例 Bean 的循环依赖问题。",
    ]
    q = "HashMap 扩容是怎么做的"

    t1 = time.time()
    dvecs = emb.encode(docs, is_query=False)
    qvec = emb.encode([q], is_query=True)[0]
    elapsed = time.time() - t1

    print(f"\n编码 {len(docs)} 条文档 + 1 条查询，耗时 {elapsed:.2f}s")
    print(f"  输出形状：{dvecs.shape}  dtype={dvecs.dtype}")

    sims = dvecs @ qvec
    print("\n与查询的相似度（应该 HashMap 最高）：")
    for d, s in sorted(zip(docs, sims), key=lambda x: -x[1]):
        print(f"  {s:.4f}  {d[:32]}…")

    order = np.argsort(-sims)
    if order[0] != 0:
        print("\n⚠ 排序不对！最相关的不是 HashMap 那条，检查指令前缀是否生效")
        return 1

    print("\n✓ 语义排序正确")
    return 0


def apply(limit: int | None) -> int:
    from app.rag.embedding import LocalBGEEmbedding
    from app.rag.vector_index import count_embedded, embed_all

    print(f"已入库向量：{count_embedded()}")
    emb = LocalBGEEmbedding()
    print(f"模型就绪：{emb.model_name}（{emb.dim} 维）\n")

    t0 = time.time()
    done = embed_all(emb, limit=limit)
    elapsed = time.time() - t0

    if done:
        print(f"\n✓ 编码 {done} 条，耗时 {elapsed:.0f}s（{done/max(elapsed,1):.1f} 条/秒）")
    print(f"当前向量总数：{count_embedded()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    return dry_run() if args.dry_run else apply(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
