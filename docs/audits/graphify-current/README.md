# graphify rolling refresh

This folder is auto-refreshed by `tools/graphify/refresh_delta.py` (scheduled by Windows Task Scheduler at 3am every other day, or triggered manually via `/refresh-graph`). Periodic full audits continue to land in dated `graphify-YYYY-MM-DD/` folders.

- Generated: 2026-05-06T22:47:54+00:00
- Mode: `code-only`
- HEAD at refresh: `d121a5de`
- Previous refresh SHA: `e49aef63`
- Code files re-extracted: 3
- Doc files re-extracted: 2
- Files dropped (deleted/renamed): 0

Run `python tools/graphify/query_local.py quality --graph docs/audits/graphify-current/graph.json` for shape stats.
