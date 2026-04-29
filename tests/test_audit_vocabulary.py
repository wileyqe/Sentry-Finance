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
