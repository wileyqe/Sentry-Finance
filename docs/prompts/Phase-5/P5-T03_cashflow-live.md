# P5-T03: Cash Flow Page Live Data

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `CashFlowPage.tsx` to the real FastAPI backend.
You will connect the rolling-window endpoints that model the user's spending against their income over defined time periods.

## Requirements
1. **Wire Live Endpoints:** 
   - Connect the page to the cash flow and rolling window endpoints.
   - Replace any chart mock data with the actual array payloads received from the API.

2. **Data Presentation:**
   - Display Income vs. Expenses over rolling periods (e.g. 30, 60, 90 days).
   - Show cumulative savings/deficit correctly.

3. **Functionality:**
   - Allow date picking or predefined period toggling if supported by backend.
   - Maintain the premium aesthetic with Recharts/Chart.js styling matching the project's CSS variables.

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/CashFlowPage.tsx`.
- Map the backend API response to the format expected by the chart components.
- Handle empty states gracefully (e.g., if there's no data for a given month).

## Verification
- Load Cash Flow page.
- Compare the visual chart data against raw DB queries to confirm accuracy.
