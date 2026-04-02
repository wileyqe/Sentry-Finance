# P5-T01: Dashboard Live Data + New KPIs

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `DashboardPage.tsx` to the real FastAPI backend.
You will replace the static placeholder values with dynamic data fetched from the API.

## Requirements
1. **Wire Live Endpoints:** 
   - Connect the page to `/api/portfolio/net-worth`, `/api/transactions/recent`, and any other dashboard summary APIs.
   - Use standard `fetch` or a fetching library (SWR/React Query if already in use in the project) to retrieve data.
   - Handle loading states with skeleton loaders or spinners.
   - Handle error states gracefully.

2. **Add New KPI Cards:**
   - **Net Worth:** Display the current net worth figure along with a velocity arrow (e.g., "↑ 5% this month").
   - **Savings Rate:** Calculate or fetch the current savings rate and display it.
   - **Emergency Fund Runway:** Display the number of months the emergency fund can sustain current spending.
   - **Credit Scores:** Implement a dual-pill UI component to show scores from two sources (e.g., NFCU and Chase).
   - **Data Freshness Indicator:** Show a global freshness metric that indicates how recently the institution data was synced.

3. **Styling & Assets:**
   - Preserve the existing glassmorphic and premium dark-mode aesthetics defined in the UI standards.
   - Ensure the KPI cards are responsive and stack cleanly on smaller screens.
   - Use Lucide icons for visual enhancements in the KPI cards.

## Implementation Steps
- Add the necessary data fetching hooks in `frontend/src/pages/DashboardPage.tsx` (or equivalent component location).
- Modify the KPI components to accept props matching the API response types.
- Build the specific UI components for the new KPIs (Velocity arrow, Credit Score dual pill).

## Verification
- Run the frontend and verify the Dashboard loads without console errors.
- Ensure the data perfectly matches the backend SQLite database state.
- Test loading and error edge cases.
