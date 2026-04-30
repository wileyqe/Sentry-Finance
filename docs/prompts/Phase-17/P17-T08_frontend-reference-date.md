# P17-T08: Frontend Trusted Reference Date

## Context

The backend now exposes `GET /api/runtime/context` with the trusted seed
reference date and proof readiness. The frontend still had several
date-sensitive defaults built from the browser clock, which could make the UI
query a different period than the trusted audit.

## Starting State

- Header date used `new Date()` at module load.
- Dashboard current-month summary, spending comparison, and budget widgets used
  browser time.
- Transactions quick ranges and manual-add default date used browser time.
- Reports timeframe windows used browser time.
- Cash Flow yearly filtering/padding used browser time.

## Task

1. Add a shared frontend runtime context provider/hook.
2. Load `GET /api/runtime/context` once at app startup.
3. Use the backend `clock.reference_date` for trusted-seed date defaults on:
   Dashboard, Transactions, Cash Flow, Reports, and Header.
4. Preserve live-data behavior by using whatever clock the backend runtime
   context returns.
5. Verify the dev stack requests April 2026 trusted-seed windows.

## Verification

- `cd frontend && npm run build`
- Canonical reseed with `SENTRY_DB_PATH=data/dummy.db` and
  `SENTRY_DB_MODE=trusted`
- Restart backend/frontend dev stack
- `GET /api/runtime/context` returns `reference_date=2026-04-28` and
  `trusted_seed_ready=True`
- Backend request logs show Dashboard requests:
  - `/api/reports/spending-comparison?reference_date=2026-04-28...`
  - `/api/reports/summary?start_date=2026-04-01&end_date=2026-04-30`
  - `/api/budgets/summary?month=2026-04`

## Outcome

Implemented `frontend/src/context/RuntimeContext.tsx` and shared date helpers
in `frontend/src/lib/dateUtils.ts`. The scoped frontend defaults now flow from
the backend runtime clock rather than each page independently sampling the
browser clock.
