# P5-T04: Reports Page Live Data

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `ReportsPage.tsx` to the real FastAPI backend.
You will connect reports that show a macro view of spending, such as the Sankey flow chart and other categorizations.

## Requirements
1. **Wire Live Endpoints:** 
   - Fetch report data (e.g., spending by category, income by source).
   - Ensure the Sankey chart successfully renders with real nodes and links.

2. **Sankey Chart Logic:**
   - Address any topological sorting or layout issues inside the Sankey chart when dynamic nodes form unexpected cyclic or disconnected graphs.
   - Map backend categorization directly to Sankey "from-to" structures.

3. **Functionality:**
   - Support month/year filtering as provided by the API.

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/ReportsPage.tsx`.
- Transform raw backend flow data into Sankey-compatible objects.
- Style the charts appropriately according to the UI standards document.

## Verification
- Test that the Reports load correctly for past, present, and future (empty) months.
- Verify node colors and link gradients are correctly assigned.
