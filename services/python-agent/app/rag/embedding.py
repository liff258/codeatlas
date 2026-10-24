"""Embedding 提供方。

设计成接口而不是直接调模型，原因有两个：
1. 现在用本地模型（用户没有 API 预算），以后接硅基流动只换一个实现，检索代码不动
2. 单测可以用一个假的 provider，不需要真下 2.2GB 模型

⚠️ bge 系列的指令前缀（最容易静默踩的坑）：
    对「查询」必须加前缀「为这个句子生成表示以用于检索相关文章：」，文档侧不加。
    忘了加不会报错，只是检索质量悄悄掉一档——向量空间整体偏移，
    表现为"搜出来的都沾点边但就是不精准"，很难归因。
    这个坑在 BGE 的 README 里写了，但很多人不看。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from app.config import settings

# bge 中文模型的查询指令前缀
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# bge-m3 的最大长度。官方说支持 8192，但没必要。
# 实测：max_length 直接决定 CPU 推理成本（注意力是 O(n²)）。
# 我们的 child chunk 平均 170 token、p95 290、极少数代码块到 629，
# 取 384 能覆盖 95% 以上，再把长度翻倍只会让编码时间翻倍。
MAX_LENGTH = 384


@runtime_checkable
class EmbeddingProvider(Protocol):
    """encode 的入参 is_query 决定是否加指令前缀，调用方必须显式传。"""

    model_name: str
    dim: int

    def encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        """把文本编码成 (len(texts), dim) 的 float32 数组，已做 L2 归一化。"""
        ...


class BaseEmbedding(ABC):
    """共享的批处理与校验逻辑。"""

    model_name: str
    dim: int

    @abstractmethod
    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        """子类实现真正的编码，不需要关心 is_query。"""

    def encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if any(not t or not t.strip() for t in texts):
            raise ValueError("待编码的文本不能为空——空串的向量没有意义，且会污染索引")

        if is_query:
            texts = [QUERY_INSTRUCTION + t for t in texts]

        vecs = self._encode_raw(texts)

        # L2 归一化：pgvector 的 cosine 距离本身会归一，但存归一化后的向量有个好处——
        # 之后如果改用内积索引，结果完全一致，不用重新灌库。
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # 防零向量除出 NaN
        return (vecs / norms).astype(np.float32)


class LocalBGEEmbedding(BaseEmbedding):
    """本地 bge 模型（torch + transformers）。

    模型目录：data/models/<模型名>，由 scripts/fetch_model.py 下载。
    """

    def __init__(self, model_dir: Path | None = None, *, max_length: int = MAX_LENGTH) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        model_dir = model_dir or (Path(settings.model_cache_dir) / "bge-m3")
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(
                f"模型不存在：{model_dir}\n先运行 python scripts/fetch_model.py 下载（约 2.2GB）"
            )

        self.model_name = f"local/{model_dir.name}"
        self._max_length = max_length

        # 线程锁：torch 模型不是线程安全的，而 ingest 和 API 会在不同线程调用
        self._lock = threading.Lock()

        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self._model = AutoModel.from_pretrained(str(model_dir))
        self._model.eval()

        # 推断维度：跑一次前向太浪费，直接查 config
        self.dim = int(self._model.config.hidden_size)

        # 线程数：留 2 个核给数据库和其他进程，其余全给推理。
        # 之前限到 4 是错的——16 核机器上白白浪费一半算力。
        torch.set_num_threads(max(1, min(8, torch.get_num_threads())))

    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        import torch

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self._max_length,
            return_tensors="pt",
        )

        with self._lock, torch.no_grad():
            out = self._model(**encoded)

        # mean pooling + attention mask。
        # 注意不能直接 out.last_hidden_state.mean(dim=1)——padding 位会被算进去，
        # 批量推理时结果和单条推理不一致。这是 BGE 官方实现里的标准做法。
        mask = encoded["attention_mask"].unsqueeze(-1).expand(out.last_hidden_state.size()).float()
        summed = (out.last_hidden_state * mask).sum(dim=1)
        counted = mask.sum(dim=1).clamp(min=1e-9)
        return (summed / counted).numpy()


class SiliconFlowEmbedding(BaseEmbedding):
    """硅基流动的 embedding API。

    等用户有 API key 时启用。配置见 .env 的 SILICONFLOW_API_KEY。
    """

    model_name = "siliconflow/bge-m3"
    dim = 1024

    def __init__(self, api_key: str | None = None, *, batch_size: int = 128) -> None:
        self._api_key = api_key or settings.siliconflow_api_key
        if not self._api_key.strip():
            raise RuntimeError("SILICONFLOW_API_KEY 未配置，无法使用 API embedding")
        self._batch_size = batch_size

    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=settings.siliconflow_base_url)

        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            resp = client.embeddings.create(model=settings.embedding_model, input=batch)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda x: x.index))

        return np.asarray(out, dtype=np.float32)


# ---------------------------------------------------------------- 工厂


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    """进程内单例。模型加载一次约几秒，不该每次请求都重建。"""
    global _provider
    if _provider is None:
        # 有 key 就走 API（快、不占本地内存），否则用本地模型
        if settings.siliconflow_api_key.strip():
            _provider = SiliconFlowEmbedding()
        else:
            _provider = LocalBGEEmbedding()
    return _provider


def reset_provider() -> None:
    """测试用：清掉单例。"""
    global _provider
    _provider = None
