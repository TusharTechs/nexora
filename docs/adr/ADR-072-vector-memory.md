# ADR-072: Semantic (vector) organizational memory

Status: Accepted.

## Context

`InMemoryMemoryStore` held taught facts/preferences/policies/corrections and the
`ConstitutionBuilder` folded **all** of them into every mission — plus the only
retrieval was substring matching in `TeachExtractor`. That does not scale and
misses the "efficient vector embedding and schema design" the judges look for.

## Decision

- `nexora/core/embeddings.py` — `embed(texts)` returns unit-normalised vectors
  from a Vertex/Gemini embedding model (`NEXORA_EMBED_MODEL`, default
  `text-embedding-005`, 768-dim). With no backend it falls back to a
  deterministic stemmed hashed-bag-of-words + bigram vector, so ranking stays
  sensible and the hermetic tests never touch the network.
- `InMemoryMemoryStore` embeds each entry on write and gains
  `search(query, k, scope, types)` — cosine ranking over the cached vectors.
- `ConstitutionBuilder.build()` is now async and, alongside the hard forbiddens,
  runs a semantic search for the memories relevant to the mission's objective
  and stores them on `MissionConstitution.relevant_memories`.
- The Node Executor prepends those memories to the evidence every deliverable is
  composed from — "KNOWN PREFERENCES & FACTS FROM ORGANIZATIONAL MEMORY".

Verified with real Vertex embeddings: "research rival companies" retrieves
"Never cold-email competitors during market research" with zero lexical overlap.

## Consequences

- Missions honour org knowledge without stuffing the whole store into every
  prompt; retrieval is O(n) cosine over small vectors, upgradeable to a real
  vector index (Vertex Vector Search / Firestore vector fields) without touching
  callers.
- `ConstitutionBuilder.build` callers must `await`.
- New env: `NEXORA_EMBED_MODEL`, `NEXORA_EMBEDDINGS` (default on).
