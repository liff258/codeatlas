"""Embedding 逻辑的单元测试（不加载真实模型）。

用假 provider 验证 BaseEmbedding 共享的那层逻辑：
指令前缀、L2 归一化、空输入校验。这些逻辑一旦写错，
症状是"检索质量变差"而不是报错，所以必须用断言守住。

真模型的语义正确性由 scripts/embed_chunks.py --dry-run 验证（需要 2.2GB 模型）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.embedding import QUERY_INSTRUCTION, BaseEmbedding  # noqa: E402


class FakeEmbedding(BaseEmbedding):
    """把文本长度当作向量，只为验证外层逻辑。"""

    model_name = "fake/test"
    dim = 4

    def __init__(self) -> None:
        self.seen: list[str] = []

    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        self.seen = list(texts)
        return np.array([[len(t), 1.0, 0.0, 0.0] for t in texts], dtype=np.float32)


def test_query_gets_instruction_prefix():
    emb = FakeEmbedding()
    emb.encode(["HashMap 扩容"], is_query=True)
    assert emb.seen[0].startswith(QUERY_INSTRUCTION)


def test_document_does_not_get_prefix():
    """文档侧加前缀会污染向量空间——这是 bge 用法的关键区别。"""
    emb = FakeEmbedding()
    emb.encode(["HashMap 扩容"], is_query=False)
    assert not emb.seen[0].startswith(QUERY_INSTRUCTION)
    assert emb.seen[0] == "HashMap 扩容"


def test_vectors_are_l2_normalized():
    emb = FakeEmbedding()
    v = emb.encode(["abc", "abcdef"])
    norms = np.linalg.norm(v, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_output_shape_and_dtype():
    emb = FakeEmbedding()
    v = emb.encode(["a", "bb", "ccc"])
    assert v.shape == (3, 4)
    assert v.dtype == np.float32


def test_empty_input_returns_empty_matrix():
    emb = FakeEmbedding()
    v = emb.encode([])
    assert v.shape == (0, 4)


def test_blank_text_rejected():
    """空串的向量没有意义，还会污染索引，必须在入口挡住。"""
    emb = FakeEmbedding()
    with pytest.raises(ValueError):
        emb.encode(["正常", "   "])


def test_zero_vector_does_not_produce_nan():
    """全零向量归一化会除出 NaN，必须兜住。"""
    class ZeroEmbedding(FakeEmbedding):
        def _encode_raw(self, texts):
            return np.zeros((len(texts), 4), dtype=np.float32)

    v = ZeroEmbedding().encode(["x"])
    assert not np.isnan(v).any()
