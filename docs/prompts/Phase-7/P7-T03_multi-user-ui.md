# P7-T03: Multi-User UI (Selector + Onboarding)

## Context

You are working on Sentry Finance, a local-first personal finance app
for a two-person household. The backend is fully owner-scoped (P7-T02):
every DAL function and API endpoint accepts an optional `owner_id`
parameter. The settings page (P7-T01) has a multi-user toggle. The owners
table and config infrastructure exist.

This task builds the **user-facing multi-user experience**:
1. A **view selector** in the app header/sidebar (Mine / Partner / Household)
2. A **partner onboarding flow** to add the second person
3. **All existing pages filter** by the active view context

### Household financial views

| View | What it shows | `owner_id` passed to API |
|------|---------------|--------------------------|
| Mine | Primary owner's accounts + shared accounts | `"mine"` |
| Partner | Partner's accounts + shared accounts | `"theirs"` |
| Household | All accounts (combined view) | `None` (no filter) |

The active view is global state — changing it re-filters every page.

## Starting State

- `dal/owners.py` — `resolve_account_ids_for_view()`, `get_primary_owner()`,
  `list_owners()`, `create_owner()`, `assign_account_owner()`,
  `seed_owners()`, `get_configured_owners()`
- `config/owner_config.yaml` — defines primary owner, partner commented out
- `dal/settings.py` — `get_setting(conn, "multi_user_enabled")` → bool
- `backend/routers/accounts.py` — `POST /api/owners`, `PATCH /api/accounts/{id}/owner`
- `backend/routers/settings.py` — `GET /api/settings/multi-user-enabled`
- P7-T02 completed — all DAL functions and router endpoints accept `owner_id`
- Sidebar.tsx has settings link but no view selector

## Task

### 1. Frontend: View Context Provider

Create `frontend/src/context/ViewContext.tsx`:

```typescript
interface ViewContextType {
  view: "mine" | "theirs" | "household";
  setView: (v: "mine" | "theirs" | "household") => void;
  ownerParam: string | null;          // "mine" | "theirs" | null
  multiUserEnabled: boolean;
  owners: Owner[];
  primaryOwner: Owner | null;
  partnerOwner: Owner | null;
}
```

**Behavior:**
- On mount, fetch `GET /api/settings/multi-user-enabled` and `GET /api/owners`.
- If `multi_user_enabled = false` OR fewer than 2 owners exist, set
  `multiUserEnabled = false`. The selector is hidden and `ownerParam = null`.
- If `multi_user_enabled = true` AND 2+ owners exist, set
  `multiUserEnabled = true`. Default view = `"household"`.
- `ownerParam` is what gets appended to API calls:
  - `"mine"` → `?owner_id=mine`
  - `"theirs"` → `?owner_id=theirs`
  - `"household"` → no parameter (default behavior)
- View persists in `localStorage` key `"sentry_view"`.

### 2. Frontend: View Selector Component

Create `frontend/src/components/ViewSelector.tsx`:

**When `multiUserEnabled = true`:**
Renders a segmented control (3 buttons) in the sidebar above the nav items:

```
┌─────────┬──────────┬───────────┐
│  Mine   │ Partner  │ Household │
└─────────┴──────────┴───────────┘
```

- Each segment shows the owner's `display_name` (from owners list)
  for Mine/Partner, and "Household" for the combined view.
- Active segment is highlighted (primary color fill).
- Clicking a segment updates the view context.
- When a segment is selected, a subtle badge shows the account count
  for that view.

**When `multiUserEnabled = false`:**
Renders nothing (completely hidden, not disabled).

### 3. Frontend: Wire View Context to All Pages

Wrap the app in `<ViewProvider>`:

```tsx
// App.tsx
<ViewProvider>
  <Routes>
    ...
  </Routes>
</ViewProvider>
```

Every page that fetches data from the API must include `ownerParam`
in its requests when non-null:

```typescript
const { ownerParam } = useView();

// In fetch calls:
const url = ownerParam
  ? `/api/reports/spending?months=6&owner_id=${ownerParam}`
  : `/api/reports/spending?months=6`;
```

**Pages to update:**

| Page | API calls that need `owner_id` |
|------|-------------------------------|
| DashboardPage | transactions, summary, recurring, net-worth-history, spending-comparison, budgets/summary, budgets, net-worth-velocity, emergency-fund |
| TransactionsPage | transactions |
| CashFlowPage | cash-flow/monthly-rolling, quarterly-rolling, yearly |
| ReportsPage | reports/flow, transactions |
| AccountsPage | accounts, freshness, net-worth-history |
| BudgetsPage | budgets |
| InvestmentsPage | accounts, investments/holdings, allocation, performance, contributions-vs-performance |
| MonthlyReviewPage | review/monthly, lifestyle/creep |
| YearlyWrapUpPage | review/yearly, cash-flow/available-years |

**Implementation approach:**

Create a utility hook `useApi` (or extend the existing one) that
automatically appends `owner_id` when the view context has one:

```typescript
function useOwnerApi<T>(path: string, deps?: any[]): {data: T | null, loading: boolean, error: Error | null} {
  const { ownerParam } = useView();
  const separator = path.includes("?") ? "&" : "?";
  const fullPath = ownerParam ? `${path}${separator}owner_id=${ownerParam}` : path;
  return useApi<T>(fullPath, [...(deps || []), ownerParam]);
}
```

This way, existing `useApi` calls just change to `useOwnerApi` — minimal
diff per page.

### 4. Frontend: Partner Onboarding Flow

Create `frontend/src/components/PartnerOnboarding.tsx`:

This is a modal/drawer triggered from the Settings page when the user
clicks "Add Partner" (visible when < 2 owners exist).

**Step 1: Partner Details**
- Text input: Partner's name (display_name)
- Generate an `owner_id` from the name (lowercase, no spaces)
- "Next →" button

**Step 2: Account Assignment**
- Show all accounts currently in the system
- For each account, show a dropdown: Mine / Partner's / Shared
- Pre-populate:
  - All accounts default to "Mine" (primary owner)
  - Credit cards default to "Shared"
- "Save & Enable Household Mode →" button

**Step 3: Confirmation**
- Summary: "Created partner [Name]. Assigned X accounts."
- "Done" button closes the modal.

**API calls on submit:**
1. `POST /api/owners` with the new partner details
2. For each account assignment:
   `PATCH /api/accounts/{account_id}/owner` with the chosen `owner_id`
   (or `null` for shared)
3. `PATCH /api/settings/multi_user_enabled` with `{"value": true}`

### 5. Frontend: Sidebar Profile Update

The sidebar footer currently shows a hardcoded "Alex Morgan / Admin".
Update it to:

**When multi-user enabled:**
- Show the active view name: "Viewing: [Mine / Partner / Household]"
- Small avatar with the active owner's initial letter

**When multi-user disabled:**
- Show the primary owner's `display_name` from `GET /api/owners`
- Or hide the profile section entirely

### 6. Backend: View-Aware Convenience Endpoint

Add to `backend/routers/accounts.py`:

```python
@router.get("/api/accounts/by-view")
def accounts_by_view(owner_id: str | None = None):
    """
    Returns accounts filtered by view context, grouped by type.
    Used by the frontend to show account counts per view segment.
    """
    with get_db() as conn:
        # Use existing account listing logic with owner_id filter
        accounts = get_accounts(conn, owner_id=owner_id)
    return {
        "count": len(accounts),
        "accounts": accounts,
    }
```

## Files to Create

1. `frontend/src/context/ViewContext.tsx`
2. `frontend/src/components/ViewSelector.tsx`
3. `frontend/src/components/PartnerOnboarding.tsx`

## Files to Modify

1. `frontend/src/App.tsx` — wrap in `<ViewProvider>`, update routes
2. `frontend/src/components/layout/Sidebar.tsx` — add ViewSelector,
   update profile section
3. `frontend/src/pages/DashboardPage.tsx` — use `useOwnerApi`
4. `frontend/src/pages/TransactionsPage.tsx` — use `useOwnerApi`
5. `frontend/src/pages/CashFlowPage.tsx` — use `useOwnerApi`
6. `frontend/src/pages/ReportsPage.tsx` — use `useOwnerApi`
7. `frontend/src/pages/AccountsPage.tsx` — use `useOwnerApi`
8. `frontend/src/pages/BudgetsPage.tsx` — use `useOwnerApi`
9. `frontend/src/pages/InvestmentsPage.tsx` — use `useOwnerApi`
10. `frontend/src/pages/MonthlyReviewPage.tsx` — use `useOwnerApi`
11. `frontend/src/pages/YearlyWrapUpPage.tsx` — use `useOwnerApi`
12. `frontend/src/pages/SettingsPage.tsx` — add "Add Partner" button
    and onboarding trigger
13. `backend/routers/accounts.py` — add `/api/accounts/by-view`
14. `frontend/src/lib/api.ts` — add `useOwnerApi` hook

## Files NOT to Modify

- `dal/*.py` — owner scoping already done in P7-T02
- `backend/routers/reports.py` — already accepts `owner_id`
- `dal/owners.py` — already complete
- `config/owner_config.yaml` — onboarding creates via API, not YAML

## Constraints

- The view selector must be **completely invisible** when multi-user is
  disabled. Not greyed out, not collapsed — absent from the DOM.
- The "Household" view must produce **exactly the same results** as the
  current app behavior (no owner_id param sent). This is the default
  and the fallback.
- View state persists in localStorage, not in the database. It's a
  UI preference, not a shared setting.
- The `useOwnerApi` hook must be a drop-in replacement for `useApi` —
  the only change per page should be the import and function name.
  Do NOT refactor the data fetching patterns of existing pages.
- Partner onboarding must NOT modify `config/owner_config.yaml`. It
  creates the owner via the API only. The YAML file is for initial
  setup and can be updated manually if needed.
- Account assignment in onboarding step 2 uses `PATCH /api/accounts/{id}/owner`
  which already exists — do NOT create a batch endpoint.
- If a user disables multi-user mode after enabling it, the owner data
  persists but the filter stops being applied. Re-enabling restores
  the previous view.

## Done Checklist

- [ ] `ViewContext.tsx` with view state, ownerParam, multiUserEnabled
- [ ] `ViewSelector.tsx` segmented control (hidden when disabled)
- [ ] `PartnerOnboarding.tsx` 3-step flow (details → assignment → confirm)
- [ ] `useOwnerApi` hook in `frontend/src/lib/api.ts`
- [ ] All 9 data pages updated to use `useOwnerApi`
- [ ] `GET /api/accounts/by-view` endpoint added
- [ ] Sidebar updated: ViewSelector + profile section
- [ ] SettingsPage "Add Partner" button triggers onboarding
- [ ] View persists in localStorage
- [ ] Household view produces same results as current behavior
- [ ] View selector hidden when multi-user disabled
- [ ] Partner onboarding creates owner + assigns accounts via API

## Verification

After completion, Claude will:
1. Verify `ViewContext` provider wraps the app
2. Verify `useOwnerApi` hook appends `owner_id` when view != "household"
3. Verify each page uses `useOwnerApi` (not raw `useApi`) for data fetches
4. Verify ViewSelector is hidden when `multiUserEnabled = false`
5. Verify PartnerOnboarding calls correct API endpoints in sequence
6. Verify localStorage persistence of view state
7. Run TypeScript check: `npx tsc --noEmit` — 0 errors
