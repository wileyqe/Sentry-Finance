import pytest

from scripts.number_trust_registry_schema import load_registry, validate_registry_schema


def _registry_with_value(value: dict) -> dict:
    return {
        "version": 2,
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
                "values": [value],
            }
        ],
    }


def _api_oracle_value(**overrides) -> dict:
    value = {
        "id": "test.value",
        "label": "Test value",
        "api": "/api/test",
        "oracle": "raw_test_value",
        "check_id": "test.value",
        "formatter": "currency",
        "display_precision": 0.01,
        "empty_state": None,
        "owner_scope": "owner_aware",
        "selector": "[data-testid='test-value']",
        "audit_stage": "api_oracle",
        "view_states": ["household"],
    }
    value.update(overrides)
    return value


def _registered_pending_value(**overrides) -> dict:
    value = {
        "id": "test.pending",
        "label": "Pending test value",
        "formatter": "label",
        "display_precision": 1,
        "empty_state": "no_data",
        "owner_scope": "household_only",
        "audit_stage": "registered_pending",
        "pending_since": "2026-05-06",
        "view_states": ["household"],
    }
    value.update(overrides)
    return value


def _diff_ids(registry: dict) -> set[str]:
    return {diff["id"] for diff in validate_registry_schema(registry)}


def test_validator_passes_real_backfilled_registry():
    assert validate_registry_schema(load_registry()) == []


def test_api_oracle_requires_selector():
    value = _api_oracle_value()
    value.pop("selector")

    assert "registry.test.value.selector" in _diff_ids(_registry_with_value(value))


def test_registered_pending_requires_pending_since():
    value = _registered_pending_value()
    value.pop("pending_since")

    assert "registry.test.pending.pending_since" in _diff_ids(_registry_with_value(value))


def test_api_oracle_forbids_pending_since():
    registry = _registry_with_value(_api_oracle_value(pending_since="2026-05-06"))

    assert "registry.test.value.pending_since" in _diff_ids(registry)


@pytest.mark.parametrize(
    "field",
    ["display_precision", "empty_state", "owner_scope"],
)
def test_required_declarative_fields_are_required(field):
    value = _api_oracle_value()
    value.pop(field)

    assert f"registry.test.value.{field}" in _diff_ids(_registry_with_value(value))


@pytest.mark.parametrize(
    ("field", "actual"),
    [
        ("owner_scope", "owner-ish"),
        ("empty_state", "blank"),
    ],
)
def test_unknown_schema_enum_values_fail(field, actual):
    registry = _registry_with_value(_api_oracle_value(**{field: actual}))

    assert f"registry.test.value.{field}" in _diff_ids(registry)


def test_minimal_registered_pending_value_does_not_require_oracle_shape():
    registry = _registry_with_value(_registered_pending_value())

    assert validate_registry_schema(registry) == []
