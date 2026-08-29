"""Text embeddings for semantic memory retrieval (ADR-072).

`embed()` returns a unit-normalised vector per input string, using a Vertex /
Gemini embedding model (NEXORA_EMBED_MODEL, default text-embedding-005). When no
LLM backend is configured it falls back to a deterministic hashed bag-of-words
vector so retrieval still ranks sensibly and the hermetic test suite never makes
a network call.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import List, Sequence

_DIM = 256  # fallback dimensionality
_WORD = re.compile(r"[a-z0-9']+")


def _unit(v: Sequence[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


_STOP = {"a", "an", "the", "of", "to", "for", "in", "on", "and", "or", "not",
         "is", "are", "be", "with", "our", "my", "your", "this", "that"}


def _stem(tok: str) -> str:
    for suf in ("ing", "ies", "es", "s", "ed"):
        if len(tok) > len(suf) + 2 and tok.endswith(suf):
            return tok[: -len(suf)] + ("y" if suf == "ies" else "")
    return tok


def _hashed(text: str) -> List[float]:
    vec = [0.0] * _DIM
    toks = [_stem(t) for t in _WORD.findall(text.lower()) if t not in _STOP]
    for tok in toks:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % _DIM] += 1.0
        vec[(h >> 8) % _DIM] += 0.5  # a second bucket softens collisions
    for a, b in zip(toks, toks[1:]):  # bigrams add a little word-order signal
        h = int(hashlib.md5(f"{a}_{b}".encode()).hexdigest(), 16)
        vec[h % _DIM] += 0.7
    return _unit(vec)


async def embed(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    from nexora.core.llm_client import llm_available
    if llm_available() and os.getenv("NEXORA_EMBEDDINGS", "1") == "1":
        try:
            return await _embed_remote(texts)
        except Exception:
            pass
    return [_hashed(t) for t in texts]


async def _embed_remote(texts: List[str]) -> List[List[float]]:
    import asyncio

    from nexora.core.llm_client import genai_client
    model = os.getenv("NEXORA_EMBED_MODEL", "text-embedding-005")
    client = genai_client()

    def _call() -> List[List[float]]:
        out: List[List[float]] = []
        # embed_content takes one-or-more contents; batch in small groups
        for i in range(0, len(texts), 16):
            resp = client.models.embed_content(model=model, contents=texts[i:i + 16])
            out.extend(_unit(e.values) for e in resp.embeddings)
        return out

    return await asyncio.to_thread(_call)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
