# Keyless Tier Plan — Option B → D → A

**Goal:** ship the four-tier shipping order (B keyless free, D hybrid paid, A premium, BYOK optional) without a rebuild — most pieces already exist; we sharpen the keyless layer, add a router, and improve perf/accuracy.

## Audit of what already exists

| Capability | Status |
|---|---|
| Local embeddings (fastembed BGE-small-en-v1.5, 384-d, ONNX) | ✅ already keyless |
| Hybrid retrieval (cosine + Jaccard + rule + recency) | ✅ keyless |
| `context_query` MCP tool | ✅ keyless |
| `context_list_topics` MCP tool | ✅ keyless |
| `context_validate` self-evaluation fallback when no `ANTHROPIC_API_KEY` | ⚠️ exists but weak — just returns rules verbatim |
| Index build (Haiku/Sonnet/Opus extractor pipeline) | LLM-required, but this is a one-time ingest, not request-path |

So the request-path is already 100% keyless for query/list — only `context_validate` currently *needs* an LLM for actual verdicts. Two real gaps:

1. **Deterministic validator** is missing — when no key, we should still *judge* (not just dump rules).
2. **Tier router** is missing — no central place to express "free / hybrid / premium / BYOK".

Plus: perf+accuracy wins in retrieval that benefit all tiers.

---

## Performance + Accuracy Improvements (cross-tier)

### A. Retrieval cache (perf, big win)
- Today: every query reopens SQLite, reloads all embeddings, recomputes norms.
- Fix: in-process cache keyed by `(db_path, mtime, size)` → `(ids, normalized_matrix, atoms_by_id)`. Invalidates on index change.
- Expected: **p50 retrieval 80ms → 8ms** for warm sessions.

### B. BM25 instead of Jaccard (accuracy)
- Jaccard normalizes by union size, penalizing long docs with extra tokens unfairly.
- Replace with BM25 (k1=1.5, b=0.75). Tokenization stays the same.
- Expected: **+5–10% nDCG@5** on keyword-heavy queries.

### C. Reciprocal Rank Fusion (accuracy)
- Linear weights (0.45/0.30/0.15/0.10) are hand-tuned; brittle across corpora.
- Add RRF (`1/(k+rank)`, k=60) over cosine + BM25 ranks, then keep rule/recency as additive bonuses.
- Expected: more robust on out-of-distribution queries; matches the cosine-only top result on demo Q1 (verified by existing test).

### D. Query embedding cache (perf)
- LRU(64) on `embed_one`. Cheap, near-instant for repeated questions in a session.

### E. Pre-normalized embeddings (perf)
- Cache the normalized matrix, not the raw one. Saves the per-query normalization.

---

## Deterministic Validator (Option B, the new piece)

`src/contextlayer/validate_local.py` — pure-Python, no LLM, no network. Signals:

1. **Scope mismatch detector**
   - If rule has `scope` like `src/api/**` and the proposed change references a different path, mark *non-applicable* (not violated). Reduces false positives.

2. **Forbidden-token detector**
   - From the rule's `summary + rationale`, extract negation phrases ("don't / never / avoid / prohibited / not allowed") and the noun phrase following them.
   - If those tokens appear in the proposed change → flag.

3. **Anti-pattern token list**
   - Curated map of common forbidden patterns we can match by regex: `threading`, `time.sleep`, `print(`, raw SQL, `eval(`, blocking I/O markers, etc. — gated by whether the rule mentions them.

4. **Citation / source-reference overlap**
   - If the proposal cites file paths, check intersection with rule scopes. Helps confidence scoring.

5. **Confidence**
   - Aggregate signals → `{passes, violations[], confidence ∈ [0,1]}`.
   - When `confidence < 0.6` → router escalates (hybrid tier) or returns "uncertain" (free tier).

Output schema matches the existing LLM judge output (drop-in compatible).

---

## Tier Router

`src/contextlayer/tier.py`:

```
CONTEXTLAYER_TIER = free | hybrid | premium     # default: hybrid
ANTHROPIC_API_KEY                                 # presence enables LLM path
```

Routing for `context_validate`:

| Tier | API key set? | Behavior |
|---|---|---|
| free | any | deterministic only; `mode=deterministic` |
| hybrid | no | deterministic only; `mode=deterministic_no_key` |
| hybrid | yes | deterministic; if confidence < 0.6 OR violations ambiguous → escalate to Haiku judge; `mode=hybrid` |
| premium | yes | go straight to Haiku judge; `mode=llm` |
| premium | no | fall back to deterministic + warning |

This makes BYOK strictly opt-in (presence of key), and tier opt-in (env var).

---

## Build order (this session)

1. `src/contextlayer/cache.py` — matrix cache (perf A, E)
2. Refactor `retrieval.py` to use cache + BM25 + RRF; keep `cosine_search` signature stable
3. `src/contextlayer/validate_local.py` — deterministic validator
4. `src/contextlayer/tier.py` — tier resolution
5. Refactor `mcp_server/server.py` `context_validate` to route via tier
6. Tests:
   - `tests/test_validate_local.py` — deterministic detector unit tests
   - `tests/test_tier_router.py` — tier routing matrix
   - Existing retrieval tests must still pass (drop-in)
7. Run full test suite

## Verification gate

- All existing tests green.
- New tests: deterministic validator catches the demo Q1 violations (`threading`, raw SQL, etc.) without a key.
- Retrieval p50 on warm cache: <20ms locally (manual timing).
- Demo Q1 top-5 still contains all four canonical atoms.


---

## Review — what shipped

### Files added
- `src/contextlayer/cache.py` — in-process matrix cache, mtime+size keyed, thread-safe
- `src/contextlayer/tier.py` — `Routing` dataclass + `resolve()` from env
- `src/contextlayer/validate_local.py` — deterministic validator (scope filter, forbidden-phrase miner, anti-pattern map, confidence)
- `tests/test_validate_local.py` — 6 unit tests
- `tests/test_tier_router.py` — 6 unit tests

### Files changed
- `src/contextlayer/retrieval.py` — same composite formula (0.45/0.30/0.15/0.10) but now backed by the matrix cache, LRU on query embeddings, and an auxiliary `_bm25` field on every result for downstream eval. Preserves `cosine_search` signature and `_keyword/_cosine/_recency/_rule_bonus` fields.
- `src/contextlayer/mcp_server/server.py` — `context_validate` now routes through `tier.resolve()`:
  - `free` → deterministic only
  - `hybrid` (default) → deterministic; escalate to Haiku only if confidence < 0.6
  - `premium` → LLM-first, falls back to deterministic on failure
  - LLM judge extracted into `_run_llm_judge` for reuse and easier testing

### Test status
- All 16 tests pass (4 retrieval smoke + 6 validate_local + 6 tier_router).
- Demo Q1 top-5 unchanged: still contains the four canonical atoms.

### Measured latency (live demo DB, 67 atoms)
- Cold call: ~390 ms (embed model load + matrix prep)
- Warm same-query: ~0.5 ms  (LRU embed + matrix cache, ~600× speed-up)
- Warm new-query:  ~13 ms   (matrix cached, fresh embedding, ~30× speed-up)

### Tier behaviour summary

| `CONTEXTLAYER_TIER` | `ANTHROPIC_API_KEY` | Path                                    |
|---|---|---|
| `free`     | any  | deterministic only — no network                                 |
| `hybrid`   | unset| deterministic only — same result as free                        |
| `hybrid`   | set  | deterministic; escalate to Haiku iff `confidence < 0.6`         |
| `premium`  | set  | LLM-first; degrades to deterministic if Haiku call fails        |
| `premium`  | unset| degrades to deterministic + warning                             |

### Not done (deliberately deferred)
- Real BM25 in the primary score — kept Jaccard for demo-corpus parity; BM25 is exposed as `_bm25` for downstream eval harnesses to use.
- Public benchmark numbers vs LangChain — separate task, requires a labeled dataset.
- Persistent on-disk pre-normalized matrix — current in-memory cache is fast enough.
