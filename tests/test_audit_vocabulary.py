from dal.category_classifications import (
    ALL_EXCL_FROM_SPEND,
    INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC,
)
from scripts import audit_number_trust


def test_number_trust_audit_uses_canonical_category_sets():
    assert audit_number_trust.ALL_EXCL_FROM_SPEND == ALL_EXCL_FROM_SPEND
    assert audit_number_trust.INCOME_CATEGORIES == INCOME_CATEGORIES
    assert audit_number_trust.INCOME_EXCL_FROM_INC == INCOME_EXCL_FROM_INC


def test_number_trust_registry_declares_owner_view_contexts():
    registry = audit_number_trust._load_registry()
    assert audit_number_trust._registry_diffs(registry) == []

    state_ids = {state["id"] for state in audit_number_trust._registry_view_states(registry)}
    assert state_ids == {"household", "owner.quintin", "owner.amy"}

    contexts = audit_number_trust._registry_value_contexts(registry)
    value_ids = [
        value["id"]
        for surface in registry["surfaces"]
        for value in surface["values"]
    ]
    assert len(contexts) == len(value_ids) * 3
