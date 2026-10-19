"""Embedding and reranking models (local ONNX via fastembed — no external API, no torch).

Both are behind small interfaces so tests can inject deterministic doubles and production could swap
in a hosted embedding API without touching retrieval code.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import math
import os
import threading
from functools import lru_cache

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class Embedder(abc.ABC):
    dim: int

    @abc.abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)


class Reranker(abc.ABC):
    name: str

    @abc.abstractmethod
    def score(self, query: str, documents: list[str]) -> list[float]:
        """Relevance in [0, 1] per document (higher is more relevant)."""

    async def ascore(self, query: str, documents: list[str]) -> list[float]:
        return await asyncio.to_thread(self.score, query, documents)


class FastEmbedEmbedder(Embedder):
    # bge models expect this instruction prefix on queries (not on passages).
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str, dim: int, cache_dir: str) -> None:
        self.model_name, self.dim, self._cache_dir = model_name, dim, cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding  # noqa: PLC0415

                logger.info("loading embedding model", extra={"model": self.model_name})
                self._model = TextEmbedding(model_name=self.model_name, cache_dir=self._cache_dir)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [v.astype(np.float32).tolist() for v in self._load().embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        prefix = self.QUERY_PREFIX if "bge" in self.model_name.lower() else ""
        return next(iter(self._load().embed([prefix + text]))).astype(np.float32).tolist()


class FastEmbedReranker(Reranker):
    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.name, self._cache_dir = model_name, cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

                logger.info("loading reranker", extra={"model": self.name})
                self._model = TextCrossEncoder(model_name=self.name, cache_dir=self._cache_dir)
        return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        logits = list(self._load().rerank(query, documents))
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    s.model_cache_dir.mkdir(parents=True, exist_ok=True)
    return FastEmbedEmbedder(s.embedding_model, s.embedding_dim, str(s.model_cache_dir))


@lru_cache
def get_reranker() -> Reranker | None:
    s = get_settings()
    if not s.reranker_enabled:
        return None
    s.model_cache_dir.mkdir(parents=True, exist_ok=True)
    return FastEmbedReranker(s.reranker_model, str(s.model_cache_dir))
