"""规模基准：知识库变大 10 倍，检索会慢多少。

v2 测出来的事实：
    纯向量查询（不带 JOIN）  0.33ms
    生产代码的带 JOIN 查询   44.0ms   ← 差 130 倍

两个都必须回答：
    1. 是 JOIN 本身贵，还是写法让 pgvector 用不上索引的优势？
    2. 库变大 10 倍，这个 44ms 会变成 440ms 吗？

做法：造 10 倍**随机**向量（不是复制——复制会让 HNSW 提前收敛，v1 就栽在这），
然后对四种写法分别测热态中位耗时。

用法：
    python scripts/bench_scale.py --scale 10
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "python-agent"))

from sqlalchemy import text  # noqa: E402

from app.infra.db import engine  # noqa: E402
from app.rag.embedding import get_provider  # noqa: E402
from app.rag.vector_index import _to_pgvector  # noqa: E402

DIM = 1024

# EXPLAIN 的输出里会打印整个 1024 维向量字面量（10KB），日志没法看。
# 只保留节点名和耗时。
_LITERAL = re.compile(r"'\[[^\]]*\]'::vector")


_EXEC_MS = re.compile(r"Execution Time: ([\d.]+) ms")


def brief_plan(conn, sql: str, params: dict) -> tuple[str, float]:
    """返回（精简后的执行计划，库内执行毫秒）。

    跑两次取第二次：第一次是冷索引（要从磁盘读图），拿它当结论会高估 5~10 倍。
    """
    exec_ms = 0.0
    lines: list[str] = []
    for attempt in range(2):
        rows = conn.execute(text("EXPLAIN (ANALYZE) " + sql), params).all()
        lines = []
        for (line,) in [(r[0],) for r in rows]:
            m = _EXEC_MS.search(line)
            if m:
                exec_ms = float(m.group(1))
            if "Order By:" in line:
                continue
            lines.append("  " + _LITERAL.sub("$Q", line).replace("  ", " ").strip()[:118])
    return "\n".join(lines), exec_ms


def warm_median(conn, sql: str, params: dict, n: int = 7) -> float:
    for _ in range(2):
        conn.execute(text(sql), params).all()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        conn.execute(text(sql), params).all()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def variants(emb_table: str, chunk_table: str) -> dict[str, str]:
    """四种写法。生产代码用的是 join_naive。"""
    return {
        # 1. 纯向量，不 JOIN
        "plain": f"""
            SELECT e.chunk_id, e.embedding <=> CAST(:q AS vector) AS distance
            FROM {emb_table} e
            ORDER BY e.embedding <=> CAST(:q AS vector)
            LIMIT :k
        """,
        # 2. 生产代码现在的写法：先 JOIN 再排序
        "join_naive": f"""
            SELECT e.chunk_id, e.embedding <=> CAST(:q AS vector) AS distance
            FROM {emb_table} e
            JOIN {chunk_table} c ON c.id = e.chunk_id
            ORDER BY e.embedding <=> CAST(:q AS vector)
            LIMIT :k
        """,
        # 3. 先取 top-k 再 JOIN（把 JOIN 挪到 LIMIT 之后）
        "join_after": f"""
            SELECT t.chunk_id, t.distance
            FROM (
                SELECT e.chunk_id, e.embedding <=> CAST(:q AS vector) AS distance
                FROM {emb_table} e
                ORDER BY e.embedding <=> CAST(:q AS vector)
                LIMIT :k
            ) t
            JOIN {chunk_table} c ON c.id = t.chunk_id
        """,
        # 4. 用 EXISTS 代替 JOIN
        "exists": f"""
            SELECT e.chunk_id, e.embedding <=> CAST(:q AS vector) AS distance
            FROM {emb_table} e
            WHERE EXISTS (SELECT 1 FROM {chunk_table} c WHERE c.id = e.chunk_id)
            ORDER BY e.embedding <=> CAST(:q AS vector)
            LIMIT :k
        """,
    }


def bench_bm25(scale: int) -> dict:
    """BM25 的查询是 O(N) 的，这里单独测——它是唯一一处线性于库大小的在线开销。

    rank_bm25 的 get_scores 对每个查询词都要遍历**全部文档**建 numpy 数组，
    不是只遍历命中的文档。所以库变大 10 倍，查询就慢 10 倍左右。
    好在基数只有几毫秒。
    """
    from rank_bm25 import BM25Okapi

    from app.rag.bm25_index import build_from_db, tokenize

    print()
    print("=" * 60)
    print(f"BM25 扩容到 {scale} 倍")
    print("=" * 60)

    bm25 = build_from_db()
    inner = bm25._bm25
    if inner is None:
        print("  索引为空，跳过")
        return {}

    # BM25Index 只存 ids 和 BM25Okapi，没留原始 token。
    # 但 doc_freqs 是「每篇文档的词 → 词频」，按词频展开能还原 token 列表
    # （顺序丢了，BM25 只看词频）。
    tokens: list[list[str]] = []
    for df in inner.doc_freqs:
        lst: list[str] = []
        for tok, cnt in df.items():
            lst.extend([tok] * int(cnt))
        tokens.append(lst)

    q = tokenize("G1 的 SATB 是什么，为什么需要它")

    def timeit(fn, n=5):
        samples = []
        for _ in range(n):
            t = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - t) * 1000)
        return statistics.median(samples)

    base_query = timeit(lambda: inner.get_scores(q))

    big_tokens = tokens * scale
    t0 = time.perf_counter()
    big = BM25Okapi(big_tokens)
    build_s = time.perf_counter() - t0
    big_query = timeit(lambda: big.get_scores(q))

    print(f"  文档数：{len(tokens)} → {len(big_tokens)}")
    print(f"  建索引：{build_s:.2f}s（当前规模 {len(tokens)} 篇约 "
          f"{build_s / scale:.2f}s，不含分词）")
    print(f"  查询：{base_query:.1f}ms → {big_query:.1f}ms"
          f"（{big_query / max(base_query, 1e-9):.1f}x）")
    return {"base": base_query, "big": big_query, "docs": len(big_tokens)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=10)
    args = ap.parse_args()
    scale = args.scale

    provider = get_provider()
    qlit = _to_pgvector(provider.encode(["G1 的 SATB 是什么"], is_query=True)[0])
    params = {"q": qlit, "k": 20}

    bm25_res = bench_bm25(scale)

    with engine.begin() as conn:
        n0 = conn.execute(text("SELECT count(*) FROM chunk_embedding")).scalar()
        print(f"当前 {n0} 条\n")

        # 基线：只把 9.7KB 的向量参数传过去、不做任何查询。
        # 这个数在下面会被从每个测量值里扣掉——否则四种写法看起来一模一样，
        # 因为真正的差异被参数传输的固定开销盖住了。
        param_overhead = warm_median(conn, "SELECT CAST(:q AS text)", {"q": qlit}, 5)
        print(f"参数传输基线（9.7KB 向量字面量，不做查询）：{param_overhead:.1f}ms")
        print("下面的「净耗时」= 实测 − 该基线\n")

        cur = variants("chunk_embedding", "chunk")
        print("=== 当前规模 ===")
        res_cur = {}
        for name, sql in cur.items():
            print(f"\n[{name}]")
            plan, exec_ms = brief_plan(conn, sql, params)
            print(plan)
            res_cur[name] = exec_ms
            print(f"  → 库内 {exec_ms:.2f}ms")

        # ---------------- 造 10 倍随机向量 ----------------
        n_big = n0 * scale
        print(f"\n=== 造 {n_big} 条随机向量（LATERAL 保证每行重算）===")
        conn.exec_driver_sql("DROP TABLE IF EXISTS _probe_emb")
        conn.exec_driver_sql("DROP TABLE IF EXISTS _probe_chunk")
        conn.exec_driver_sql(
            "CREATE TABLE _probe_chunk (id BIGINT PRIMARY KEY)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE _probe_emb (chunk_id BIGINT PRIMARY KEY, embedding vector(1024))"
        )
        t0 = time.perf_counter()
        conn.exec_driver_sql(
            f"INSERT INTO _probe_chunk SELECT g FROM generate_series(1, {n_big}) g"
        )
        # 用 ARRAY 构造器而不是 array_agg：聚合函数不能出现在自己那一层的 FROM 里
        # （LATERAL + array_agg 会报 GroupingError）。ARRAY[...] 里塞 1024 个 random()
        # 是逐行求值的，没有聚合，也不会有 GROUP BY 的坑。
        arr = ",".join(["random()"] * DIM)
        conn.exec_driver_sql(
            f"""
            INSERT INTO _probe_emb (chunk_id, embedding)
            SELECT g, (ARRAY[{arr}])::vector
            FROM generate_series(1, {n_big}) g
            """
        )
        print(f"  灌入耗时 {time.perf_counter() - t0:.1f}s")

        conn.exec_driver_sql("SET maintenance_work_mem = '1GB'")
        t0 = time.perf_counter()
        conn.exec_driver_sql(
            """
            CREATE INDEX _probe_emb_hnsw ON _probe_emb
            USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
            """
        )
        build_s = time.perf_counter() - t0
        conn.exec_driver_sql("ANALYZE _probe_chunk")
        conn.exec_driver_sql("ANALYZE _probe_emb")
        print(f"  建 HNSW 索引 {build_s:.1f}s")

        big = variants("_probe_emb", "_probe_chunk")
        print(f"\n=== {scale} 倍规模 ===")
        res_big = {}
        for name, sql in big.items():
            print(f"\n[{name}]")
            plan, exec_ms = brief_plan(conn, sql, params)
            print(plan)
            res_big[name] = exec_ms
            print(f"  → 库内 {exec_ms:.2f}ms")

        conn.exec_driver_sql("DROP TABLE _probe_emb")
        conn.exec_driver_sql("DROP TABLE _probe_chunk")

    print("\n" + "=" * 60)
    print(f"汇总（库内执行时间，N {n0} → {n_big}）")
    print("=" * 60)
    print(f"{'写法':<14}{'当前':>10}{'10 倍':>10}{'倍数':>8}")
    for name in cur:
        a, b = res_cur[name], res_big[name]
        print(f"{name:<14}{a:>8.2f}ms{b:>8.2f}ms{b / max(a, 1e-3):>7.1f}x")
    print(f"\n建 HNSW 索引（离线）：{build_s:.1f}s")
    if bm25_res:
        print(f"BM25 查询：{bm25_res['base']:.1f}ms → {bm25_res['big']:.1f}ms"
              f"（{bm25_res['big'] / max(bm25_res['base'], 1e-9):.1f}x，线性）")
    print(f"客户端看到的每个查询都要再加 {param_overhead:.1f}ms 参数传输"
          "（9.7KB 向量字面量，与库大小无关）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
