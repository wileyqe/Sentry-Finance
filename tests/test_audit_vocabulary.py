from dal.category_classifications import (
    ALL_EXCL_FROM_SPEND,
    INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC,
)
from scripts import audit_number_trust
from scripts.generate_number_trust_oracle_vocabulary import (
    check_vocabulary,
    write_vocabulary,
)
from scripts.number_trust_vocabulary import build_oracle_vocabulary


def test_number_trust_audit_uses_canonical_category_sets():
    assert audit_number_trust.ALL_EXCL_FROM_SPEND == ALL_EXCL_FROM_SPEND
    assert audit_number_trust.INCOME_CATEGORIES == INCOME_CATEGORIES
    assert audit_number_trust.INCOME_EXCL_FROM_INC == INCOME_EXCL_FROM_INC


def test_number_trust_oracle_vocabulary_matches_canonical_category_sets():
    import json

    vocab = json.loads(audit_number_trust.ORACLE_VOCABULARY_PATH.read_text(encoding="utf-8"))
    assert vocab == build_oracle_vocabulary()


def test_oracle_vocabulary_generator_writes_checkable_payload(tmp_path):
    output = tmp_path / "oracle-vocabulary.json"

    assert not check_vocabulary(output)
    write_vocabulary(output)

    assert check_vocabulary(output)


def test_number_trust_registry_declares_owner_view_contexts():
    registry = audit_number_trust._load_registry()
    assert audit_number_trust._registry_diffs(registry) == []

    state_ids = {state["id"] for state in audit_number_trust._registry_view_states(registry)}
    assert state_ids == {"household", "owner.quintin", "owner.amy"}

    contexts = audit_number_trust._registry_value_contexts(registry)
    audited_contexts = audit_number_trust._registry_value_contexts(
        registry,
        audit_stage="api_oracle",
    )
    pending_contexts = audit_number_trust._registry_value_contexts(
        registry,
        audit_stage="registered_pending",
    )
    value_ids = [
        value["id"]
        for surface in registry["surfaces"]
        for value in surface["values"]
    ]
    assert len(contexts) == len(value_ids) * 3
    assert len(audited_contexts) == len(contexts)
    assert len(audited_contexts) == 264
    assert pending_contexts == []

    pages = {surface["page"] for surface in registry["surfaces"]}
    assert {"Dashboard", "Transactions", "Cash Flow", "Reports", "Accounts", "Budgets"} <= pages

    registered_check_ids = audit_number_trust._registry_check_ids(registry)

    for surface in registry["surfaces"]:
        assert surface["route"].startswith("/")
        for value in surface["values"]:
            assert value["audit_stage"] in audit_number_trust.REGISTRY_AUDIT_STAGES
            if value["audit_stage"] == "api_oracle":
                assert value["check_id"] in registered_check_ids
            assert value["formatter"]
            assert isinstance(value["selector"], str)
            assert value["selector"]
