"""检索效果冒烟测试。

不写断言，只打印结果——这一步的目的是**用眼睛看**召回质量，
再决定阈值、分词、融合权重怎么调。

用法：
    python scripts/search_test.py
    python scripts/search_test.py --query "HashMap 扩容" --top 8
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", help="只跑指定查询")
    ap.add_argument("--top", type=int, default=3, help="每条查询显示前 n 个结果")
    args = ap.parse_args()

    t0 = time.time()
    index = build_from_db()
    build_ms = (time.time() - t0) * 1000

    print(f"索引：{len(index)} 个 child chunk，构建耗时 {build_ms:.0f}ms\n")

    queries = args.query or DEFAULT_QUERIES

    for q in queries:
        toks = tokenize(q)
        print("=" * 74)
        print(f"Q: {q}")
        print(f"   分词：{' / '.join(toks)}")

        t = time.time()
        hits = index.search(q, top_k=args.top)
        ms = (time.time() - t) * 1000

        if not hits:
            print("   ⚠ 无结果")
            continue

        for h in hits:
            row = fetch_chunk(h.chunk_id)
            if not row:
                continue
            heading, content = row
            preview = " ".join(content.split())[:110]
            print(f"   #{h.rank} [{h.score:6.2f}] {heading or '(无标题)'}")
            print(f"        {preview}…")
        print(f"   ({ms:.0f}ms)\n")

    return 0


def fetch_chunk(chunk_id: int) -> tuple[str, str] | None:
    from sqlalchemy import text

    from app.infra.db import SessionLocal

    with SessionLocal() as db:
        r = db.execute(
            text("SELECT heading_path, content FROM chunk WHERE id = :id"), {"id": chunk_id}
        ).first()
    return (r[0] or "", r[1]) if r else None


if __name__ == "__main__":
    raise SystemExit(main())
