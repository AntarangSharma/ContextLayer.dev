# demo-data/

This directory holds:

- `acme-billing-api/` — a 15-PR synthetic git repo authored by `build_acme.py`.
  Used as the **primary demo path** (Appendix A #16 in the design spec).
  Generator + repo land at T+2 in Phase 1.

- `acme-billing-api.db` (gitignored runtime artifact) — pre-indexed SQLite store.
  Committed at T+24 once the full pipeline is locked.

- (Optional, conditional on Phase 3 stretch) `fastapi/` and `fastapi.db`.
