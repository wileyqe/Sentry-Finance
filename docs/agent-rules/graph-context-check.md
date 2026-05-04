# Graph Context Check

Graphify is an advisory map for "what else might be connected?" Use it to
avoid missed context before edits, not to ask permission to edit. Live code and
tests remain executable truth; `docs/ARCHITECTURE.md` remains design truth;
`docs/ROADMAP.md` remains status truth.

Run a graph check before non-trivial edits, multi-file changes, roadmap tasks,
DAL/API/frontend data-flow work, connector/parser work, schema/migration work,
PR merge/rebase work, or whenever blast radius is unclear. It is optional for
typos, tiny doc fixes, obvious one-line fixes, generated report updates, and
narrow test-only changes.

Common commands:

```powershell
python tools\graphify\query_local.py search "<term>"
python tools\graphify\query_local.py impact "<task or concept>"
python tools\graphify\query_local.py neighbors "<node or term>"
python tools\graphify\query_local.py hubs --limit 10
python tools\graphify\query_local.py drift --min-confidence 0.85
python tools\graphify\query_local.py quality
```

- Use `impact` at task start to find related files, tests, docs, and lineage.
- Use `hubs` before editing shared functions or highly connected modules.
- Use `drift` when changing invariants, docs, category rules, lineage, or
  number-trust assets.
- If the graph is stale, missing, or contradicts live code, proceed from
  code/tests and mention the graph limitation in the summary.
- For graph refresh/extraction details, see `tools/graphify/README.md`; do not
  duplicate that workflow here.
