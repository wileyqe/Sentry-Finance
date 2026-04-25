"""
Re-export facade for the dal.derived package.

Originally a single module; split for maintainability. Public API is
preserved — callers can still ``from dal.reports import X``.
"""

from .metrics import (
    _affirm_hysa_id,
    compute_dti_ratio,
    compute_emergency_fund_months,
    compute_interest_cost,
    compute_net_worth_velocity,
    get_summary_metrics,
)
from .recompute import (
    recompute_account_metrics,
    recompute_for_institution,
    recompute_interest_earned,
    recompute_net_worth,
)

__all__ = [
    "compute_dti_ratio",
    "compute_emergency_fund_months",
    "compute_interest_cost",
    "compute_net_worth_velocity",
    "get_summary_metrics",
    "recompute_account_metrics",
    "recompute_for_institution",
    "recompute_interest_earned",
    "recompute_net_worth",
]
