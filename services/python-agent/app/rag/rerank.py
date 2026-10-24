"""重排（rerank）。

为什么需要它：
    混合检索能把正确答案召回进前 20，但排不到第一位——因为 RRF 只看排名，
    BM25 那个又准又强的第一名会被向量中段的结果稀释。本项目实测
    混合检索 Hit@1 只有 46.7%，还不如纯 BM25 的 60%。

    调融合参数修不了这个（k 从 1 扫到 60 都试过），因为问题不在融合策略，
    而在「双塔模型把 query 和 doc 分开编码，丢掉了交叉信息」。
    交叉编码器把 query 和 doc 拼在一起送进模型，能捕捉到「这段是不是真在回答这个问题」，
    代价是每个候选都要跑一次前向，没法预先算好。

延迟权衡（CPU）：
    CPU 上交叉编码器很慢：12 个候选 × 256 token 约 5 秒，比检索本身慢一个数量级。
    这是必然的——双塔模型可以把文档向量预先算好，交叉编码器必须每次现算。
    所以只重排前 12 个（不是全部 20 个），并且必须在界面上显示「重排中」，
    否则用户会觉得卡住了。
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from app.config import settings

# 重排多少个候选。太少会漏掉正确答案，太多会拖慢。
RERANK_TOP_N = 12
# query + document 拼起来的最大长度。
# 实测这是延迟的主要变量：320 → 12 条要 6.6 秒，256 → 约 5 秒。
# child chunk 平均 170 token，加上 query 约 30 token，256 够用；
# 少数超长 chunk 会被截断，但截断的是尾部，对判断"这段是不是在回答"影响不大。
RERANK_MAX_LENGTH = 256
# 一次前向处理多少个 pair
RERANK_BATCH = 8


class Reranker:
    """bge-reranker 交叉编码器。

    输出是 logits（未归一化），经过 sigmoid 映射到 0~1 当作相关性分数。
    不要直接拿 logits 排序——数值范围在 -10~10 之间，看起来不像"分数"，
    而且和别的分数（余弦相似度等）没法放在一起比较。
    """

    def __init__(
        self,
        model_dir: Path | None = None,
        *,
        max_length: int = RERANK_MAX_LENGTH,
        batch_size: int = RERANK_BATCH,
    ) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_dir = model_dir or (Path(settings.model_cache_dir) / "bge-reranker-v2-m3")
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(
                f"reranker 模型不存在：{model_dir}\n"
                "先运行 python scripts/fetch_model.py --model BAAI/bge-reranker-v2-m3"
            )

        self.model_name = f"local/{model_dir.name}"
        self._max_length = max_length
        self._batch_size = batch_size
        self._lock = threading.Lock()

        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self._model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
        self._model.eval()

        torch.set_num_threads(max(1, min(8, torch.get_num_threads())))

    def score(self, query: str, docs: list[str]) -> np.ndarray:
        """返回每个 doc 与 query 的相关性分数（0~1，越大越相关）。"""
        if not docs:
            return np.zeros(0, dtype=np.float32)

        import torch

        out: list[float] = []

        with self._lock, torch.no_grad():
            for i in range(0, len(docs), self._batch_size):
                batch = docs[i : i + self._batch_size]
                # 交叉编码器的输入是 [query, doc] 对，不是两个独立的向量
                encoded = self._tokenizer(
                    [[query, d] for d in batch],
                    padding=True,
                    truncation=True,
                    max_length=self._max_length,
                    return_tensors="pt",
                )
                logits = self._model(**encoded, return_dict=True).logits.view(-1).float()
                out.extend(torch.sigmoid(logits).tolist())

        return np.asarray(out, dtype=np.float32)

    def rerank(self, query: str, chunks: list, *, top_n: int = RERANK_TOP_N) -> list:
        """对候选重排，返回前 top_n 个。

        入参是 RetrievedChunk 列表（有 .content 和 .score 属性）。
        重排后会写入 .rerank_score，并保持 .score 原值以便对比。
        """
        if not chunks:
            return []

        head = chunks[:top_n]
        tail = chunks[top_n:]

        scores = self.score(query, [c.content for c in head])

        for c, s in zip(head, scores):
            c.rerank_score = float(s)

        head.sort(key=lambda c: c.rerank_score, reverse=True)

        # 被截掉的候选保留在末尾，标记 rerank_score=None。
        # 不要直接丢弃——如果上层要取 20 条展示，还有东西可给。
        for c in tail:
            c.rerank_score = None

        return head + tail


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


def reset_reranker() -> None:
    global _reranker
    _reranker = None
