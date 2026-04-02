# P5-T05: Accounts Page Live Data + Freshness Badges

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `AccountsPage.tsx` to the real FastAPI backend.
You will fetch the actual list of tracked portfolio accounts (checking, savings, credit cards, loans).

## Requirements
1. **Wire Live Endpoints:** 
   - Connect the page to `/api/accounts` or `/api/portfolio/accounts`.
   - Update account totals to reflect live SQLite balances.

2. **Per-Institution Freshness Badges:**
   - Compare the API's `last_updated` or `snapshot_time` against the current date/time.
   - Display a freshness badge natively next to each institution or account:
     - **Green:** Synced recently (e.g., < 24 hrs)
     - **Yellow:** Staleness warning (e.g., 1-3 days)
     - **Red:** Outdated data (e.g., > 3 days)

3. **Document Drop Nudge Integration:**
   - Read from the `documents/pending-nudges` endpoint and display inline alerts or banners corresponding to specific accounts (e.g. "TSP statement is overdue").

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/AccountsPage.tsx`.
- Construct the freshness badge component and logic to evaluate relative timestamps (`date-fns` or `dayjs`).
- Pass nudge alerts to the respective account groups visually.

## Verification
- Refresh the Accounts page and ensure balances align perfectly with the backend view.
- Confirm freshness states accurately reflect the timestamps of the last scrapes or document drops.
