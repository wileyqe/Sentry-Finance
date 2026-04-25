"""
Re-export facade for the dal.reports package.

Originally a single module; split for maintainability. Public API is
preserved — callers can still ``from dal.reports import X``.
"""

from .accountability import (
    _home_improvement_capex_in_window,
    _net_worth_at_date,
    _to_cents,
    _user_contributions_in_window,
    get_accountability,
)
from .cash_flow_report import (
    get_cash_flow_report,
)
from .csv_export import (
    export_transactions_csv,
)
from .flow import (
    _classify_transfer,
    _compute_bucket_totals,
    _compute_bypass_pseudo_flows,
    _compute_reinvestment_flows,
    get_flow_data,
)
from .merchant import (
    get_merchant_flow_data,
    get_merchant_list,
)
from .net_worth import (
    get_net_worth_history,
)
from .spending import (
    get_category_trend,
    get_period_summary,
    get_spending_by_category,
    get_spending_comparison,
)

__all__ = [
    "export_transactions_csv",
    "get_accountability",
    "get_cash_flow_report",
    "get_category_trend",
    "get_flow_data",
    "get_merchant_flow_data",
    "get_merchant_list",
    "get_net_worth_history",
    "get_period_summary",
    "get_spending_by_category",
    "get_spending_comparison",
]
