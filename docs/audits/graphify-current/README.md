# graphify rolling refresh

This folder is auto-refreshed by `tools/graphify/refresh_delta.py` (scheduled by Windows Task Scheduler at 3am every other day, or triggered manually via `/refresh-graph`). Periodic full audits continue to land in dated `graphify-YYYY-MM-DD/` folders.

- Generated: 2026-05-10T04:33:28+00:00
- Mode: `code-only`
- HEAD at refresh: `8eecd9a2`
- Previous refresh SHA: `63c34000`
- Code files re-extracted: 5
- Doc files re-extracted: 8
- Files dropped (deleted/renamed): 0

Run `python tools/graphify/query_local.py quality --graph docs/audits/graphify-current/graph.json` for shape stats.
