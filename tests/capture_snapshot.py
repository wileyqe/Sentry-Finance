"""Capture a golden snapshot of KPIs and totals for regression testing.

Run this ONCE on the working monolith to create tests/golden_snapshot.json.
Smoke tests compare against this snapshot after each refactor phase.
"""
import json, sys, os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing dashboard triggers data load (module-level side effect)
import dashboard as d

# Full date range
month_range = [0, len(d.months_available) - 1]
filtered, exp, inc = d.filter_data(month_range, "ALL", "ALL")

snapshot = {
    "total_transactions": len(d.ALL),
    "total_filtered": len(filtered),
    "total_income": round(float(inc["signed_amount"].sum()), 2),
    "total_expenses": round(float(exp["abs_amount"].sum()), 2),
    "net_cash_flow": round(float(inc["signed_amount"].sum() - exp["abs_amount"].sum()), 2),
    "num_months": len(filtered["month"].unique()),
    "num_institutions": int(d.ALL["institution"].nunique()),
    "num_categories": int(d.ALL["category"].nunique()),
    "columns": sorted(d.ALL.columns.tolist()),
    "expense_categories": sorted(exp["category"].dropna().unique().tolist()),
}

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_snapshot.json")
with open(out_path, "w") as f:
    json.dump(snapshot, f, indent=2)

print(f"\n📸 Golden Snapshot saved to {out_path}")
for k, v in snapshot.items():
    if isinstance(v, list) and len(v) > 5:
        print(f"  {k}: [{len(v)} items]")
    else:
        print(f"  {k}: {v}")
