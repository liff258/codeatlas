"""混合检索与 RRF 融合的单元测试。

RRF 是纯函数，最容易验证也最值得验证——它一旦算错，
表现是"排序看起来还行但总差一点"，不会报错，很难发现。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.bm25_index import Hit as BM25Hit  # noqa: E402
from app.rag.retrieve import RRF_K, rrf_fuse  # noqa: E402
from app.rag.vector_index import VectorHit  # noqa: E402


def bm25(cid: int, rank: int, score: float = 10.0) -> BM25Hit:
    return BM25Hit(chunk_id=cid, score=score, rank=rank)


def vec(cid: int, rank: int, dist: float = 0.2) -> VectorHit:
    return VectorHit(chunk_id=cid, distance=dist, rank=rank)


def test_single_source_preserves_order():
    fused = rrf_fuse([bm25(1, 1), bm25(2, 2), bm25(3, 3)], [], top_n=10)
    assert [f.chunk_id for f in fused] == [1, 2, 3]
    assert fused[0].rrf_score > fused[1].rrf_score > fused[2].rrf_score


def test_both_sources_beat_single_source():
    """两路都召回的，必须排在只有一路召回的前面。这是 RRF 的核心价值。"""
    # chunk 9 在两边都排第 3；chunk 1 只在 bm25 排第 1
    fused = rrf_fuse(
        [bm25(1, 1), bm25(9, 3)],
        [vec(8, 1), vec(9, 3)],
        top_n=10,
    )
    assert fused[0].chunk_id == 9, "双路召回的应该排第一"
    assert fused[0].sources == "bm25+vector"


def test_score_formula():
    """手工核对一下公式：1/(k+rank) 相加。"""
    fused = rrf_fuse([bm25(7, 2)], [vec(7, 5)], top_n=10)
    expected = 1 / (RRF_K + 2) + 1 / (RRF_K + 5)
    assert abs(fused[0].rrf_score - expected) < 1e-12


def test_no_duplicate_chunk_ids():
    """同一个 chunk 被两路召回时只能出现一次，分数相加而不是产生两条。"""
    fused = rrf_fuse([bm25(5, 1), bm25(5, 1)], [vec(5, 1)], top_n=10)
    ids = [f.chunk_id for f in fused]
    assert ids.count(5) == 1


def test_empty_inputs():
    assert rrf_fuse([], [], top_n=10) == []
    assert len(rrf_fuse([bm25(1, 1)], [], top_n=10)) == 1
    assert len(rrf_fuse([], [vec(1, 1)], top_n=10)) == 1


def test_top_n_truncates():
    bm = [bm25(i, i) for i in range(1, 21)]
    fused = rrf_fuse(bm, [], top_n=5)
    assert len(fused) == 5


def test_rank_fields_recorded():
    """两路各自的排名要留住，调试台要展示"这一条是 BM25 第 2、向量第 7 找到的"。"""
    fused = rrf_fuse([bm25(3, 2)], [vec(3, 7, dist=0.31)], top_n=5)
    f = fused[0]
    assert f.bm25_rank == 2
    assert f.vec_rank == 7
    assert abs(f.vec_distance - 0.31) < 1e-9


def test_vector_only_hit_has_no_bm25_rank():
    fused = rrf_fuse([], [vec(11, 1)], top_n=5)
    assert fused[0].bm25_rank is None
    assert fused[0].sources == "vector"
