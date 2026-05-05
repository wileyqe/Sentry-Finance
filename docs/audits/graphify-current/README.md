# graphify rolling refresh

This folder is auto-refreshed by `tools/graphify/refresh_delta.py` (scheduled by Windows Task Scheduler at 3am every other day, or triggered manually via `/refresh-graph`). Periodic full audits continue to land in dated `graphify-YYYY-MM-DD/` folders.

- Generated: 2026-05-05T18:50:35+00:00
- Mode: `code-only`
- HEAD at refresh: `3682d74f`
- Previous refresh SHA: `94acb0c7`
- Code files re-extracted: 6
- Doc files re-extracted: 1
- Files dropped (deleted/renamed): 0

Run `python tools/graphify/query_local.py quality --graph docs/audits/graphify-current/graph.json` for shape stats.
