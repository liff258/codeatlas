"""向量索引与灌库。

pgvector 的查询必须用裸 SQL 而不是 ORM：
    SQLAlchemy 不认识 vector 类型，ORM 写法会把它当字符串处理，
    结果是"能插进去但查不出来"或者类型报错。用 text() + ::vector 强转最稳。

距离用 cosine（`<=>`）。存进去的向量已经 L2 归一化，
所以 cosine / 内积 / L2 三种距离的排序结果一致，以后换索引不用重灌。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import text

from app.infra.db import SessionLocal

# CPU 推理的甜点区。实测 batch=16 时约 5.6 条/秒，
# 再加大 batch 吞吐不变但单批耗时线性增长，中途失败的代价更大。
BATCH = 16


@dataclass
class VectorHit:
    chunk_id: int
    distance: float
    rank: int


def _to_pgvector(vec: np.ndarray) -> str:
    """numpy → pgvector 字面量。精度用 6 位小数，够用且能把存储压掉一半。"""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def embed_all(provider, *, batch_size: int = BATCH, limit: int | None = None) -> int:
    """给所有还没有 embedding 的 child chunk 编码并落库。

    幂等：只处理 chunk_embedding 里不存在的 chunk_id，重复跑不会重算。
    分批提交：一个 batch 一个事务，中途失败不用全部重来。
    """
    done = 0

    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT c.id, c.content
                FROM chunk c
                LEFT JOIN chunk_embedding e ON e.chunk_id = c.id
                WHERE c.level = 'child' AND e.chunk_id IS NULL
                ORDER BY c.id
                LIMIT :lim
                """
            ),
            {"lim": limit or 10**9},
        ).all()

        total = len(rows)
        if total == 0:
            print("所有 child chunk 都已有 embedding，无需处理")
            return 0

        print(f"待编码：{total} 个 child chunk")

        for start in range(0, total, batch_size):
            batch = rows[start : start + batch_size]
            ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]

            vecs = provider.encode(texts, is_query=False)
            if vecs.shape[0] != len(ids):
                raise RuntimeError(f"编码数量不匹配：{vecs.shape[0]} != {len(ids)}")

            for cid, vec in zip(ids, vecs):
                db.execute(
                    text(
                        """
                        INSERT INTO chunk_embedding (chunk_id, model, embedding)
                        VALUES (:cid, :model, CAST(:vec AS vector))
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            model = EXCLUDED.model, embedding = EXCLUDED.embedding
                        """
                    ),
                    {"cid": cid, "model": provider.model_name, "vec": _to_pgvector(vec)},
                )

            db.commit()
            done += len(batch)
            print(f"  {done}/{total}  ({done/total*100:.0f}%)")

    return done


def search(vec: np.ndarray, top_k: int = 20, *, subject: str | None = None) -> list[VectorHit]:
    """余弦最近邻。可选按学科过滤（前端筛选器用）。"""
    q = _to_pgvector(vec)
    params: dict = {"q": q, "k": top_k}

    where = ""
    if subject:
        where = "WHERE c.subject = :sj"
        params["sj"] = subject

    with SessionLocal() as db:
        rows = db.execute(
            text(
                f"""
                SELECT e.chunk_id, e.embedding <=> CAST(:q AS vector) AS distance
                FROM chunk_embedding e
                JOIN chunk c ON c.id = e.chunk_id
                {where}
                ORDER BY e.embedding <=> CAST(:q AS vector)
                LIMIT :k
                """
            ),
            params,
        ).all()

    return [VectorHit(chunk_id=r[0], distance=float(r[1]), rank=i + 1) for i, r in enumerate(rows)]


def count_embedded() -> int:
    with SessionLocal() as db:
        return db.execute(text("SELECT count(*) FROM chunk_embedding")).scalar_one()
