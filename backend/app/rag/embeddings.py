"""Embedding providers.

* ``voyage`` - Voyage AI embeddings (Anthropic's recommended embedding partner), asymmetric
  ``document`` / ``query`` input types, configurable output dimension.
* ``hashing`` - deterministic feature-hashing embedder (word uni/bi-grams + char trigrams). It needs no
  network or model weights, so air-gapped / test deployments still get a working dense channel; the
  lexical channel of hybrid retrieval carries most of the precision in that mode.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
_STOP = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "what", "which", "who", "whom", "how", "why", "when", "where", "do", "does", "did", "can", "could", "should", "would", "may", "might"]
)


class Embedder(ABC):
    model_name: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder(Embedder):
    def __init__(self, dim: int):
        self.dim = dim
        self.model_name = f"hashing-v1-{dim}"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
        feats: dict[str, float] = {}
        for t in toks:
            feats[f"w:{t}"] = feats.get(f"w:{t}", 0) + 1.0
            compact = t.replace("-", "").replace(".", "")
            if compact != t:
                feats[f"w:{compact}"] = feats.get(f"w:{compact}", 0) + 1.0
            padded = f"#{compact}#"
            for i in range(len(padded) - 2):
                g = f"c:{padded[i:i + 3]}"
                feats[g] = feats.get(g, 0) + 0.25
        for a, b in zip(toks, toks[1:], strict=False):
            feats[f"b:{a}_{b}"] = feats.get(f"b:{a}_{b}", 0) + 0.7
        for f, w in feats.items():
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            v[idx] += sign * (1 + math.log(w)) if w >= 1 else sign * w
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class VoyageEmbedder(Embedder):
    URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str, dim: int):
        self.model_name = model
        self.dim = dim
        self.http = httpx.Client(timeout=60.0, headers={"Authorization": f"Bearer {api_key}"})

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=30),
           retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)))
    def _call(self, texts: list[str], input_type: str) -> list[list[float]]:
        resp = self.http.post(self.URL, json={"input": texts, "model": self.model_name, "input_type": input_type,
                                              "output_dimension": self.dim, "truncation": True})
        if resp.status_code in (429,) or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise ValueError(f"voyage embeddings error {resp.status_code}: {resp.text[:200]}")
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            out.extend(self._call(texts[i : i + 64], "document"))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._call([text], "query")[0]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "voyage":
        if not s.voyage_api_key:
            raise RuntimeError("XDATA_VOYAGE_API_KEY required for voyage embeddings")
        return VoyageEmbedder(s.voyage_api_key.get_secret_value(), s.embedding_model, s.embedding_dim)
    return HashingEmbedder(s.embedding_dim)
