# P5-T07: Investments Page Live Data

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `InvestmentsPage.tsx` to the real FastAPI backend.
You will fetch real portfolio positions, holdings, and performance endpoints for all tracked investment accounts.

## Requirements
1. **Wire Live Endpoints:** 
   - Connect the page to `/api/portfolio/...` endpoints.
   - Include all investment accounts seamlessly (Fidelity, Acorns, TSP).

2. **Holdings Data Representation:**
   - Group the detailed positions by account or asset type/ticker.
   - Display latest values, cost basis (if available from Phase 4), and shares.
   
3. **Performance Metrics:**
   - Display a unified tracking chart mapping the value trajectory over time.
   - Calculate absolute change or percentage change relative to a timeframe.

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/InvestmentsPage.tsx`.
- Refactor the mock array rendering loop to iterate through API-provided holdings.
- Handle styling logic for positive (green) and negative (red) market fluctuations.

## Verification
- Validate the portfolio value visually against the sum of the SQLite holdings tables.
- Render charts securely using real dataset endpoints.
