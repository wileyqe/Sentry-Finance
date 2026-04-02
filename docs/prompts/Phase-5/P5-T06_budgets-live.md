# P5-T06: Budgets Page Live Data

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `BudgetsPage.tsx` to the real FastAPI backend.
You will connect budget-vs-actual endpoints to show exactly how much of a budget is remaining according to live transactions.

## Requirements
1. **Wire Live Endpoints:** 
   - Fetch defined budgets (the planned amount) from `/api/budgets`.
   - Fetch the aggregated categorized actual spend.
   
2. **Data Presentation:**
   - Display circular or linear progress bars showing the burn-down rate.
   - If a budget is exceeded, reflect an alerting state (red).
   - If pacing ahead of schedule, reflect a warning state (yellow).
   - Show how many days are left in the period for proper context.

3. **Functionality:**
   - Use the backend math directly; do not recalculate actuals on the client if provided by the backend.

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/BudgetsPage.tsx`.
- Map API shapes to local budget card components.
- Make the 'Remaining'/'Over' math reliable.

## Verification
- Load the Budgets page with a test database containing varied spend (0%, 50%, >100%).
- Ensure the progress UI is correctly bounded and handles overflow gracefully.
