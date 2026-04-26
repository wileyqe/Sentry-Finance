"""build_diagrams.py — Phase 4 generator for docs/data-lineage/diagrams/.

Walks lineage/*.yaml and emits one Mermaid `graph LR` per event, plus a
`_overview.mmd` that shows the dominant write/read flow between the four
event classes, the central tables, and the top UI surfaces.

Run from docs/data-lineage/:
  python build_diagrams.py

Re-run after any lineage/*.yaml edit. Diagrams are GENERATED — do not
hand-edit; changes belong in the source YAML.

Per-event diagram shape:
  origin (rect)  -->  write tables (stadium)  -->  consumers + derivations
  (rect) --> ui surfaces (hex). External effects branch off the first
  write table as circles. Edge selection from consumer/derivation back
  to a table prefers a `<table>.<col>` match in the consumer's reads /
  derivation's inputs; otherwise falls back to the first write table.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
LINEAGE_DIR = ROOT / "lineage"
DIAG_DIR = ROOT / "diagrams"

TABLE_COL_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\.([a-zA-Z_*][a-zA-Z0-9_]*)")
BARE_TABLE_RE = re.compile(r"^\s*([a-z][a-z0-9_]+)")
SSE_TOKEN_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*)`")
UPPER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

VALID_CLASSES = ("user_action", "external_force", "system_derived",
                 "system_scheduled", "live_only")


def coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def safe_id(prefix: str, value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    s = re.sub(r"_+", "_", s).strip("_")
    return (f"{prefix}_{s}" if s else prefix)[:60]


def escape_label(text: str, max_len: int = 90) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.replace('"', "'").replace("`", "'")
    # Mermaid label parser dislikes parens/brackets in some node shapes;
    # square brackets and curly braces get stripped to keep things safe.
    s = s.replace("[", "(").replace("]", ")")
    s = s.replace("{", "(").replace("}", ")")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def fmt_origin(rec: dict) -> str:
    o = rec.get("origin") or {}
    f = (o.get("file") or "?").strip()
    sym = (o.get("symbol") or "?").strip()
    # symbol fields are sometimes multi-line folded scalars; collapse.
    sym = re.sub(r"\s+", " ", sym)
    return f"{f}:{sym}"


def extract_tables(strs, known_tables: set[str]) -> set[str]:
    """Return the subset of known_tables referenced by these reads/inputs strings."""
    out: set[str] = set()
    for s in strs:
        if not isinstance(s, str):
            continue
        m = TABLE_COL_RE.match(s)
        if m and m.group(1) in known_tables:
            out.add(m.group(1))
            continue
        m2 = BARE_TABLE_RE.match(s)
        if m2 and m2.group(1) in known_tables:
            out.add(m2.group(1))
    return out


GENERIC_TOKENS = {"SSE", "INFO", "WARN", "WARNING", "ERROR", "DEBUG", "API",
                  "DAL", "POST", "GET", "PATCH", "PUT", "DELETE", "HTTP",
                  "TRUE", "FALSE", "NULL", "JSON", "CSV", "PDF"}


def extract_external_token(text: str, idx: int) -> str:
    """Pull a representative SSE topic / external token from prose."""
    if not isinstance(text, str):
        return f"effect_{idx}"
    stripped = text.strip()

    # 1. If the line opens with "SSE <topic>" the topic comes right after.
    leading_sse = re.match(r"\s*SSE\s+([a-zA-Z_][a-zA-Z_0-9]*)", stripped)
    if leading_sse:
        tok = leading_sse.group(1)
        if tok.lower() not in {"after", "on", "per", "the", "and"} and len(tok) >= 3:
            return tok

    # 2. Uppercase identifiers like REFRESH_COMPLETE — prefer underscore-bearing.
    upper = UPPER_TOKEN_RE.findall(text)
    for tok in upper:
        if tok not in GENERIC_TOKENS and "_" in tok:
            return tok
    for tok in upper:
        if tok not in GENERIC_TOKENS:
            return tok

    # 3. backticked identifiers
    backtick = SSE_TOKEN_RE.findall(text)
    for tok in backtick:
        if tok.upper() not in GENERIC_TOKENS and len(tok) >= 3:
            return tok
    if backtick:
        return backtick[0]
    if upper:
        return upper[0]
    words = re.findall(r"[A-Za-z0-9_]+", text)[:3]
    return "_".join(words) or f"effect_{idx}"


_NO_EFFECT_PREFIXES = ("no sse", "no notification", "none", "not applicable",
                       "n/a", "no external")


def is_noop_effect(text: str) -> bool:
    if not isinstance(text, str):
        return True
    s = text.strip().lower()
    if not s or s == "[]":
        return True
    if any(s.startswith(p) for p in _NO_EFFECT_PREFIXES):
        return True
    return False


def gen_event_diagram(rec: dict) -> str:
    eid = rec.get("event_id", "unknown")
    label = rec.get("label", eid)
    klass = rec.get("class", "?")

    out: list[str] = []
    out.append(f"%% Auto-generated by build_diagrams.py — do not edit by hand.")
    out.append(f"%% Event: {eid} (class: {klass})")
    out.append(f"%% {label}")
    out.append("graph LR")

    # Node-style classes — applied at the bottom with classDef + class.
    style_origin: list[str] = []
    style_table: list[str] = []
    style_consumer: list[str] = []
    style_derivation: list[str] = []
    style_ui: list[str] = []
    style_effect: list[str] = []

    # Origin
    origin_label = fmt_origin(rec)
    out.append(f'  origin["{escape_label(origin_label, 110)}"]')
    style_origin.append("origin")

    # Write tables — one node per distinct table name (operations collapsed).
    seen_tables: list[str] = []
    table_ops: dict[str, list[str]] = defaultdict(list)
    for w in rec.get("write_signature") or []:
        if not isinstance(w, dict):
            continue
        t = w.get("table")
        if not t or not isinstance(t, str):
            continue
        op = (w.get("operation") or "").strip() or "write"
        table_ops[t].append(op)
        if t not in seen_tables:
            seen_tables.append(t)

    for t in seen_tables:
        ops = ",".join(sorted(set(table_ops[t])))
        nid = safe_id("tbl", t)
        out.append(f'  {nid}[("{escape_label(t)}<br/>{escape_label(ops, 30)}")]')
        out.append(f"  origin --> {nid}")
        style_table.append(nid)

    known_tables: set[str] = set(seen_tables)

    # Direct consumers
    consumer_nodes: list[tuple[str, set[str]]] = []
    for i, dc in enumerate(rec.get("direct_consumers") or []):
        if not isinstance(dc, dict):
            continue
        f = (dc.get("file") or "?").strip()
        sym = (dc.get("symbol") or "?").strip()
        sym = re.sub(r"\s+", " ", sym)
        reads = coerce_list(dc.get("reads"))
        nid = safe_id(f"dc{i}", sym or f"c{i}")
        out.append(f'  {nid}["{escape_label(f + ":" + sym, 90)}"]')
        consumer_nodes.append((nid, extract_tables(reads, known_tables)))
        style_consumer.append(nid)

    # Derivations
    derivation_nodes: list[tuple[str, set[str]]] = []
    for i, d in enumerate(rec.get("derivations") or []):
        if not isinstance(d, dict):
            continue
        metric = (d.get("metric") or f"derivation_{i}").strip()
        f = (d.get("file") or "?").strip()
        sym = (d.get("symbol") or "?").strip()
        sym = re.sub(r"\s+", " ", sym)
        inputs = coerce_list(d.get("inputs"))
        nid = safe_id(f"dv{i}", metric)
        first = escape_label(metric, 50)
        second = escape_label(f"{f}:{sym}", 70)
        out.append(f'  {nid}["{first}<br/>{second}"]')
        derivation_nodes.append((nid, extract_tables(inputs, known_tables)))
        style_derivation.append(nid)

    def link_via_tables(node_id: str, matched: set[str]) -> None:
        if matched:
            for t in sorted(matched):
                out.append(f'  {safe_id("tbl", t)} --> {node_id}')
        elif seen_tables:
            out.append(f'  {safe_id("tbl", seen_tables[0])} --> {node_id}')

    for nid, matched in consumer_nodes:
        link_via_tables(nid, matched)
    for nid, matched in derivation_nodes:
        link_via_tables(nid, matched)

    # UI surfaces — dedupe by page name, but keep insertion order.
    ui_nodes: list[str] = []
    seen_pages: set[str] = set()
    for i, u in enumerate(rec.get("ui_surfaces") or []):
        if not isinstance(u, dict):
            continue
        page = u.get("page")
        if not page or not isinstance(page, str):
            continue
        page = page.strip()
        if page in seen_pages:
            continue
        seen_pages.add(page)
        nid = safe_id(f"ui{i}", page)
        out.append(f'  {nid}{{{{"{escape_label(page, 60)}"}}}}')
        ui_nodes.append(nid)
        style_ui.append(nid)

    feed_nodes = [nid for nid, _ in consumer_nodes] + [nid for nid, _ in derivation_nodes]
    if not feed_nodes:
        # No explicit consumer/derivation — write tables feed UI directly.
        for ui_nid in ui_nodes:
            for t in seen_tables:
                out.append(f'  {safe_id("tbl", t)} --> {ui_nid}')
    else:
        for ui_nid in ui_nodes:
            for fn in feed_nodes:
                out.append(f"  {fn} --> {ui_nid}")

    # External effects — circles. Hung off the first write table (or origin
    # if there are no writes). Skip prose-only no-op placeholders. Cap at 6
    # to keep diagrams legible; prose stays in the YAML.
    effect_count = 0
    seen_effect_tokens: set[str] = set()
    for i, e in enumerate(rec.get("external_effects") or []):
        if not isinstance(e, str) or is_noop_effect(e):
            continue
        if effect_count >= 6:
            break
        token = extract_external_token(e, i)
        if token in seen_effect_tokens:
            token = f"{token}_{i}"
        seen_effect_tokens.add(token)
        nid = safe_id(f"ex{i}", token)
        out.append(f'  {nid}(("{escape_label(token, 40)}"))')
        anchor = safe_id("tbl", seen_tables[0]) if seen_tables else "origin"
        out.append(f"  {anchor} -.-> {nid}")
        style_effect.append(nid)
        effect_count += 1

    # Styles. Mermaid classDef + class assignments.
    out.append("")
    out.append("  classDef origin fill:#fff7e6,stroke:#cc8400,stroke-width:1px;")
    out.append("  classDef table fill:#e6f0ff,stroke:#2952cc,stroke-width:1px;")
    out.append("  classDef consumer fill:#f4f4f4,stroke:#444,stroke-width:1px;")
    out.append("  classDef derivation fill:#eef9e6,stroke:#3d7a1f,stroke-width:1px;")
    out.append("  classDef ui fill:#fde6f0,stroke:#a5226f,stroke-width:1px;")
    out.append("  classDef effect fill:#f6e6ff,stroke:#5e2a82,stroke-width:1px;")

    def emit_class(nodes: list[str], cls: str) -> None:
        if nodes:
            out.append(f"  class {','.join(nodes)} {cls};")

    emit_class(style_origin, "origin")
    emit_class(style_table, "table")
    emit_class(style_consumer, "consumer")
    emit_class(style_derivation, "derivation")
    emit_class(style_ui, "ui")
    emit_class(style_effect, "effect")

    return "\n".join(out) + "\n"


def gen_overview(records: list[dict]) -> str:
    """Class super-nodes → top tables → top UI surfaces. One arrow per
    dominant relationship, not per event.
    """
    by_class: dict[str, list[str]] = defaultdict(list)
    writes_by_class: dict[str, Counter] = defaultdict(Counter)
    reads_by_class: dict[str, Counter] = defaultdict(Counter)
    ui_by_class: dict[str, Counter] = defaultdict(Counter)
    table_to_ui: Counter = Counter()
    table_writers: Counter = Counter()
    table_to_ui_pairs: Counter = Counter()  # (table, ui_page)

    all_tables: set[str] = set()
    for rec in records:
        klass = rec.get("class") or "?"
        eid = rec.get("event_id", "?")
        by_class[klass].append(eid)

        rec_write_tables: set[str] = set()
        for w in rec.get("write_signature") or []:
            if not isinstance(w, dict):
                continue
            t = w.get("table")
            if t and isinstance(t, str):
                rec_write_tables.add(t)
                all_tables.add(t)
        # Sort set iterations everywhere — Counter.most_common() breaks
        # ties by insertion order, and PYTHONHASHSEED randomizes set
        # iteration order per process, which makes the overview flicker
        # between runs (caught by the freshness check).
        for t in sorted(rec_write_tables):
            writes_by_class[klass][t] += 1
            table_writers[t] += 1

        ui_pages_in_record: set[str] = set()
        for u in rec.get("ui_surfaces") or []:
            if not isinstance(u, dict):
                continue
            p = u.get("page")
            if p and isinstance(p, str):
                ui_pages_in_record.add(p.strip())
        for p in sorted(ui_pages_in_record):
            ui_by_class[klass][p] += 1

        # Direct consumer / derivation reads (any matched table)
        rec_read_tables: set[str] = set()
        for dc in rec.get("direct_consumers") or []:
            if not isinstance(dc, dict):
                continue
            for s in coerce_list(dc.get("reads")):
                if isinstance(s, str):
                    m = TABLE_COL_RE.match(s) or BARE_TABLE_RE.match(s)
                    if m:
                        rec_read_tables.add(m.group(1))
        for d in rec.get("derivations") or []:
            if not isinstance(d, dict):
                continue
            for s in coerce_list(d.get("inputs")):
                if isinstance(s, str):
                    m = TABLE_COL_RE.match(s) or BARE_TABLE_RE.match(s)
                    if m:
                        rec_read_tables.add(m.group(1))
        for t in sorted(rec_read_tables):
            reads_by_class[klass][t] += 1

        # Tally table → UI by co-occurrence in this record (write OR read).
        for t in sorted(rec_write_tables | rec_read_tables):
            for p in sorted(ui_pages_in_record):
                table_to_ui_pairs[(t, p)] += 1
                table_to_ui[t] += 1

    # Pick top 5 tables by combined activity (writes + reads), but only
    # tables that have at least one writer — read-only join targets like
    # `accounts` would otherwise show up as "written by 0" which is
    # confusing in a diagram about write/read flow.
    table_activity: Counter = Counter()
    for c in writes_by_class.values():
        table_activity.update(c)
    for c in reads_by_class.values():
        table_activity.update(c)
    # Sort by activity desc, then table name asc — explicit tiebreak so
    # the result is stable regardless of insertion order.
    top_tables = [
        t for t, _ in sorted(
            table_activity.items(), key=lambda kv: (-kv[1], kv[0])
        ) if table_writers.get(t, 0) > 0
    ][:5]

    # Pick top 5 UI surfaces by total activity (page name as tiebreak).
    ui_activity: Counter = Counter()
    for c in ui_by_class.values():
        ui_activity.update(c)
    top_ui = [p for p, _ in sorted(
        ui_activity.items(), key=lambda kv: (-kv[1], kv[0])
    )][:5]

    out: list[str] = []
    out.append("%% Auto-generated by build_diagrams.py — do not edit by hand.")
    out.append("%% Sentry Finance — Data Lineage Overview (Phase 4)")
    out.append("%% Four event classes → dominant write tables → top UI surfaces.")
    out.append("graph LR")

    # Subgraphs per class with event counts. Show a representative sample.
    class_node_ids: dict[str, str] = {}
    for klass in VALID_CLASSES:
        events = by_class.get(klass) or []
        if not events:
            continue
        nid = safe_id("cls", klass)
        class_node_ids[klass] = nid
        sample = ", ".join(sorted(events)[:3])
        more = f" (+{len(events) - 3} more)" if len(events) > 3 else ""
        out.append(f'  subgraph sg_{nid}["{klass}  ({len(events)})"]')
        out.append(f'    {nid}["{escape_label(sample + more, 90)}"]')
        out.append("  end")

    # Table nodes
    for t in top_tables:
        nid = safe_id("tbl", t)
        writers = table_writers.get(t, 0)
        out.append(f'  {nid}[("{escape_label(t)}<br/>(written by {writers})")]')

    # Class → table edges: one per top table per class, only when that
    # class is a dominant writer (top-2 contribution from this class).
    for klass, cnid in class_node_ids.items():
        class_top = [
            t for t, _ in sorted(
                writes_by_class[klass].items(), key=lambda kv: (-kv[1], kv[0])
            )
        ][:2]
        for t in class_top:
            if t not in top_tables:
                continue
            out.append(f"  {cnid} --> {safe_id('tbl', t)}")
        # If a class has no overlap with top_tables, draw to its single
        # most-written table even if it isn't in the global top-5 — keeps
        # the overview honest about classes whose data lives off-spine.
        if not any(t in top_tables for t in class_top) and class_top:
            t = class_top[0]
            tnid = safe_id("tbl", t)
            writers = table_writers.get(t, 0)
            out.append(f'  {tnid}[("{escape_label(t)}<br/>(written by {writers})")]')
            out.append(f"  {cnid} --> {tnid}")

    # UI nodes
    for p in top_ui:
        nid = safe_id("ui", p)
        out.append(f'  {nid}{{{{"{escape_label(p, 60)}"}}}}')

    # Table → UI edges: top 2 UI surfaces per top table. Sort by count
    # desc, page name asc — explicit tiebreak.
    for t in top_tables:
        pairs_for_t = [(p, n) for (tt, p), n in table_to_ui_pairs.items() if tt == t]
        pairs_for_t.sort(key=lambda x: (-x[1], x[0]))
        for p, _ in pairs_for_t[:2]:
            if p in top_ui:
                out.append(f"  {safe_id('tbl', t)} --> {safe_id('ui', p)}")

    # Styles
    out.append("")
    out.append("  classDef cls fill:#fff7e6,stroke:#cc8400,stroke-width:1px;")
    out.append("  classDef table fill:#e6f0ff,stroke:#2952cc,stroke-width:1px;")
    out.append("  classDef ui fill:#fde6f0,stroke:#a5226f,stroke-width:1px;")
    if class_node_ids:
        out.append(f"  class {','.join(class_node_ids.values())} cls;")
    if top_tables:
        out.append(f"  class {','.join(safe_id('tbl', t) for t in top_tables)} table;")
    if top_ui:
        out.append(f"  class {','.join(safe_id('ui', p) for p in top_ui)} ui;")

    return "\n".join(out) + "\n"


def main() -> int:
    DIAG_DIR.mkdir(exist_ok=True)
    written = 0
    skipped: list[str] = []
    records: list[dict] = []

    for path in sorted(LINEAGE_DIR.glob("*.yaml")):
        if path.name == "README.md":
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                rec = yaml.safe_load(f)
        except yaml.YAMLError as e:
            skipped.append(f"{path.name}: YAML parse error — {e}")
            continue
        if not isinstance(rec, dict):
            skipped.append(f"{path.name}: top-level not a mapping")
            continue
        records.append(rec)
        eid = rec.get("event_id") or path.stem
        diagram = gen_event_diagram(rec)
        out_path = DIAG_DIR / f"{eid}.mmd"
        with out_path.open("w", encoding="utf-8") as f:
            f.write(diagram)
        written += 1

    overview = gen_overview(records)
    with (DIAG_DIR / "_overview.mmd").open("w", encoding="utf-8") as f:
        f.write(overview)

    print(f"Wrote {written} per-event diagrams + 1 overview to {DIAG_DIR}/.")
    if skipped:
        print("Skipped:")
        for s in skipped:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
