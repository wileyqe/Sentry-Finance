"""Schema validation for the number-trust UI registry.

This module owns the declarative registry contract. The audit harness still
keeps its historical checks, but calls this validator so new metadata fields
fail in one place for both the CLI and proof gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from dal.clock import reference_date  # noqa: E402

REGISTRY_PATH = ROOT / "docs" / "audits" / "number-trust" / "ui-number-registry.yaml"
AUDIT_STAGES = {"api_oracle", "registered_pending"}
EMPTY_STATES = {None, "zero", "no_data"}
OWNER_SCOPES = {"household_only", "owner_aware", "per_owner"}
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PENDING_SINCE_TTL_DAYS = 60


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _diff(
    diff_id: str,
    expected: Any,
    actual: Any,
    *,
    classification: str = "lineage/docs drift",
) -> dict[str, Any]:
    return {
        "id": diff_id,
        "expected": expected,
        "actual": actual,
        "classification": classification,
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _missing(value: dict[str, Any], key: str) -> bool:
    return key not in value


def _validate_view_states(registry: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    diffs: list[dict[str, Any]] = []
    states = registry.get("view_states")
    if not isinstance(states, list):
        return [
            _diff("registry.view_states", "list of owner/view states", states)
        ], set()

    seen: set[str] = set()
    valid_state_ids: set[str] = set()
    for state in states:
        if not isinstance(state, dict):
            diffs.append(_diff("registry.view_states.item", "mapping", state))
            continue
        state_id = state.get("id")
        if not _has_non_empty_string(state_id):
            diffs.append(_diff("registry.view_states.id", "non-empty id", state))
            continue
        if state_id in seen:
            diffs.append(_diff(f"registry.view_states.{state_id}.unique", "unique id", "duplicate"))
        seen.add(state_id)
        valid_state_ids.add(state_id)
        if state.get("view") not in {"household", "owner"}:
            diffs.append(
                _diff(
                    f"registry.view_states.{state_id}.view",
                    "household or owner",
                    state.get("view"),
                )
            )
        if state.get("view") == "household" and state.get("owner_id") is not None:
            diffs.append(
                _diff(f"registry.view_states.{state_id}.owner_id", None, state.get("owner_id"))
            )
        if state.get("view") == "owner" and not state.get("owner_id"):
            diffs.append(
                _diff(
                    f"registry.view_states.{state_id}.owner_id",
                    "owner id",
                    state.get("owner_id"),
                )
            )
    return diffs, valid_state_ids


def _validate_display_precision(value_id: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    if _missing(value, "display_precision"):
        return [
            _diff(
                f"registry.{value_id}.display_precision",
                "numeric display precision",
                None,
                classification="formatter mismatch",
            )
        ]
    actual = value.get("display_precision")
    if not _is_number(actual) or actual <= 0:
        return [
            _diff(
                f"registry.{value_id}.display_precision",
                "positive number",
                actual,
                classification="formatter mismatch",
            )
        ]
    return []


def _validate_common_value_fields(
    value_id: str,
    value: dict[str, Any],
    valid_state_ids: set[str],
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for field, expected in [
        ("id", "non-empty value id"),
        ("label", "visible label"),
        ("formatter", "formatter contract"),
    ]:
        if not _has_non_empty_string(value.get(field)):
            diffs.append(
                _diff(
                    f"registry.{value_id}.{field}",
                    expected,
                    value.get(field),
                    classification="formatter mismatch" if field == "formatter" else "lineage/docs drift",
                )
            )

    diffs.extend(_validate_display_precision(value_id, value))

    if _missing(value, "empty_state"):
        diffs.append(_diff(f"registry.{value_id}.empty_state", sorted(v for v in EMPTY_STATES if v is not None) + [None], None))
    elif value.get("empty_state") not in EMPTY_STATES:
        diffs.append(
            _diff(
                f"registry.{value_id}.empty_state",
                sorted(v for v in EMPTY_STATES if v is not None) + [None],
                value.get("empty_state"),
            )
        )

    if _missing(value, "owner_scope"):
        diffs.append(_diff(f"registry.{value_id}.owner_scope", sorted(OWNER_SCOPES), None))
    elif value.get("owner_scope") not in OWNER_SCOPES:
        diffs.append(
            _diff(f"registry.{value_id}.owner_scope", sorted(OWNER_SCOPES), value.get("owner_scope"))
        )

    declared = value.get("view_states")
    if not declared:
        diffs.append(
            _diff(
                f"registry.{value_id}.view_states",
                "at least one explicit owner/view state",
                declared,
            )
        )
    elif not isinstance(declared, list):
        diffs.append(_diff(f"registry.{value_id}.view_states", "list", declared))
    else:
        unknown = [state_id for state_id in declared if state_id not in valid_state_ids]
        if unknown:
            diffs.append(
                _diff(
                    f"registry.{value_id}.view_states.known",
                    sorted(valid_state_ids),
                    unknown,
                )
            )
    return diffs


def _validate_pending_since(value_id: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    actual = value.get("pending_since")
    if _missing(value, "pending_since"):
        return [
            _diff(f"registry.{value_id}.pending_since", "YYYY-MM-DD", None)
        ]
    if not isinstance(actual, str) or not ISO_DATE_RE.match(actual):
        return [
            _diff(f"registry.{value_id}.pending_since", "YYYY-MM-DD", actual)
        ]
    try:
        date.fromisoformat(actual)
    except ValueError:
        return [
            _diff(f"registry.{value_id}.pending_since", "valid YYYY-MM-DD", actual)
        ]
    return []


def _format_days(days: int) -> str:
    unit = "day" if days == 1 else "days"
    return f"{days} {unit}"


def _validate_pending_since_ttl(
    surface_id: str,
    value_id: str,
    value: dict[str, Any],
) -> list[dict[str, Any]]:
    pending_date = date.fromisoformat(value["pending_since"])
    age_days = (reference_date() - pending_date).days
    if age_days <= PENDING_SINCE_TTL_DAYS:
        return []

    overdue_days = age_days - PENDING_SINCE_TTL_DAYS
    return [
        _diff(
            f"registry.{value_id}.pending_since.ttl",
            (
                f"{surface_id}/{value_id} pending <= {PENDING_SINCE_TTL_DAYS} days; "
                "when stale, promote to `api_oracle` with full Q3 "
                "default-buildable shape, or remove the entry"
            ),
            (
                f"{surface_id}/{value_id} is {_format_days(overdue_days)} overdue "
                f"({_format_days(age_days)} pending since {pending_date.isoformat()})"
            ),
        )
    ]


def validate_registry_schema(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return audit-shaped diffs for registry schema violations."""

    diffs, valid_state_ids = _validate_view_states(registry)
    surfaces = registry.get("surfaces")
    if not isinstance(surfaces, list):
        diffs.append(_diff("registry.surfaces", "list of surfaces", surfaces))
        return diffs

    seen_values: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, dict):
            diffs.append(_diff("registry.surface", "mapping", surface))
            continue
        surface_id = surface.get("id") or "<missing>"
        if not _has_non_empty_string(surface.get("id")):
            diffs.append(_diff(f"registry.{surface_id}.id", "non-empty surface id", surface.get("id")))
        if not _has_non_empty_string(surface.get("page")):
            diffs.append(_diff(f"registry.{surface_id}.page", "page name", surface.get("page")))
        if not _has_non_empty_string(surface.get("route")):
            diffs.append(_diff(f"registry.{surface_id}.route", "frontend route", surface.get("route")))
        values = surface.get("values")
        if not isinstance(values, list) or not values:
            diffs.append(_diff(f"registry.{surface_id}.values", "non-empty list", values))
            continue

        for value in values:
            if not isinstance(value, dict):
                diffs.append(_diff(f"registry.{surface_id}.value", "mapping", value))
                continue
            value_id = value.get("id") or "<missing>"
            if value_id in seen_values:
                diffs.append(_diff(f"registry.{value_id}.unique", "unique value id", "duplicate"))
            seen_values.add(value_id)

            diffs.extend(_validate_common_value_fields(value_id, value, valid_state_ids))

            stage = value.get("audit_stage")
            if stage not in AUDIT_STAGES:
                diffs.append(
                    _diff(f"registry.{value_id}.audit_stage", sorted(AUDIT_STAGES), stage)
                )
                continue

            if stage == "registered_pending":
                pending_since_diffs = _validate_pending_since(value_id, value)
                diffs.extend(pending_since_diffs)
                if not pending_since_diffs:
                    diffs.extend(
                        _validate_pending_since_ttl(surface_id, value_id, value)
                    )
                continue

            if "pending_since" in value:
                diffs.append(
                    _diff(
                        f"registry.{value_id}.pending_since",
                        "absent for api_oracle",
                        value.get("pending_since"),
                    )
                )
            for field, expected in [
                ("api", "API source path"),
                ("oracle", "Python oracle helper"),
                ("check_id", "audit check id for api_oracle value"),
                ("selector", "DOM selector or pending sentinel"),
            ]:
                if not _has_non_empty_string(value.get(field)):
                    diffs.append(_diff(f"registry.{value_id}.{field}", expected, value.get(field)))
            if "dom_builder" in value and not _has_non_empty_string(value.get("dom_builder")):
                diffs.append(
                    _diff(f"registry.{value_id}.dom_builder", "opaque builder name", value.get("dom_builder"))
                )
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the number-trust UI registry schema")
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="Path to ui-number-registry.yaml",
    )
    args = parser.parse_args()

    registry = load_registry(args.registry)
    diffs = validate_registry_schema(registry)
    report = {
        "registry": str(args.registry),
        "status": "fail" if diffs else "ok",
        "diff_count": len(diffs),
        "diffs": diffs,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
