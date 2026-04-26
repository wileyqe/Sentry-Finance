"""
build_inverse_index.py — Phase 3 generator for docs/data-lineage/inverse-index.yaml.

Walks lineage/*.yaml and builds two inverse maps:
  - by_table_column: who writes / who reads each table.column
  - by_ui_surface:   which events feed each rendered surface

Run from docs/data-lineage/:
  python build_inverse_index.py

Re-run any time a lineage record changes; the file is meant to be regenerated,
not hand-edited. Hand-written prose belongs in `notes` of the per-event YAML.

Parsing rules:
  * `write_signature[].columns_set[]` items are clean column tokens; we pair
    each with its sibling `table` to form table.column entries.
  * `direct_consumers[].reads[]` and `derivations[].inputs[]` items are
    free-form strings. We extract `table.column` via a regex that anchors on
    the first `<snake_case>.<col_or_*>` token; trailing parenthetical
    annotations are dropped. Items that don't match (e.g. prose like
    "transactions on cash accounts (debit categories)") are recorded under
    `unparsed_reads` for follow-up rather than silently dropped.
  * `ui_surfaces[].page` keys the by_ui_surface index; we collect components
    + via_endpoints (the `via:` line) per page. Endpoints are extracted with
    `(GET|POST|PATCH|PUT|DELETE) /api/...` to keep the index clean of prose.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
LINEAGE_DIR = ROOT / "lineage"
EVENTS_YAML = ROOT / "events.yaml"
OUT = ROOT / "inverse-index.yaml"

TABLE_COL_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\.([a-zA-Z_*][a-zA-Z0-9_]*)")
ENDPOINT_RE = re.compile(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/[A-Za-z0-9/_{}\-]+)")
SSE_RE = re.compile(r"\bSSE\s+['\"]?([a-z_][a-z_0-9]*)['\"]?", re.IGNORECASE)


def extract_table_col(s: str) -> tuple[str, str] | None:
    """Pull the first `table.column` token off a free-form reads/inputs string."""
    if not isinstance(s, str):
        return None
    m = TABLE_COL_RE.match(s)
    if not m:
        return None
    return m.group(1), m.group(2)


def coerce_list(value) -> list:
    """Some lineage YAMLs put a bare string under `reads:` / `inputs:` instead
    of a list. Iterating a string yields characters, which generated 600+
    spurious unparsed entries. Treat a non-list scalar as a single-item list.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_event_ids_from_events_yaml() -> set[str]:
    """events.yaml has unquoted folded scalars with embedded colons that break
    strict YAML parsers, so we extract `- id: <name>` lines via regex. The
    file's `not_modeled`, `synthetic_gaps`, and `lineage_notes` sections also
    use `id:` keys but are deliberately not phase-2 records — we filter them
    out by tracking which top-level class section we're inside.
    """
    valid_classes = {"user_action", "external_force", "system_derived",
                     "system_scheduled", "live_only"}
    section_re = re.compile(r"^([a-z_]+):\s*$")
    id_re = re.compile(r"^\s*-\s*id:\s*([a-zA-Z0-9_]+)\s*$")
    ids: set[str] = set()
    current_section: str | None = None
    with EVENTS_YAML.open("r", encoding="utf-8") as f:
        for line in f:
            sm = section_re.match(line)
            if sm and not line.startswith(" "):
                current_section = sm.group(1)
                continue
            if current_section in valid_classes:
                im = id_re.match(line)
                if im:
                    ids.add(im.group(1))
    return ids


def iter_lineage_files() -> list[Path]:
    return sorted(p for p in LINEAGE_DIR.glob("*.yaml") if p.name != "README.md")


BARE_TABLE_RE = re.compile(r"^\s*([a-z][a-z0-9_]+)(?=\s|,|\(|$)")


def main() -> int:
    by_tc_writes: dict[str, set[str]] = defaultdict(set)
    by_tc_reads: dict[str, set[str]] = defaultdict(set)
    by_ui: dict[str, dict] = {}
    unparsed_reads_raw: list[dict] = []
    seen_event_ids: set[str] = set()
    file_count = 0
    skipped: list[str] = []

    for path in iter_lineage_files():
        with path.open("r", encoding="utf-8") as f:
            try:
                rec = yaml.safe_load(f)
            except yaml.YAMLError as e:
                skipped.append(f"{path.name}: YAML parse error — {e}")
                continue
        if not isinstance(rec, dict):
            skipped.append(f"{path.name}: top-level not a mapping")
            continue
        eid = rec.get("event_id") or path.stem
        seen_event_ids.add(eid)
        file_count += 1

        # --- writes ---
        for w in (rec.get("write_signature") or []):
            if not isinstance(w, dict):
                continue
            table = w.get("table")
            cols = w.get("columns_set") or []
            if not table or not isinstance(cols, list):
                continue
            for c in cols:
                if not isinstance(c, str):
                    continue
                # Strip trailing comment/annotation; columns_set entries are
                # usually clean tokens, but a few contain inline prose.
                col = c.split()[0].strip().rstrip(",")
                if not col:
                    continue
                by_tc_writes[f"{table}.{col}"].add(eid)

        # --- direct reads ---
        for dc in (rec.get("direct_consumers") or []):
            if not isinstance(dc, dict):
                continue
            for r in coerce_list(dc.get("reads")):
                tc = extract_table_col(r) if isinstance(r, str) else None
                if tc:
                    by_tc_reads[f"{tc[0]}.{tc[1]}"].add(eid)
                else:
                    unparsed_reads_raw.append({
                        "event": eid, "section": "direct_consumers",
                        "value": r if isinstance(r, str) else repr(r),
                    })

        # --- derivation inputs ---
        for d in (rec.get("derivations") or []):
            if not isinstance(d, dict):
                continue
            for r in coerce_list(d.get("inputs")):
                tc = extract_table_col(r) if isinstance(r, str) else None
                if tc:
                    by_tc_reads[f"{tc[0]}.{tc[1]}"].add(eid)
                else:
                    unparsed_reads_raw.append({
                        "event": eid, "section": "derivations",
                        "value": r if isinstance(r, str) else repr(r),
                    })

        # --- ui surfaces ---
        for u in (rec.get("ui_surfaces") or []):
            if not isinstance(u, dict):
                continue
            page = u.get("page")
            if not page:
                continue
            page = str(page).strip()
            entry = by_ui.setdefault(page, {
                "fed_by_events": set(),
                "components": set(),
                "via_endpoints": set(),
            })
            entry["fed_by_events"].add(eid)
            comp = u.get("component")
            if isinstance(comp, str) and comp.strip():
                entry["components"].add(comp.strip())
            via = u.get("via")
            if isinstance(via, str):
                for verb, path_ in ENDPOINT_RE.findall(via):
                    entry["via_endpoints"].add(f"{verb} {path_}")

    # --- second pass: resolve bare-table references like "transactions on
    # cash accounts" against the known set of tables seen in write_signature.
    # Anything that resolves becomes a `<table>.*` read; anything that
    # doesn't stays in unparsed_reads_for_followup as prose.
    known_tables: set[str] = {k.split(".", 1)[0] for k in by_tc_writes}
    unparsed_reads: list[dict] = []
    for entry in unparsed_reads_raw:
        v = entry["value"]
        m = BARE_TABLE_RE.match(v) if isinstance(v, str) else None
        if m and m.group(1) in known_tables:
            by_tc_reads[f"{m.group(1)}.*"].add(entry["event"])
        else:
            unparsed_reads.append(entry)

    # --- round-trip validation against events.yaml ---
    declared = load_event_ids_from_events_yaml()
    missing_records = sorted(declared - seen_event_ids)
    extra_records = sorted(seen_event_ids - declared)

    # --- shape final document ---
    def _sorted(d: dict[str, set[str]]) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sorted(d.items())}

    by_tc_out: dict[str, dict] = {}
    all_keys = sorted(set(by_tc_writes) | set(by_tc_reads))
    for k in all_keys:
        entry: dict = {}
        if k in by_tc_writes:
            entry["written_by"] = sorted(by_tc_writes[k])
        if k in by_tc_reads:
            entry["read_by"] = sorted(by_tc_reads[k])
        by_tc_out[k] = entry

    by_ui_out: dict[str, dict] = {}
    for page in sorted(by_ui):
        e = by_ui[page]
        out_entry: dict = {"fed_by_events": sorted(e["fed_by_events"])}
        if e["components"]:
            out_entry["components"] = sorted(e["components"])
        if e["via_endpoints"]:
            out_entry["via_endpoints"] = sorted(e["via_endpoints"])
        by_ui_out[page] = out_entry

    doc = {
        "version": 1,
        "phase": 3,
        "status": "generated",
        "generator": "build_inverse_index.py",
        "regenerate": "Run `python build_inverse_index.py` from docs/data-lineage/ after editing any lineage/*.yaml.",
        "stats": {
            "lineage_files_walked": file_count,
            "unique_table_columns": len(by_tc_out),
            "unique_ui_surfaces": len(by_ui_out),
            "events_declared_in_events_yaml": len(declared),
            "events_seen_in_lineage": len(seen_event_ids),
            "events_missing_records": missing_records,
            "events_extra_records_not_in_events_yaml": extra_records,
            "unparsed_reads_count": len(unparsed_reads),
            "files_skipped": skipped,
        },
        "by_table_column": by_tc_out,
        "by_ui_surface": by_ui_out,
        "unparsed_reads_for_followup": unparsed_reads,
    }

    header = (
        "# inverse-index.yaml — Phase 3 deliverable. GENERATED.\n"
        "#\n"
        "# Do NOT hand-edit. Regenerate with `python build_inverse_index.py`\n"
        "# from this directory after any lineage/*.yaml change.\n"
        "#\n"
        "# Top-level shape:\n"
        "#   stats           — counts + round-trip diagnostics\n"
        "#   by_table_column — every <table>.<column> referenced anywhere,\n"
        "#                     with `written_by` and `read_by` event lists\n"
        "#   by_ui_surface   — every UI page named in any lineage/*.yaml,\n"
        "#                     with the events that feed it, the components\n"
        "#                     that render it, and the API endpoints used\n"
        "#   unparsed_reads_for_followup — direct_consumers.reads /\n"
        "#                     derivations.inputs entries that didn't match\n"
        "#                     the `<table>.<column>` extractor; review and\n"
        "#                     either reword in the source YAML or accept as\n"
        "#                     prose-only references.\n\n"
    )

    with OUT.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False,
                       allow_unicode=True, width=100)

    # --- console summary ---
    print(f"Walked {file_count} lineage files.")
    print(f"Unique table.column entries: {len(by_tc_out)}")
    print(f"Unique UI surfaces: {len(by_ui_out)}")
    print(f"Events declared in events.yaml: {len(declared)}")
    print(f"Events with lineage records:    {len(seen_event_ids)}")
    if missing_records:
        print(f"MISSING records (declared but no YAML): {missing_records}")
    if extra_records:
        print(f"EXTRA records (YAML but not in events.yaml): {extra_records}")
    if skipped:
        print("Skipped files:")
        for s in skipped:
            print(f"  {s}")
    print(f"Unparsed reads/inputs: {len(unparsed_reads)} (see unparsed_reads_for_followup in output)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
