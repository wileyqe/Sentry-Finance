# P2-T03: Document Drop Frontend

## Context

You are working on Sentry Finance, a local-first personal finance app.
P2-T02 built the document drop backend. This task builds the frontend:
a drag-and-drop file zone, a parse preview modal, and a persistent nudge
toast for overdue Tier 3 institutions.

The app is React + TypeScript + Tailwind CSS with Framer Motion animations.
The existing design language uses:
- Dark mode: `bg-slate-900`, `border-slate-700`
- Accent: `text-gain` (green), `text-loss` (red), `text-blue-400`
- Shadows: `shadow-lg`, rounded: `rounded-xl` / `rounded-lg`
- Body text: `text-sm text-slate-700 dark:text-slate-200`
- Material Symbols Outlined icons via class `material-symbols-outlined`

Frontend file structure (relevant parts):
```
frontend/src/
  pages/          AccountsPage.tsx, DashboardPage.tsx, etc.
  components/     AccountsSummaryCard.tsx, RefreshBanner.tsx,
                  ToastContainer.tsx, ErrorBoundary.tsx, MFAModal.tsx (P2-T01)
  lib/            api.ts (apiFetch), toast.ts (toast()), accounts.ts, utils.ts
```

### Toast system (`lib/toast.ts`):
```typescript
export function toast(message: string, type: ToastType = "info", duration = 3500)
```
Fires a notification that appears in `ToastContainer` (bottom-right, auto-dismisses).

### API client (`lib/api.ts`):
```typescript
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T>
```
Prepends `http://127.0.0.1:8000`, throws `ApiError` on non-2xx.

---

## Endpoints (from P2-T02)

```
POST /api/documents/upload
  Body: multipart/form-data, field name "file"
  Response: {
    file_id: string,
    filename: string,
    parser_type: string,
    preview: Record<string, any>,
    warnings: string[],
    can_commit: boolean,
  }

POST /api/documents/commit
  Body: { file_id: string }
  Response: { status: "committed", parser_type: string, summary: {...} }

GET /api/documents/history?limit=20
  Response: { documents: [...] }

GET /api/documents/pending-nudges
  Response: { nudges: [{ institution, display_name, message }] }
```

---

## Task

### 1. Create `frontend/src/components/DocumentDrop.tsx`

A self-contained drag-and-drop zone that handles the full upload flow:
1. User drops a file (or clicks to browse)
2. File is uploaded to `/api/documents/upload`
3. Parse preview is shown in a modal
4. User confirms → commit is called → success toast
5. User cancels → staged file is abandoned (no cleanup needed server-side)

```tsx
/**
 * DocumentDrop — Drag-and-drop document ingestion zone.
 *
 * States:
 *   idle       — waiting for drop
 *   uploading  — file uploaded, awaiting parse result
 *   preview    — showing ParseResult for user confirmation
 *   committing — committing to DB
 *   success    — committed, showing summary
 *   error      — parse or commit failed
 */
```

**Visual design:**
- Container: dashed border, `border-slate-400 dark:border-slate-600`, rounded-xl
- Idle state: cloud upload icon + "Drop a PDF or XLSX file here" + "or click to browse" in muted text
- Drag-over state: border becomes `border-blue-400 bg-blue-50 dark:bg-blue-900/20`
- Uploading state: spinner + "Parsing document..."
- Error state: red icon + error message
- Use `<input type="file" accept=".pdf,.xlsx" hidden ref={inputRef} />`
  triggered by clicking the drop zone

**Preview modal:**
- Appears as a full-screen overlay (z-50) when parse result arrives
- Shows `parser_type` as a pill badge ("TSP Statement", "myPay RAS", "Unknown")
- Shows each key in `preview` dict as a two-column table (label: value)
- Shows any `warnings` in yellow if present
- "Confirm & Import" button (disabled if `can_commit === false`)
- "Cancel" button (dismisses without committing)
- Framer Motion: `initial={{ opacity: 0, scale: 0.95 }}` → `animate={{ opacity: 1, scale: 1 }}`

**Implementation notes:**
- Use `FormData` to send the file: `fd.append("file", file)`
- `fetch` (or `apiFetch`) with `method: "POST"` — do NOT set Content-Type header
  manually (browser sets it with the boundary)
- On commit success: call `toast("Document imported successfully", "success")`
- On commit failure: call `toast(errorMessage, "error")`

### 2. Create `frontend/src/pages/DocumentsPage.tsx`

A dedicated page at route `/documents` that shows:
- The `<DocumentDrop />` component at the top
- A "Recent imports" history table below (from `GET /api/documents/history`)

History table columns: Date, File Name, Type, Status (Committed / Pending)

### 3. Create `frontend/src/components/DocumentNudge.tsx`

A persistent nudge banner for overdue Tier 3 documents.

This is NOT a regular toast — it's a persistent banner that stays until dismissed
(or until the document is successfully imported). It should:
- Appear at the bottom of the screen, above the regular toasts
- Show the institution name and message from the nudge API
- Have a "Drop File" button that opens the DocumentsPage or a drop zone in place
- Have a subtle "Dismiss for today" link (stores dismissal timestamp in localStorage,
  checks next page load)

Poll `GET /api/documents/pending-nudges` on app load and once per hour
(use a `setInterval` with cleanup in `useEffect`).

```tsx
// Dismiss logic
const NUDGE_DISMISS_KEY = "nudge_dismissed_until";
function isDismissed(): boolean {
  const until = localStorage.getItem(NUDGE_DISMISS_KEY);
  if (!until) return false;
  return new Date(until) > new Date();
}
function dismissForToday() {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(0, 0, 0, 0);
  localStorage.setItem(NUDGE_DISMISS_KEY, tomorrow.toISOString());
}
```

### 4. Wire the new route and components into the app

Find `frontend/src/App.tsx` (or wherever routes are defined) and add:
```tsx
import DocumentsPage from "./pages/DocumentsPage";
// ...
<Route path="/documents" element={<DocumentsPage />} />
```

Find the nav/sidebar (look for where AccountsPage, DashboardPage etc. are linked)
and add a "Documents" nav item with a `description` or `upload_file` icon.

Find the app root layout (the component that wraps all pages — likely renders
`ToastContainer` and `MFAModal`) and render `<DocumentNudge />` there.

---

## Files to Create

1. `frontend/src/components/DocumentDrop.tsx`
2. `frontend/src/pages/DocumentsPage.tsx`
3. `frontend/src/components/DocumentNudge.tsx`

## Files to Modify

4. `frontend/src/App.tsx` (or router file) — add `/documents` route
5. The nav/sidebar component — add Documents link
6. The app root layout — render `<DocumentNudge />`

## Files NOT to Modify

- Any backend files
- `lib/toast.ts` — use as-is
- `lib/api.ts` — use `apiFetch` as-is
- `ToastContainer.tsx` — the nudge is a separate persistent component, not a toast

---

## Constraints

- The drag-and-drop zone must work on Windows (Chromium/Electron via Tauri)
- File size > 50 MB should show a client-side error before uploading
  (check `file.size` before calling the API)
- The `file` input `accept` attribute: `.pdf,.xlsx` (matches what parsers support)
- Supported parser types for display labels:
  ```typescript
  const PARSER_LABELS: Record<string, string> = {
    tsp_statement: "TSP Statement",
    mypay_ras: "myPay RAS",
    unknown: "Unknown Document",
  };
  ```
- Preview dict keys are snake_case from Python — convert to Title Case for display:
  `"statement_date"` → `"Statement Date"`, `"total_balance"` → `"Total Balance"`
- The commit button text should reflect the action: "Import TSP Balance", not just "Confirm"
- Error handling: if `can_commit === false` (unknown parser), show message
  "Document type not recognized. Check that this is a TSP statement or supported file."
  instead of the preview table
- Keep the `DocumentNudge` component lightweight — it should not re-render
  on every route change

---

## Done Checklist

- [ ] `DocumentDrop.tsx` created with idle/uploading/preview/committing/success/error states
- [ ] Drag-and-drop works (dragover, dragleave, drop events)
- [ ] Click-to-browse works (hidden `<input type="file" />`)
- [ ] File size > 50 MB rejected client-side before upload
- [ ] Preview modal shows parser_type, preview dict, warnings, Confirm + Cancel buttons
- [ ] `can_commit === false` shows "unrecognized" message instead of preview table
- [ ] Commit calls `POST /api/documents/commit` with `file_id`
- [ ] Success: `toast("Document imported successfully", "success")`
- [ ] `DocumentsPage.tsx` created at `/documents` route
- [ ] History table shows recent imports from `GET /api/documents/history`
- [ ] `DocumentNudge.tsx` polls pending-nudges, shows persistent banner when due
- [ ] Nudge dismiss logic stores until-midnight in localStorage
- [ ] Route wired in `App.tsx`
- [ ] Nav item added
- [ ] `DocumentNudge` rendered in root layout

## Verification

After completion, Claude will:
1. Read all three new component files — check state machine completeness,
   FormData construction, and that Content-Type is NOT manually set on the upload fetch
2. Verify the route is registered in App.tsx
3. Verify DocumentNudge is rendered in root layout
4. Check that nudge dismiss logic correctly computes "until midnight"
5. Check that preview dict keys are displayed with human-friendly labels
6. Check drag-and-drop event handlers: `onDragOver`, `onDragLeave`, `onDrop`
   all preventDefault() correctly
7. Check file size guard: `file.size > 50 * 1024 * 1024` before upload
