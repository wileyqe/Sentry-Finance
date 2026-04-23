# P0 Codebase Audit — Prompt Template

Paste the block below into a fresh Claude Code session (on clean `main`). It
dispatches 10 parallel audit agents scoped to Sentry Finance specifics,
synthesizes findings into P0/P1/P2 buckets, and lands P0 fixes on a dedicated
branch without pushing. Edit this file rather than editing the prompt inline
at paste time — keeps the template and its history in one place.

Origin: derived from the "Parallel Multi-Agent Audit Swarms" suggestion in
`~/.claude/usage-data/report.html` (2026-03-26 → 2026-04-22 insights), then
reshaped to ground each agent in the canonical patterns and guardrails this
repo already enforces (owner-scoping via `build_account_filter`, transfer_tag
+ blacklist aggregate pattern from ARCHITECTURE §4.6, household-only budgets
post-v23, investment seeder cosmetic caveat, connector catch-log-continue).

---

You are starting a comprehensive audit of the Sentry Finance codebase. Before dispatching any agents, do these in order and stop to ask if anything's ambiguous — don't guess.

1. Read `CLAUDE.md`, `docs/ARCHITECTURE.md` §3 and §4.6, and `dal/owners.py` (especially `build_account_filter`, which is the canonical owner-scoping API: `None` means no filter, `[]` means owner-owns-nothing via `AND 1=0`, and `if not account_ids:` is a known regression). These define the patterns your agents will detect violations against.
2. Confirm `main` is clean and synced with `origin/main` per Branch & Worktree Hygiene. Create and switch to `audit/p0-{today}` off clean main. All fix commits land there; nothing pushes until I say so.
3. `mkdir -p .audit docs/audits` and add `.audit/` to `.gitignore` if it isn't already.

Then **dispatch 10 Explore subagents in parallel**, one per mandate. Each writes `.audit/<name>.json` using the schema below, caps findings at 25 (top-severity only), and ignores `__pycache__`, `node_modules`, `dist`, `data/`, `.venv/`, `profiles/`, and `migrations/*.sql` unless the mandate specifically targets schema.

**Agent mandates** (scoped to Sentry Finance specifics, not generic lint):

1. **owner-scoping** — DAL queries touching per-person tables (`transactions`, `balances`, `positions_ledger`, `payroll_snapshots`) without threading through `build_account_filter`. Flag `if not account_ids:` shortcuts. Exception: budgets are household-only post-v23 — `owner_id` on the budgets DAL/router is a REGRESSION. Scan `dal/`, `routers/`, `frontend/hooks/`.
2. **pii-leaks** — what `scripts/pii_scan.py` would miss: last-4 in log format strings, real merchant names in fixtures, account numbers in docstrings, PII in the last 50 commit messages. Skip files in `pii_scan.py::ALLOWLIST`.
3. **n-plus-one** — per-row DB/HTTP calls inside loops over transactions/accounts/positions. Focus `dal/reports.py`, `dal/performance.py`, `dal/transactions.py`, `extractors/`.
4. **test-coverage-gaps** — hot paths lacking assertions: `upsert_transactions` sign/direction invariant, `build_account_filter` None-vs-`[]` semantics, budget household-uniqueness partial index, transfer_tag + blacklist aggregates (per §4.6 — any `SUM(CASE WHEN direction='Debit'...)` survivor is itself a P0 finding), connector catch-log-continue isolation.
5. **a11y** — `.tsx` only: icon buttons without `aria-label`, color-only red/green money signaling, broken heading hierarchy, non-keyboard-reachable menus/drawers, form inputs without labels.
6. **dead-code** — exported symbols with zero importers (TS + Py); post-Phase-14 residue (SunburstChart attempts, abandoned seeder helpers). Use `ts-prune` for frontend; grep for Python.
7. **type-safety** — `any`, `as any`, `as unknown as X`, `@ts-ignore`, `@ts-expect-error` in `frontend/src/`. Counts per file + worst-offender examples.
8. **error-handling** — bare `except:`, swallowed exceptions, connector blocks that could crash the shared refresh pipeline (must catch-log-continue), frontend fetch paths with no error UI, post-commit pipeline steps (categorization/reconciliation/recurring/derived/alerts/goals) that don't isolate failures.
9. **synthetic-vs-real-mislabeling** — seeded dummy values shown in UI without a "seeded" affordance; investment benchmark cards that obscure the deterministic-linear-drift caveat CLAUDE.md explicitly names (VTI +1.5/mo, VXUS +0.3/mo, BND −0.1/mo vs live yfinance TWR — treat as known, don't "fix" by reshaping the generator); fixtures claiming "real" provenance.
10. **api-contract-drift** — `routers/*.py` response shapes vs `frontend/src/api/*.ts` and `frontend/hooks/*.ts`. Flag both directions: dead backend fields (frontend doesn't consume) and frontend-expected-but-missing fields (runtime undefined).

**Finding schema** (strict — each agent emits exactly this):

```json
{
  "agent": "<name>",
  "scanned_paths": ["..."],
  "findings": [
    {
      "severity": "P0|P1|P2",
      "title": "<short>",
      "file": "path/to/file.py",
      "line": 123,
      "evidence": "<=3 lines of code>",
      "why": "<canonical pattern or guardrail violated>",
      "suggested_fix": "<concrete change — named function/file>"
    }
  ]
}
```

**Severity** (enforce strictly; when in doubt, downgrade):
- **P0** — correctness bug, security/PII leak, or invariant violation in a shipped path. Users are currently wrong.
- **P1** — drift from canonical pattern with latent risk; not yet wrong.
- **P2** — hygiene or preventive-only.

**After agents return.** Write `docs/audits/{today}-synthesis.md` with: per-agent counts, P0/P1/P2 buckets, a ranked top-10 across buckets (title + file:line + one-sentence impact), and any findings where two agents independently flagged the same region (high-confidence hotspots). Show me the synthesis before executing any fix.

**Execution (one pass, P0 only, after my ack).** On branch `audit/p0-{today}`:
- One commit per fix. Subject `fix({agent}): {title}`. Body cites the finding file:line.
- After each commit, run the relevant test slice: DAL/migration/reconciliation/connector touches → full backend suite per CLAUDE.md; frontend touches → `npm run build` + any frontend tests present.
- **Stop and ask** before touching: `accounts.yaml`, migrations, connector auth code, `scripts/pii_scan.py`, `CLAUDE.md`, or anything flagged with <90% confidence. Also stop if a test starts failing that was green on `main` — do not "fix" the test.
- Do not push. When done, summarize via `git log --oneline main..HEAD` + a one-line "what I changed" per commit, and ask whether to open a PR or merge directly.

**Out of scope.** P1/P2 fixes, new features, refactors beyond the specific finding, ROADMAP changes, scope expansion from one finding into "while I'm here" cleanups.
