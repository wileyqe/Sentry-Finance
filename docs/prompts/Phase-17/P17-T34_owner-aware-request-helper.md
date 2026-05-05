# P17-T34: Owner-Aware Frontend Request Helper

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/37

## Context

Owner scoping is first-class end-to-end. Backend DAL coverage for
`dal/owners.build_account_filter` is strong, and `useOwnerApi` handles
hook-based owner-aware requests. Several pages still perform imperative
`fetch()` calls and manually append `owner_id`, sometimes without
`encodeURIComponent`.

This is an AFK overnight slice for Codex or Claude.

## Starting State

- `frontend/src/lib/useOwnerApi.ts` appends encoded `owner_id` for hook
  calls.
- `frontend/src/pages/CashFlowPage.tsx`,
  `frontend/src/pages/MonthlyReviewPage.tsx`, and
  `frontend/src/pages/YearlyWrapUpPage.tsx` manually build owner query
  strings.
- `frontend/src/pages/ReportsPage.tsx` uses `URLSearchParams`, which is a
  safer local pattern.
- Household-only budgets are an intentional exception and must remain
  same-across-owner.

## Task

1. Read `docs/ARCHITECTURE.md` section 6.3, `CLAUDE.md` owner-scoping
   guardrail, and `frontend/src/lib/useOwnerApi.ts`.
2. Add a small frontend module for owner-aware imperative requests or URL
   construction beside `useOwnerApi`.
3. Migrate owner-aware imperative fetches in Cash Flow, Monthly Review,
   and Yearly Wrap-Up to the shared helper.
4. Keep Reports on `URLSearchParams` or migrate it only if the shared helper
   clearly improves locality without churn.
5. Add a focused test if the frontend test setup supports it; otherwise add
   the smallest static/exported helper test practical in this repo.

## Non-Goals

- Do not change `dal/owners.build_account_filter`.
- Do not introduce per-owner budgets.
- Do not redesign frontend data fetching broadly.
- Do not touch owner lifecycle/product behavior.

## Verification

- Run the frontend build or targeted frontend tests available in the repo.
- Run any owner-scoping tests if backend code changes unexpectedly.
- Search for remaining unsafe manual `owner_id=` construction and explain
  any intentional leftovers.

## Agent Shutdown

Use branch `codex/p17-t34-owner-aware-request-helper` or
`claude/p17-t34-owner-aware-request-helper`. Commit and stop. Do not merge.
