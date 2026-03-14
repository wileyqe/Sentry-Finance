# Sentry Finance — Recursive UI Review, Test & Troubleshoot Prompt

> **Purpose**: Paste this prompt into a new session to trigger a comprehensive, recursive review of every UI surface using ONLY the dummy database. The agent will visually inspect, functionally test, and aesthetically audit every page — then loop until all issues are resolved.

---

## System Context

You are reviewing the **Sentry Finance** personal finance dashboard — a Tauri/React/Vite desktop application backed by a Python FastAPI sidecar and local SQLite database.

**Critical constraint**: The application is running against a **dummy database only** (`data/dummy.db`), seeded from JSON files in `dummy_data/`. No live financial data should appear anywhere. If you see data that does not originate from the dummy seed files, flag it as a **data contamination bug**.

### Running Services

| Service | Command | URL |
|---|---|---|
| Frontend (Vite dev) | `npm run dev` (in `frontend/`) | `http://localhost:1420` |
| Backend (FastAPI) | `$env:SENTRY_DB_PATH="data\dummy.db"; .venv\Scripts\python.exe backend\api_server.py` | `http://localhost:8000` |

### Pages Under Review

| Route | Page | Key Components |
|---|---|---|
| `/dashboard` | Dashboard | Net Worth trend, Cash Flow chart, Investment summary card, Accounts summary, Budget overview, Recurring transactions |
| `/transactions` | Transactions | Full transaction table with sort/filter/search, category editing via Sheet, pagination |
| `/accounts` | Accounts | Account cards grouped by institution, balance history charts, linked drill-down |
| `/budgets` | Budgets | Budget bars by category, progress indicators, add/edit budget |
| `/investments` | Investments | Holdings table, sector allocation pie chart, portfolio performance line chart, gain/loss coloring |
| `/reports` | Reports | Sankey income/expense diagram, interactive node filtering, date-range controls, filtered transaction list |

### Dummy Data Files (Source of Truth)

```
dummy_data/
├── Institutions.json          # 5 institutions (NFCU, Chase, Fidelity, Acorns, Affirm)
├── Investment_holdings.json   # Individual stock/fund positions with shares, cost basis, sectors
├── balance_snapshots.json     # Daily account balances over ~3 years
├── budgets.json               # Monthly budget allocations by category
├── loan_details.json          # Loan/liability details
├── portfolio_snapshots.json   # Aggregated portfolio value snapshots
├── recurring_transactions.json# Recurring bills and subscriptions
├── savings_goals.json         # Savings goal targets and progress
├── transactions.json          # Core transaction records
└── transactions_dense.json    # Extended 3-year dense transaction history
```

---

## Design Principles (MUST enforce)

Read and internalize ALL of the following skill files before beginning review. These are non-negotiable quality standards:

### 1. Minimalist & Kinetic UI (`skills/skill-kinetic-ui.md`)
- **Zero Slop**: Strip all unnecessary decoration. No excessive shadows, generic gradients, or heavy borders. Brutalist-minimalist + sleek high-contrast modernism.
- **Strict Token Enforcement**: Only use established design tokens (Tailwind spacing, palette). No arbitrary pixel values or rogue hex codes.
- **Kinetic Typography & Micro-interactions**: Static interfaces are forbidden. Every interactive element needs smooth, physics-based spring animations (not linear/ease-in-out).
- **Spatial Layering**: Use floating modal cards for sub-tasks. No flat endless scrolling pages.

### 2. Financial Information Architecture (`skills/Financial-Information-Architecture.md`)
- **High-Density, Low-Clutter**: Maximize data display without overwhelming the user.
- **Structural Integrity**: Use stark typography, strict grid alignment, and negative space. Avoid borders/background shading unless absolutely necessary.
- **Omnipresent Navigation**: Persistent left-aligned nav. User must never feel lost.
- **Data Visualization**: Green/red for gains/losses. Top-level metrics (Net Worth, Cash Flow) immediately visible at hierarchy top with drill-down to granular transactions.

### 3. UI Component Rules (`skills/skill-ui-components.md`)
- Structural components: **shadcn/ui** only (Tables, Buttons, Inputs, Select, Sheets).
- Charts/visualization: **Tremor** React library.
- Row editing: Opens a **Sheet** (right-side drawer).
- All DB mutations use **Optimistic UI** (update visual state immediately, then await backend).

### 4. Deterministic System Architecture (`skills/skill-agen-orchestration.md`)
- Local-first determinism: UI updates optimistically before IPC responses.
- Progressive disclosure: Surface critical info first, delay complex config.

---

## Review Protocol

Execute the following **recursive loop** until every page passes all checks with zero issues:

```
FOR EACH page IN [Dashboard, Transactions, Accounts, Budgets, Investments, Reports]:
    1. NAVIGATE to page
    2. RUN Functional Audit
    3. RUN Data Accuracy Audit  
    4. RUN Aesthetic Audit
    5. RUN Interaction Audit
    6. LOG all issues found
    
IF issues.length > 0:
    FOR EACH issue:
        DIAGNOSE root cause (frontend component, API response, CSS, seed data)
        IMPLEMENT fix
        VERIFY fix on the live page
    GOTO top of loop (re-test ALL pages)
    
ELSE:
    GENERATE final report
    EXIT
```

---

## Audit Checklists

### A. Functional Audit (per page)

- [ ] Page loads without console errors or uncaught exceptions
- [ ] All API calls return 200 (check Network tab / FastAPI logs)
- [ ] No loading spinners stuck indefinitely
- [ ] No empty states that should contain data
- [ ] No `undefined`, `null`, `NaN`, or `[object Object]` rendered in the DOM
- [ ] All interactive elements (buttons, dropdowns, tabs, date pickers) respond to clicks
- [ ] Navigation between pages preserves state correctly
- [ ] Sorting/filtering works and reflects in the displayed data
- [ ] Pagination (if present) shows correct totals and page boundaries
- [ ] Sheet/drawer components open and close properly

### B. Data Accuracy Audit (per page)

- [ ] **All displayed data traces back to dummy data files** — no live or hardcoded values
- [ ] Dollar amounts are formatted correctly (`$X,XXX.XX`)
- [ ] Percentages are formatted correctly (`XX.X%`)
- [ ] Dates are formatted consistently and correctly
- [ ] **Net Worth** = sum of all asset account balances + investment portfolio value − liabilities
- [ ] **Cash Flow** = income − expenses for the selected period (verify math against `transactions_dense.json`)
- [ ] **Investment gains/losses** = current value − cost basis (verify against `Investment_holdings.json`)
- [ ] **Budget progress** = actual spending / budget limit (verify against `budgets.json` and transactions)
- [ ] **Recurring transactions** match `recurring_transactions.json`
- [ ] Account balances match latest entries in `balance_snapshots.json`
- [ ] Charts display correct data points (spot-check at least 3 data points per chart)

### C. Aesthetic Audit (per page)

- [ ] **Zero Slop**: No generic/default-looking UI elements. Every pixel looks intentional.
- [ ] **Color palette**: Harmonious, consistent, no rogue colors outside the design system
- [ ] **Typography**: Clean hierarchy — clear H1/H2/body distinction, no browser-default fonts
- [ ] **Spacing**: Consistent rhythm, proper use of whitespace. No cramped or floating elements.
- [ ] **Charts**: Properly sized within containers (no overflow, no tiny-in-huge-space)
- [ ] **Responsiveness**: Components fill their containers appropriately at the desktop viewport
- [ ] **Green/Red correctness**: Gains are green, losses are red — never reversed
- [ ] **Visual polish**: Hover states present on all interactive elements, transitions feel smooth
- [ ] **Dark mode**: All elements are visible and contrast-appropriate (no white-on-white, no invisible text)
- [ ] **No layout jank**: No overlapping elements, no content pushed off-screen, no stretched/warped items

### D. Interaction Audit (per page)

- [ ] **Hover states**: Every clickable element has a visible hover effect
- [ ] **Micro-animations**: Page transitions, card entrances, chart drawing animations present
- [ ] **Sheet interactions**: Right-side sheet opens on table row click, edits save correctly
- [ ] **Chart interactivity**: Tooltips on hover, click interactions where applicable
- [ ] **Sankey diagram** (Reports): Nodes are clickable, clicking filters the transaction list below
- [ ] **Date range controls**: Changing date ranges re-fetches and re-renders data correctly
- [ ] **Sort controls** (Transactions): Column headers are clickable, sort direction toggles, visual indicator shows active sort

---

## Issue Severity Classification

When logging issues, classify each one:

| Severity | Definition | Example |
|---|---|---|
| 🔴 **P0 — Broken** | Feature is non-functional or shows wrong data | Net Worth shows `NaN`; page crashes on load |
| 🟠 **P1 — Degraded** | Feature works but with incorrect behavior | Sort doesn't toggle direction; chart overflows container |
| 🟡 **P2 — Polish** | Cosmetic issue that violates design principles | Missing hover state; generic font; no entry animation |
| 🟢 **P3 — Enhancement** | Not broken, but could be better | Could add sparklines; tooltip could show more detail |

**Fix priority**: P0 first, then P1, then P2. Log P3 items but do not fix unless all P0–P2 are resolved.

---

## Troubleshooting Decision Tree

```
Issue: Empty or missing data
├── Check API response (GET /api/... in browser or curl)
│   ├── API returns empty → Check seed script, verify dummy.db has data
│   └── API returns data  → Check frontend component, verify field mapping
│
Issue: Wrong numbers / bad math
├── Trace the calculation
│   ├── Backend (dal/*.py or backend/routers/*.py) → Fix SQL query or aggregation
│   └── Frontend (pages/*.tsx) → Fix JS calculation or field mapping
│
Issue: Styling / layout violation
├── Identify the component
│   ├── Uses inline styles → Convert to Tailwind tokens
│   ├── Uses wrong component → Replace with shadcn/ui equivalent
│   └── Missing animation → Add Framer Motion or CSS spring transition
│
Issue: Data contamination (non-dummy data visible)
├── Check SENTRY_DB_PATH env var → Must be "data\dummy.db"
├── Check for hardcoded values in .tsx files → Remove and bind to API data
└── Check seed script → Ensure it doesn't merge with sentry.db
```

---

## Final Deliverable

After all pages pass all audits with zero P0/P1/P2 issues, produce a summary report:

```markdown
# UI Review Report — [Date]

## Pages Reviewed: 6/6
## Iterations Required: N

### Issues Found & Resolved
| # | Page | Severity | Description | Root Cause | Fix Applied |
|---|------|----------|-------------|------------|-------------|
| 1 | ...  | ...      | ...         | ...        | ...         |

### Remaining P3 Enhancements (Optional)
- ...

### Aesthetic Score (per page)
| Page | Score (1-10) | Notes |
|------|-------------|-------|
| Dashboard | X | ... |
| Transactions | X | ... |
| Accounts | X | ... |
| Budgets | X | ... |
| Investments | X | ... |
| Reports | X | ... |

### Screenshots
[Embed screenshots of each final page state]
```

---

## Rules of Engagement

1. **Context management**: Follow `skills/context-window-management.md`. Do not load more than 3 full files at once. Use skeletons for adjacent code.
2. **Dummy data only**: The env var `SENTRY_DB_PATH` must equal `data\dummy.db`. If it doesn't, fix it before starting.
3. **No live browser sessions**: Do not launch Playwright or connect to CDP. This is UI-only testing via `localhost:1420`.
4. **Fix in place**: When you find an issue, fix it immediately in the source code, verify the fix renders correctly, then continue the audit.
5. **Record screenshots**: Capture at least one screenshot per page per iteration for the final report.
6. **Be ruthless on aesthetics**: This is a premium financial dashboard. If it looks "generic", "default", or "bootstrapped", that is a P2 bug. The bar is Monarch Money / Copilot Money / Linear-level polish.
