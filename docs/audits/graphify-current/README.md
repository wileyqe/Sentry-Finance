# graphify rolling refresh

This folder is auto-refreshed by `tools/graphify/refresh_delta.py` (scheduled by Windows Task Scheduler at 3am every other day, or triggered manually via `/refresh-graph`). Periodic full audits continue to land in dated `graphify-YYYY-MM-DD/` folders.

- Generated: 2026-05-04T22:06:21+00:00
- Mode: `manual-stale-node-prune`
- HEAD at refresh: `ba557fd6`
- Previous refresh SHA: `c877623d`
- Code files re-extracted: 0
- Doc files re-extracted: 0
- Files dropped (deleted/renamed): 1

Manual cleanup removed a stale node for a deleted trigger document; no code or
semantic extraction was rerun.

Run `python tools/graphify/query_local.py quality --graph docs/audits/graphify-current/graph.json` for shape stats.
