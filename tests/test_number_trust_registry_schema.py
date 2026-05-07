import pytest

from scripts.number_trust_registry_schema import load_registry, validate_registry_schema


def _registry_with_value(value: dict, *, surface_id: str = "test.surface") -> dict:
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
                "id": surface_id,
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


def _diff_by_id(registry: dict, diff_id: str) -> dict:
    return next(
        diff for diff in validate_registry_schema(registry) if diff["id"] == diff_id
    )


def test_validator_passes_real_backfilled_registry():
    assert validate_registry_schema(load_registry()) == []


def test_api_oracle_requires_selector():
    value = _api_oracle_value()
    value.pop("selector")

    assert "registry.test.value.selector" in _diff_ids(_registry_with_value(value))


def test_default_buildable_api_oracle_requires_concrete_selector():
    value = _api_oracle_value()
    value.pop("selector")

    assert "registry.test.value.default_dom_builder.selector" in _diff_ids(
        _registry_with_value(value, surface_id="dashboard.kpis")
    )


def test_named_dom_builder_allows_custom_selector_shape():
    value = _api_oracle_value(
        selector="[data-testid^='test-value-'], [data-testid='test-value-empty']",
        dom_builder="credit_score_multiselect",
    )

    assert validate_registry_schema(
        _registry_with_value(value, surface_id="dashboard.kpis")
    ) == []


def test_default_buildable_api_oracle_passes_with_complete_shape():
    registry = _registry_with_value(_api_oracle_value(), surface_id="dashboard.kpis")

    assert validate_registry_schema(registry) == []


def test_registered_pending_requires_pending_since():
    value = _registered_pending_value()
    value.pop("pending_since")

    assert "registry.test.pending.pending_since" in _diff_ids(_registry_with_value(value))


def test_api_oracle_forbids_pending_since():
    registry = _registry_with_value(_api_oracle_value(pending_since="2026-05-06"))

    assert "registry.test.value.pending_since" in _diff_ids(registry)


def test_registered_pending_older_than_ttl_fails(monkeypatch):
    monkeypatch.setenv("SENTRY_REFERENCE_DATE", "2026-05-06")
    registry = _registry_with_value(_registered_pending_value(pending_since="2026-03-06"))

    ttl_diff = _diff_by_id(registry, "registry.test.pending.pending_since.ttl")

    assert "test.surface/test.pending" in ttl_diff["expected"]
    assert "test.surface/test.pending" in ttl_diff["actual"]
    assert "1 day overdue" in ttl_diff["actual"]
    assert (
        "promote to `api_oracle` with full Q3 default-buildable shape"
        in ttl_diff["expected"]
    )
    assert "remove the entry" in ttl_diff["expected"]


def test_registered_pending_within_ttl_passes(monkeypatch):
    monkeypatch.setenv("SENTRY_REFERENCE_DATE", "2026-05-06")
    registry = _registry_with_value(_registered_pending_value(pending_since="2026-03-08"))

    assert validate_registry_schema(registry) == []


def test_api_oracle_pending_since_does_not_trip_ttl(monkeypatch):
    monkeypatch.setenv("SENTRY_REFERENCE_DATE", "2026-05-06")
    registry = _registry_with_value(_api_oracle_value(pending_since="2020-01-01"))
    diff_ids = _diff_ids(registry)

    assert diff_ids == {"registry.test.value.pending_since"}
    assert "registry.test.value.pending_since.ttl" not in diff_ids


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
