# Ops: Dependabot Triage — 2026-04-18

## Context

23 open Dependabot alerts on `main` as of 2026-04-18: 1 critical, 8 high,
14 moderate. Sentry Finance is a local-first Tauri desktop app (no
remote prod deployment, no CI/CD), so server-side CVEs are materially
less urgent than RCE-in-build-chain types. This doc is a prioritized
triage; **no bumps were performed in this session**.

Alert list source: `gh api /repos/wileyqe/Sentry-Finance/dependabot/alerts?state=open`.

## Starting State

- Python deps: `requirements.in` → pip-compiled `requirements.txt` (Python 3.14)
- Frontend deps: `frontend/package.json` + `frontend/package-lock.json` (npm)
- Installed versions pulled from `package-lock.json` directly (node_modules
  not present in this worktree)
- Nothing in Dependabot has been dismissed or suppressed

## Key findings (headline)

1. **`litellm` is dead code.** Listed in `requirements.in` and pinned
   `<=1.82.6`, but **not imported anywhere** in `backend/`, `dal/`,
   `extractors/`, or `scripts/`. Removing it closes the only
   **critical** alert plus 2 of the 8 highs. Highest-leverage single fix.
2. **Most npm alerts are dev-chain only.** The `shadcn` CLI tool is
   listed in `dependencies` (it should be in `devDependencies`) and
   drags in `@modelcontextprotocol/sdk` (→ `hono`, `@hono/node-server`),
   `msw`, and `express` (→ `router` → `path-to-regexp`). None of these
   ship in the Tauri bundle — they only exist at dev time for component
   scaffolding.
3. **Only two frontend packages reach the shipped bundle** from the
   alert list: `lodash` (via `recharts`) and the Vite-chain glob libs
   only when running `vite dev`. Practical exploit surface is limited —
   Sentry renders only trusted local data.

## Alert-by-alert table

Columns: `#` = alert number, `Sev` = Dependabot severity, `CVSS` = advisory
CVSS (0.0 means unscored in the advisory, not harmless), `Eco` = ecosystem,
`Installed` = current version in lockfile / requirements.txt, `Fix` = first
patched version, `Scope` = where it actually runs, `Reach` = whether this
code path is exercised in the shipped app.

| #  | Sev      | CVSS | Eco | Package             | Installed | Fix       | Scope / parent chain                               | Reach                                         |
|----|----------|------|-----|---------------------|-----------|-----------|----------------------------------------------------|-----------------------------------------------|
| 21 | critical | 0.0  | pip | `litellm`           | 1.82.6    | 1.83.0    | runtime (listed in `requirements.in`)              | **Dead** — no imports anywhere                |
| 22 | high     | 0.0  | pip | `litellm`           | 1.82.6    | 1.83.0    | same                                               | **Dead**                                      |
| 20 | high     | 0.0  | pip | `litellm`           | 1.82.6    | 1.83.0    | same                                               | **Dead**                                      |
| 23 | moderate | 0.0  | pip | `cryptography`      | pinned    | 46.0.7    | runtime                                            | Used by `backend/credential_broker.py` (keyring path) — reaches prod |
| 9  | high     | 8.1  | npm | `lodash`            | 4.17.23   | 4.18.0    | runtime (transitive via `recharts`)                | Ships in Tauri bundle; no `_.template` calls from app — indirect     |
| 8  | moderate | 6.5  | npm | `lodash`            | 4.17.23   | 4.18.0    | same                                               | Same — prototype pollution via `_.unset/_.omit`; not user-reachable  |
| 11 | high     | 0.0  | npm | `vite`              | 7.3.1     | 7.3.2     | dev (dev server only)                              | Dev-only; exposed only while `npm run tauri dev` is running          |
| 10 | high     | 0.0  | npm | `vite`              | 7.3.1     | 7.3.2     | dev                                                | Dev-only                                      |
| 12 | moderate | 0.0  | npm | `vite`              | 7.3.1     | 7.3.2     | dev                                                | Dev-only                                      |
| 6  | high     | 7.5  | npm | `path-to-regexp`    | 6.3.0     | 8.4.0     | transitive via `shadcn` → `@modelcontextprotocol/sdk` → `msw`; also `express/router` | **Dev-chain only** — shadcn CLI + msw are not in the Tauri bundle |
| 7  | moderate | 5.9  | npm | `path-to-regexp`    | 6.3.0     | 8.4.0     | same                                               | **Dev-chain only**                            |
| 2  | high     | 7.5  | npm | `picomatch`         | 4.0.3     | 4.0.4     | transitive via `vite`, `tinyglobby`, `fdir`        | Dev/build only                                |
| 1  | high     | 7.5  | npm | `picomatch`         | 2.3.1     | 2.3.2     | transitive via `anymatch`, `micromatch`, `readdirp`| Dev/build only                                |
| 4  | moderate | 5.3  | npm | `picomatch`         | 2.3.1     | 2.3.2     | same                                               | Dev/build only                                |
| 3  | moderate | 5.3  | npm | `picomatch`         | 4.0.3     | 4.0.4     | same                                               | Dev/build only                                |
| 5  | moderate | 6.5  | npm | `brace-expansion`   | 5.0.4     | 5.0.5     | transitive via `minimatch`                         | Dev/build only                                |
| 14 | moderate | 5.3  | npm | `hono`              | 4.12.7    | 4.12.12   | transitive via `shadcn` → `@modelcontextprotocol/sdk` | **Dev-chain only** — we don't run a hono server |
| 15 | moderate | 0.0  | npm | `hono`              | 4.12.7    | 4.12.12   | same                                               | Dev-chain only                                |
| 16 | moderate | 5.3  | npm | `hono`              | 4.12.7    | 4.12.12   | same                                               | Dev-chain only                                |
| 17 | moderate | 0.0  | npm | `hono`              | 4.12.7    | 4.12.12   | same                                               | Dev-chain only                                |
| 18 | moderate | 4.8  | npm | `hono`              | 4.12.7    | 4.12.12   | same                                               | Dev-chain only                                |
| 19 | moderate | 4.3  | npm | `hono`              | 4.12.7    | 4.12.14   | same                                               | Dev-chain only                                |
| 13 | moderate | 5.3  | npm | `@hono/node-server` | 1.19.11   | 1.19.13   | transitive via same `shadcn` chain                 | Dev-chain only                                |

## Already mitigated / non-reachable

- **`litellm` (#20, #21, #22)** — no import in backend/dal/extractors/scripts.
  The dep was added speculatively for an AI backstop but never wired up.
  The pin `litellm<=1.82.6` explicitly blocks the patched 1.83.0 line, so
  the fix must be either **remove the dep entirely** (preferred) or bump
  the pin to `<=1.83.0`.
- **All `hono` + `@hono/node-server` alerts** — we do not run a hono
  server. The package enters the tree only via the `shadcn` CLI's MCP
  integration, which is a dev-time scaffolder. Zero runtime exposure.
- **`path-to-regexp` alerts** — same story (shadcn → msw, shadcn → express).
  msw is a browser-mock library; Sentry's frontend doesn't import it.
- **`picomatch` / `brace-expansion` alerts** — all reachable only during
  `vite build` / `vite dev`. ReDoS on glob patterns we author ourselves
  is not a realistic threat model for a single-developer local build.
- **`lodash` code injection (#9, CVSS 8.1, GHSA-r5fr-rjxr-66jc)** —
  the vuln is in `_.template` with untrusted input keys. `recharts` does
  not call `_.template`, and the app only feeds lodash with its own
  trusted shapes (chart data, axis configs). Residual risk is limited to
  any future code path that does pass user-controlled objects into
  lodash utilities — low today, worth closing anyway.

## Recommended bump order

### Priority 1 — runtime, high leverage (do first)

1. **Delete `litellm` from `requirements.in`.** Re-run
   `pip-compile --generate-hashes requirements.in` to refresh
   `requirements.txt`. Verify with `ruff check` and the full backend
   suite. **Closes 1 critical + 2 highs in one line.**
   - Compat: none — the package isn't imported.
   - If we ever want an LLM backstop again, `google-genai` is already
     in `requirements.in` and can cover that use case.

2. **Bump `cryptography` to `>=46.0.7`.** Patch-level bump; stable API.
   Verify `credential_broker.py` still stores/retrieves via keyring
   end-to-end.
   - Compat: cryptography 46.x supports Python 3.9+, so the 3.14 pin
     is safe.

### Priority 2 — dev server exposure (do second)

3. **Bump `vite` to `^7.3.2`** in `frontend/package.json` and
   `npm install` to update the lock. Patch-level bump inside the 7.x
   line — no breaking changes expected. Verify `npm run build` and
   `npm run tauri dev`.
   - Compat: `@vitejs/plugin-react` 4.6 already supports vite 7.x.
   - **Closes 2 highs + 1 moderate.**

### Priority 3 — shipped-bundle frontend runtime (do third, lower practical risk)

4. **Force-resolve `lodash` to `^4.18.0` via npm `overrides`** in
   `frontend/package.json`:
   ```json
   "overrides": { "lodash": "^4.18.0" }
   ```
   Then `npm install`, `npm run build`, and a smoke-test of a chart-heavy
   page (Investments tab, Cash Flow) — recharts is the only consumer and
   should not notice. **Closes 1 high + 1 moderate.**
   - Compat: 4.17 → 4.18 is a minor bump; API is unchanged. If recharts
     pins lodash in a way that overrides can't satisfy, fall back to
     `npm-force-resolutions` or a `package.json` `resolutions` override
     (Tauri/Vite respect both).

### Priority 4 — dev-only bulk bump (do fourth, low risk)

5. **Single bulk-bump PR for all remaining dev-chain alerts.** Add
   `overrides` entries to `frontend/package.json` (npm 8.3+ native,
   no extra tooling):
   ```json
   "overrides": {
     "lodash": "^4.18.0",
     "hono": "^4.12.14",
     "@hono/node-server": "^1.19.13",
     "path-to-regexp": "^8.4.0",
     "picomatch": "^4.0.4",
     "brace-expansion": "^5.0.5"
   }
   ```
   Note: `picomatch@2.x` consumers (`anymatch`, `readdirp`) won't
   accept `^4.0.4`; they need `^2.3.2` in a separate override path, or
   left alone since they're fully dev-time. Easiest: let dual versions
   coexist and just pin each major:
   ```json
   "overrides": {
     "picomatch@2": "^2.3.2",
     "picomatch@4": "^4.0.4",
     ...
   }
   ```
   Verify `npm run build` + `npm run tauri dev` + `npm ls` no-peer-warnings.
   **Closes the remaining 2 highs + 11 moderates in one PR.**

### Optional hygiene (not required, but worth it)

6. **Move `shadcn` from `dependencies` → `devDependencies`** in
   `frontend/package.json`. It's a CLI scaffolder, not a runtime
   library. This doesn't change what ships (Vite already tree-shakes
   it), but it reduces noise in future Dependabot runs because `npm
   audit --production` will filter it out.

## Version-compat notes / risks

- **Python 3.14**: `cryptography` 46.0.7 is fine. `litellm` removal
  sidesteps the 3.14-compat question entirely.
- **`pip-compile --generate-hashes`**: must be re-run after any
  `requirements.in` edit — do NOT hand-edit `requirements.txt`.
- **npm `overrides` vs. `resolutions`**: this project uses npm (not
  yarn/pnpm), so native `overrides` is correct. Tauri's `beforeBuildCommand`
  uses whatever `npm run build` resolves.
- **`recharts` + lodash override**: recharts 3.8 declares `lodash: "^4.17.21"`,
  so `^4.18.0` satisfies the range. No patch needed.
- **`shadcn` chain**: if the override on `path-to-regexp: "^8.4.0"`
  breaks `express` (which peer-depends on `router` which peer-depends on
  `path-to-regexp@^8`), we'd need to scope the override or just accept
  that shadcn itself is dev-only and skip it. Alternative: remove
  `shadcn` from package.json entirely and use `npx shadcn@latest` ad-hoc
  when scaffolding a component.

## Verification checklist (for the follow-up bump session)

After each priority block:

- [ ] `ruff check backend dal extractors tests`
- [ ] `pytest tests/ -x --tb=short` — full backend suite
- [ ] `cd frontend && npm run build` — frontend build
- [ ] `cd frontend && npm run tauri dev` — smoke-test the running app
- [ ] Revisit Dependabot alerts page — expected alert counts after each:
  - After P1: 23 → 19 (closed #20, #21, #22, #23)
  - After P2: 19 → 16 (closed #10, #11, #12)
  - After P3: 16 → 14 (closed #8, #9)
  - After P4: 14 → 0

## Follow-ups / open questions for the user

1. **Keep `litellm` removed, or add an AI backstop plan?** If the plan
   is to eventually wire it up, re-adding it later when actually needed
   is cheaper than keeping a vulnerable unused dep on the shelf.
2. **`shadcn` in `dependencies`**: was this intentional, or should it
   move to `devDependencies` / be replaced by `npx shadcn@latest`
   invocations?
3. **Dependabot auto-PR policy**: with no CI, auto-merging dev-only
   bumps is relatively safe but needs a manual `npm run build` + smoke
   before merge. Worth deciding if this project wants auto-PRs enabled
   for patch-level only.

## Outcome

Triage-only session. No code, config, or lockfile changes were made.
Deliverable is this document. User to schedule the four-priority bump
sequence at their own cadence.
