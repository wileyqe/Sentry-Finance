# P5-T02: Transactions Page Live Data + Teach-the-System

## Context
You are working on Sentry Finance, a local-first personal finance app.
The backend API is functional, but the frontend React pages are currently using dummy/mock data.
The goal of this task is to wire the `TransactionsPage.tsx` to the real FastAPI backend.
You will connect the list of transactions to `/api/transactions` and implement an advanced "teach-the-system" categorization flow.

## Requirements
1. **Wire Live Endpoints:** 
   - Connect the page to the list of transactions.
   - Support pagination, filtering, and sorting as exposed by the existing API.
   - Display Uncategorized transaction nudges via toast notifications.

2. **Categorization Teaching Flow:**
   - When a user clicks to categorize a transaction, present a structured dialog:
     1. Choose Category
     2. Name/Map Merchant (normalize raw statement descriptions to readable names)
     3. Mark as Recurring (boolean toggle)
     4. Select Amount Match Strategy (Is this a fixed amount or variable?)
   - This sends a payload to a backend rule engine (e.g. `POST /api/user-rules/merchants` or similar) so future identical transactions are auto-categorized.

3. **Functionality:**
   - Clicking a transaction opens a slide-over/modal for details and rule creation.
   - After a rule is saved, smoothly update the UI to reflect the newly categorized transaction without full page reloading (optimistic updates preferred via React Query/SWR).
   - Display toast/snackbars for success and error states.

## Implementation Steps
- Add data fetching hooks in `frontend/src/pages/TransactionsPage.tsx`.
- Create the components for the "teach the system" wizard dialog.
- Bind form submissions to the correct API routes.
- Format transaction dates and currency standard to the rest of the application.

## Verification
- Test categorizing an uncategorized transaction and saving a rule.
- Refresh the page and confirm the transaction retains the new category and mapping.
