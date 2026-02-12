"""Smoke tests for Project Antigravity dashboard.

These tests validate that the dashboard data pipeline produces
consistent results after refactoring. Run with:
    python -m pytest tests/test_smoke.py -v
"""
import json, os, sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_snapshot.json")


@pytest.fixture(scope="session")
def dashboard():
    """Import dashboard module (triggers data load)."""
    import dashboard as d
    return d


@pytest.fixture(scope="session")
def snapshot():
    """Load golden snapshot for comparison."""
    if not os.path.exists(SNAPSHOT_PATH):
        pytest.skip("Golden snapshot not found. Run: python tests/capture_snapshot.py")
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def full_range_data(dashboard):
    """filter_data with full month range, no institution/account filter."""
    month_range = [0, len(dashboard.months_available) - 1]
    return dashboard.filter_data(month_range, "ALL", "ALL")


# ─── Import Tests ────────────────────────────────────────────────────────────

class TestImport:
    def test_module_imports(self, dashboard):
        """Dashboard module imports without error."""
        assert dashboard is not None

    def test_all_dataframe_exists(self, dashboard):
        """Global ALL DataFrame is populated."""
        assert len(dashboard.ALL) > 0

    def test_all_has_required_columns(self, dashboard):
        """ALL DataFrame has all expected columns."""
        required = {"date", "description", "amount", "signed_amount",
                    "category", "institution", "account", "month", "week"}
        actual = set(dashboard.ALL.columns)
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"


# ─── Data Pipeline Tests ─────────────────────────────────────────────────────

class TestDataPipeline:
    def test_filter_data_returns_three(self, full_range_data):
        """filter_data returns (filtered, expenses, income) tuple."""
        assert len(full_range_data) == 3

    def test_transaction_count(self, dashboard, snapshot):
        """Total transaction count matches snapshot."""
        assert len(dashboard.ALL) == snapshot["total_transactions"]

    def test_income_total(self, full_range_data, snapshot):
        """Total income matches snapshot (within $0.01)."""
        _, _, inc = full_range_data
        actual = round(float(inc["signed_amount"].sum()), 2)
        assert abs(actual - snapshot["total_income"]) < 0.02, \
            f"Income: {actual} != {snapshot['total_income']}"

    def test_expense_total(self, full_range_data, snapshot):
        """Total expenses match snapshot (within $0.01)."""
        _, exp, _ = full_range_data
        actual = round(float(exp["abs_amount"].sum()), 2)
        assert abs(actual - snapshot["total_expenses"]) < 0.02, \
            f"Expenses: {actual} != {snapshot['total_expenses']}"

    def test_net_cash_flow(self, full_range_data, snapshot):
        """Net cash flow matches snapshot."""
        _, exp, inc = full_range_data
        actual = round(float(inc["signed_amount"].sum() - exp["abs_amount"].sum()), 2)
        assert abs(actual - snapshot["net_cash_flow"]) < 0.02

    def test_institution_count(self, dashboard, snapshot):
        """Number of institutions matches."""
        assert dashboard.ALL["institution"].nunique() == snapshot["num_institutions"]

    def test_columns_match(self, dashboard, snapshot):
        """DataFrame columns match snapshot."""
        actual = sorted(dashboard.ALL.columns.tolist())
        expected = snapshot["columns"]
        assert actual == expected, f"Column diff: {set(actual) ^ set(expected)}"


# ─── Filter Logic Tests ─────────────────────────────────────────────────────

class TestFilterLogic:
    def test_expenses_exclude_transfers(self, full_range_data):
        """Expenses should not include Transfers/Savings/CC Payments."""
        _, exp, _ = full_range_data
        excluded = {"Transfers", "Savings", "Credit Card Payments", "Credit Card Payment"}
        found = set(exp["category"].unique()) & excluded
        assert not found, f"Excluded categories in expenses: {found}"

    def test_income_exclude_transfers(self, full_range_data):
        """Income should not include Transfers/Savings/CC Payments."""
        _, _, inc = full_range_data
        excluded = {"Transfers", "Savings", "Credit Card Payments", "Credit Card Payment"}
        found = set(inc["category"].unique()) & excluded
        assert not found, f"Excluded categories in income: {found}"

    def test_expenses_all_negative(self, full_range_data):
        """All expense amounts should be from negative signed_amounts."""
        _, exp, _ = full_range_data
        assert (exp["signed_amount"] < 0).all()

    def test_income_all_positive(self, full_range_data):
        """All income amounts should be positive."""
        _, _, inc = full_range_data
        assert (inc["signed_amount"] > 0).all()
