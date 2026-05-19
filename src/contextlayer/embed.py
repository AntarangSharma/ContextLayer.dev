"""fastembed wrapper — BAAI/bge-small-en-v1.5, 384-d, ONNX runtime.

Singleton model (first call downloads ~30s; subsequent calls instant).
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

log = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384


@lru_cache(maxsize=1)
def _model():
    """Lazy-load fastembed.TextEmbedding once."""
    from fastembed import TextEmbedding
    log.info("Loading fastembed model %s (first run downloads ~120MB)...", MODEL_NAME)
    return TextEmbedding(model_name=MODEL_NAME)


def embed_one(text: str) -> np.ndarray:
    """Return a 384-d float32 vector for the given text."""
    model = _model()
    vec = next(iter(model.embed([text])))
    return np.asarray(vec, dtype=np.float32)


def embed_many(texts: list[str]) -> np.ndarray:
    """Return an (N, 384) float32 matrix."""
    model = _model()
    vecs = list(model.embed(texts))
    return np.asarray(vecs, dtype=np.float32)
