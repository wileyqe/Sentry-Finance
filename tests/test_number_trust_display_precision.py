import json
import subprocess
from pathlib import Path

import pytest

from scripts.audit_number_trust import (
    _DisplayPrecisionIndex,
    _check_partition,
    _compare,
    _round_to_display_precision,
)


ROOT = Path(__file__).resolve().parent.parent


def _registry(display_precision: float | int) -> dict:
    return {
        "view_states": [
            {
                "id": "household",
                "view": "household",
                "owner_id": None,
                "expected_state": "populated",
            }
        ],
        "surfaces": [
            {
                "id": "test.surface",
                "page": "Test",
                "route": "/test",
                "values": [
                    {
                        "id": "test.value",
                        "label": "Test value",
                        "api": "/api/test",
                        "oracle": "raw_test_value",
                        "check_id": "test.value",
                        "formatter": "number",
                        "display_precision": display_precision,
                        "empty_state": None,
                        "owner_scope": "owner_aware",
                        "selector": "[data-testid='test-value']",
                        "audit_stage": "api_oracle",
                        "view_states": ["household"],
                    }
                ],
            }
        ],
    }


def _compare_value(expected, actual, display_precision):
    diffs: list[dict] = []
    _compare(
        "test.value@household",
        expected,
        actual,
        diffs,
        display_precision_index=_DisplayPrecisionIndex(_registry(display_precision)),
    )
    return diffs


def test_full_precision_difference_passes_when_display_precision_matches():
    diffs = _compare_value(1234.5600001, 1234.5599999, 0.01)

    assert diffs == []


def test_display_precision_difference_fails_with_rounded_diff():
    diffs = _compare_value(1234.56, 1234.57, 0.01)

    assert diffs == [
        {
            "id": "test.value@household",
            "expected": 1234.56,
            "actual": 1234.57,
            "classification": "API/DAL logic bug",
            "display_precision": 0.01,
            "raw_expected": 1234.56,
            "raw_actual": 1234.57,
        }
    ]


@pytest.mark.parametrize(
    ("display_precision", "expected", "actual"),
    [
        (0.01, 12.3401, 12.3399),
        (0.1, 7.4401, 7.4399),
        (1, 719.4, 719.49),
        (100, 1234.4, 1234.49),
    ],
)
def test_supported_display_precisions_round_before_exact_compare(
    display_precision,
    expected,
    actual,
):
    assert _compare_value(expected, actual, display_precision) == []


def test_half_even_rounding_matches_documented_boundary():
    assert _round_to_display_precision(0.125, 0.01) == 0.12
    assert _round_to_display_precision(0.135, 0.01) == 0.14


def test_node_display_rounding_matches_python_half_even_boundary():
    proc = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import { roundToDisplayPrecision } from './scripts/number_trust_oracle.mjs';"
            "console.log(JSON.stringify(["
            "roundToDisplayPrecision(0.125, 0.01),"
            "roundToDisplayPrecision(0.135, 0.01)"
            "]));",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(proc.stdout) == [0.12, 0.14]


def test_partition_percent_check_uses_display_precision_exact_equality():
    diffs: list[dict] = []

    _check_partition(
        "cash_flow.current_month.income@household",
        [{"total": 1.0, "pct": 99.49}],
        1.0,
        diffs,
    )

    assert diffs == [
        {
            "id": "cash_flow.current_month.income@household.category_pct_sum",
            "expected": 100,
            "actual": 99.5,
            "classification": "invariant violation",
            "display_precision": 0.1,
            "raw_expected": 100,
            "raw_actual": 99.49,
        }
    ]
