"""Sentence embeddings (ROADMAP §6.5) behind one small interface.

- `FastEmbedder`: a local ONNX model through `fastembed` (e.g. BAAI/bge-small-en-v1.5), used when the package is
  installed and the model can be loaded (EMBEDDINGS=fastembed or auto).
- `HashEmbedder`: deterministic feature hashing of stemmed words, word bigrams and character 4-grams. No downloads,
  no dependencies; catches morphology ("analytics" ~ "analytical") and shared phrases. The default fallback.

Vectors are L2-normalised lists of floats, so cosine similarity is a dot product.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from functools import lru_cache
from typing import Protocol

log = logging.getLogger("cvmatch.embed")
_WORD = re.compile(r"[a-z0-9+#]+")
_STOP = frozenset("a an the and or of in on to with for at by from as is are be we you our your this that will "
                  "have has using use experience strong ability skills skill work working years year".split())


class Embedder(Protocol):
    name: str
    floor: float
    span: float
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "s", "al", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _h(feature: str, dim: int) -> tuple[int, float]:
    d = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    v = int.from_bytes(d, "little")
    return v % dim, (1.0 if (v >> 63) & 1 else -1.0)


class HashEmbedder:
    floor, span = 0.20, 0.35          # cosine → credit mapping (lexical vectors: lower similarities)

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hash-{dim}"

    @lru_cache(maxsize=20000)
    def _one(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self.dim
        words = [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP]
        feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:])]
        for w in words:
            p = f"#{w}#"
            feats += [(f"c:{p[i:i + 4]}", 0.25) for i in range(max(1, len(p) - 3))]
        for f, wt in feats:
            i, sign = _h(f, self.dim)
            vec[i] += sign * wt
        n = math.sqrt(sum(x * x for x in vec)) or 1.0
        return tuple(x / n for x in vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(self._one(t)) for t in texts]


class FastEmbedder:
    floor, span = 0.55, 0.25          # dense sentence models: unrelated text already scores ~0.4-0.5

    def __init__(self, model: str):
        from fastembed import TextEmbedding           # optional dependency
        self._m = TextEmbedding(model_name=model)
        self.name = f"fastembed:{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for v in self._m.embed(texts):
            v = [float(x) for x in v]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


@lru_cache(maxsize=1)
def get() -> Embedder:
    mode = os.getenv("EMBEDDINGS", "auto").lower()
    if mode in ("auto", "fastembed"):
        try:
            return FastEmbedder(os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
        except Exception as e:                        # not installed, or model can't be downloaded/loaded
            if mode == "fastembed":
                log.warning("fastembed unavailable (%s); using hashing embeddings", type(e).__name__)
    return HashEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
