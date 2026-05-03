# P17-T25: myPay Browser Connector Foundation

## Context

The app already understands myPay RAS PDFs once the user manually drops one
into the Documents page. The remaining gap is retrieval: myPay should become a
live document source that can log in, reach the RAS document area, download the
latest PDF, and ingest it through the same parser-backed document pipeline.

The desired endstate is full automation:

1. Browser connector fills username/password through the same credential flow
   used by the other connectors.
2. myPay sends the second factor by email to Gmail.
3. A local Gmail OAuth OTP provider reads only recent myPay/DFAS challenge
   messages, extracts the code, and supplies it to the connector.
4. The connector downloads the RAS PDF and ingests it without manual upload.

This prompt is the first slice, not the Gmail OAuth slice. Build the connector
foundation now with a manual MFA bridge that works temporarily. Plan the code
so a Gmail OAuth OTP provider can replace the manual provider later without
rewriting login, navigation, download, or ingestion.

This task is assigned to **Claude**.

## Workflow And Handoff

Claude owns implementation on a dedicated branch. Codex owns validation and
merge back to clean `main`.

Claude workflow:

1. Start from clean, up-to-date `main`.
2. Create a dedicated branch, suggested name:
   `claude/p17-mypay-browser-connector-foundation`.
3. Run the Graph Context Check before edits:
   `python tools\graphify\query_local.py impact "myPay browser connector RAS PDF ingestion Gmail OAuth OTP"`.
4. Execute this prompt's implementation and verification steps.
5. Update this prompt's `## Outcome` section with what changed, what was
   verified, and what remains for Gmail OAuth OTP automation.
6. Commit the work to the Claude branch. Do not merge.

Commit hygiene:

- Do not work directly on `main`.
- Do not use `--no-verify`.
- Avoid `[v]` or `Verified` in the commit message; Codex will handle roadmap
  completion status during validation/merge.
- Do not edit `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`; Codex updates
  those after validating and merging.
- Do not delete branches, rewrite unrelated work, or touch user changes.

Codex validation/merge workflow after Claude finishes:

1. Review Claude's branch diff against current clean `main`.
2. Run the appropriate tests/checks from this prompt.
3. Inspect for credential, PDF, token, email, screenshot, and PII leakage.
4. Merge only after the branch is clean and verification is acceptable.
5. Update roadmap/archive status as part of the merge pass.

## Multi-Agent Coordination

Claude owns only this responsibility/write set unless the user redirects:

- `extractors/mypay_connector.py`
- `extractors/__init__.py`
- `extractors/selector_registry.yaml`
- `config/refresh_policy.yaml`
- A small MFA/OTP provider abstraction if needed, likely under `extractors/`
- A shared document-ingest helper if needed to avoid duplicating router logic
- `backend/result_writer.py` and/or `backend/automation_worker.py` only if the
  connector result needs a new document-ingest persistence path
- `backend/routers/documents.py` only for a narrow refactor to share existing
  document upload/commit behavior
- `docs/COMMANDS.md` if a new command shape should be documented
- `docs/data-lineage/events.yaml`
- `docs/data-lineage/lineage/document_upload_commit.yaml` if the live document
  commit path changes
- Targeted tests, likely `tests/test_mypay_connector.py`,
  `tests/test_document_connector_ingest.py`, or adjacent document-drop tests
- This prompt's `## Outcome` section

Do **not** edit these files in this branch:

- `docs/ROADMAP.md`
- `docs/ROADMAP_ARCHIVE.md`
- Number-trust proof scripts or registry files
- Fidelity or TSP connector files except for read-only comparison
- Gmail OAuth implementation files beyond a stub/interface note, if any

If a working implementation appears to require broad refresh-orchestrator,
credential-broker, or frontend redesign, stop and write a short note in the
prompt outcome explaining the blocker instead of widening the branch.

## Starting State

- `dal/parsers/mypay_ras.py` is parser truth for myPay RAS PDFs.
- `dal/document_drop.py` registers `MyPayRASParser` for document recognition.
- `backend/routers/documents.py` implements manual upload and commit:
  upload/stage, parse preview, commit, update `document_drops`, then run the
  post-commit pipeline for `mypay_ras -> mypay`.
- `frontend/src/components/DocumentDrop.tsx` is the current manual PDF path.
- `backend/mfa_bridge.py`, `backend/routers/mfa.py`, and
  `frontend/src/components/MFAModal.tsx` already support dashboard/manual MFA
  code entry.
- `skills/institution_connector.py` is the connector lifecycle base class.
- `run_all.py` and `backend/automation_worker.py` instantiate connectors from
  `extractors.CONNECTOR_REGISTRY`.
- `backend/result_writer.py` currently treats `result.files` as transaction
  CSVs. A myPay PDF must not be accidentally passed through that CSV path.
- `dal/freshness.py` already lists `mypay` as a tier-3 document source with a
  monthly-style freshness expectation. This task should move behavior toward a
  connector-driven source without breaking existing document-drop nudges.
- `raw_exports/` content is untracked local data. Do not commit downloaded
  PDFs, email messages, tokens, or screenshots.

Graph context at prompt-authoring time pointed at:

- `dal/parsers/mypay_ras.py`
- `dal/document_drop.py`
- `backend/routers/documents.py`
- `backend/mfa_bridge.py`
- `frontend/src/components/MFAModal.tsx`
- `skills/institution_connector.py`
- `extractors/tsp_connector.py`
- `extractors/fidelity_connector.py`
- `backend/result_writer.py`
- `docs/data-lineage/lineage/document_upload_commit.yaml`
- `tests/test_t04_mypay.py`
- `tests/test_document_drop_trust.py`

Treat Graphify as advisory only. Live code and tests are executable truth.

## Task

Build a usable myPay connector foundation with manual MFA fallback and
parser-backed PDF ingestion.

Required behavior:

1. Create and register a myPay connector.
   - Add `extractors/mypay_connector.py` as an `InstitutionConnector`
     subclass.
   - Register `"mypay"` in `extractors/__init__.py`.
   - Add conservative refresh policy metadata for `mypay` in
     `config/refresh_policy.yaml`; monthly/720-hour cadence is a reasonable
     default for RAS documents unless live testing proves otherwise.
   - The connector should work even though myPay is document/payroll oriented
     and may not have normal account configs.

2. Implement username/password login.
   - Use broker credentials when provided.
   - Preserve Password Manager/manual fallback behavior where the base
     lifecycle expects it.
   - Add selectors to `extractors/selector_registry.yaml` when selectors are
     known. Prefer verified selectors over guesses.
   - Do not log usernames, passwords, real account identifiers, or challenge
     bodies.

3. Implement manual MFA bridge as the temporary path.
   - Detect the myPay second-factor code screen or post-login state.
   - Broadcast `sse_topics.MFA_REQUIRED` with institution `"mypay"` when a
     code is needed.
   - Call `backend.mfa_bridge.wait_for_code("mypay", ...)`, fill the code, and
     submit it.
   - If the selected factor is a phone authenticator app or push approval with
     no code field, fall back to polling for post-login state and tell the user
     to complete the approval in the browser.
   - Set `_mfa_prompted = True` only when the connector actually waits for
     user action.
   - Time out cleanly and return a connector error rather than hanging.

4. Plan for Gmail OAuth OTP automation without implementing it yet.
   - Introduce a small extension point only if it makes the current connector
     cleaner. For example, a minimal provider interface can expose
     `wait_for_code(institution, challenge_started_at, hint) -> str | None`.
   - The current provider should use the manual MFA bridge.
   - Leave a clear follow-on note for a Gmail OAuth provider.
   - Do not implement Gmail OAuth, IMAP polling, Gmail browser scraping, token
     persistence, or inbox access in this branch.
   - The follow-on Gmail provider should eventually use least-privilege Gmail
     OAuth, store tokens only in local gitignored/keyring-backed storage, query
     only recent messages from the myPay/DFAS sender window, and redact OTPs in
     logs.

5. Navigate to the RAS document and download the latest PDF.
   - Use the authenticated myPay session to reach the RAS/statement document
     area.
   - Download the latest available RAS PDF into `raw_exports/mypay/` or another
     gitignored raw-export location.
   - Use sanitized, deterministic-enough filenames such as
     `mypay_ras_<YYYY-MM>_<timestamp>.pdf` when the pay period is knowable.
   - Handle "no new RAS available" distinctly from login/MFA/download failure.
   - Do not commit real PDFs or raw downloaded files.

6. Ingest the downloaded PDF through the existing parser-backed path.
   - Use `MyPayRASParser` via `dal.document_drop` recognition where practical;
     do not create a second parser.
   - Enforce `ParseResult.can_commit`; parser silent-failure guards must block
     ingestion.
   - Commit the parsed PDF to `payroll_snapshots`.
   - Record a committed `document_drops` row with `parser_type="mypay_ras"`,
     `committed_at`, summary JSON, file size, and owner attribution consistent
     with the manual document-drop path.
   - Trigger or preserve the existing post-commit pipeline behavior for
     institution `"mypay"`.
   - Do not route PDF files through the generic transaction-CSV branch in
     `backend/result_writer.py`.

7. Keep manual document drop working.
   - The `/api/documents/upload` and `/api/documents/commit` path should still
     work for user-dropped RAS PDFs.
   - If you refactor shared document ingest logic, cover both router and
     connector paths with tests.

8. Add tests.
   Cover at least:
   - connector registration for `"mypay"`,
   - manual MFA bridge code fill path without a live myPay site,
   - timeout/error path for MFA,
   - downloaded PDF routing does not enter CSV parsing,
   - parser-backed ingest writes `payroll_snapshots` and committed
     `document_drops`,
   - existing myPay parser tests still pass,
   - manual document-drop behavior still passes.

9. Update docs and lineage only where behavior changed.
   - A new file under `extractors/` requires a lineage/events update per the
     doc-coupling gate.
   - If document commit origin now includes automated myPay connector ingestion,
     update `docs/data-lineage/lineage/document_upload_commit.yaml`.
   - Add a concise command note to `docs/COMMANDS.md` if useful for running
     just myPay.

Implementation notes:

- Prefer local-first, dependency-light code.
- Use existing connector lifecycle, browser profile, credential broker, MFA
  bridge, and document parser abstractions.
- Keep connector failures isolated; a myPay failure must not take down other
  institutions during refresh.
- Do not add cloud persistence, telemetry, external OTP services, or Gmail
  access in this branch.
- Do not store credentials, OAuth tokens, raw emails, OTPs, real PDFs, or
  screenshots in committed files.
- Redact OTPs and sensitive filenames in logs.
- Do not change `dal/parsers/mypay_ras.py` unless live PDF shape requires a
  small parser hardening. Parser changes need targeted tests.

## Verification

Minimum static and unit verification:

```powershell
python -m py_compile extractors\mypay_connector.py backend\result_writer.py backend\routers\documents.py
python -m pytest tests\test_t04_mypay.py tests\test_t02_document_drop.py -q
python -m pytest tests\test_mypay_connector.py tests\test_document_connector_ingest.py -q
```

Adjust the test filenames if the implementation places coverage in adjacent
existing files.

If shared document-ingest or result-writer behavior changes:

```powershell
python -m pytest tests\test_document_drop_trust.py tests\test_payroll.py tests\test_payroll_flow.py -q
python -m pytest tests\test_result_writer_investment.py -q
```

If the refresh worker/orchestrator path changes:

```powershell
python -m pytest tests\test_refresh_orchestrator.py tests\test_dal.py -q
```

Targeted search checks:

```powershell
rg -n "mypay|mypay_ras|MFA_REQUIRED|wait_for_code|document_drops|payroll_snapshots" extractors backend dal tests docs
rg -n "gmail|oauth|token|imap|otp" extractors backend docs tests
```

Manual/dev verification when credentials and MFA are available:

```powershell
$env:SENTRY_DB_PATH = "$PWD\data\dummy.db"
$env:SENTRY_DB_MODE = "trusted"
python run_all.py --institutions mypay --force --dev
```

Expected manual/dev result:

1. Connector logs in or reuses a session.
2. If challenged, dashboard/manual MFA flow accepts the code or browser
   approval.
3. Connector downloads the latest RAS PDF.
4. The PDF parses as `mypay_ras`.
5. `payroll_snapshots` contains/updates the pay period from the PDF.
6. `document_drops` has a committed `mypay_ras` row for the download.
7. The post-commit pipeline for `mypay` runs or is explicitly reported as
   skipped/non-fatal.

If live myPay cannot be completed because of credentials, MFA setup, or site
availability, leave the code unit-tested and record the exact live blocker in
`## Outcome`.

## Done Criteria

- `mypay` is a registered connector.
- Username/password login is implemented using the existing credential flow.
- Manual MFA bridge works as the temporary route for email/app code entry.
- The connector downloads the latest RAS PDF when authenticated.
- Downloaded PDFs are parsed and ingested through the existing myPay parser
  semantics.
- PDF ingestion records both `payroll_snapshots` and committed
  `document_drops`.
- Generic CSV ingestion is not invoked for myPay PDFs.
- Manual document drop remains functional.
- Tests cover the connector foundation and document-ingest routing.
- The prompt outcome explicitly names the Gmail OAuth OTP follow-on and any
  live-site selector/MFA blockers.

## Follow-On: Gmail OAuth OTP Automation

Do not implement this follow-on in P17-T25. Capture enough design notes so the
next prompt can be written without re-discovering the boundary.

Expected next slice:

- Create a Gmail OAuth setup command or local settings flow.
- Request the narrowest practical Gmail read scope.
- Store OAuth client/token material outside tracked files, preferably keyring
  or a gitignored local config path.
- Poll only messages newer than the challenge start time.
- Filter to myPay/DFAS sender and subject/body hints.
- Extract only the OTP code and discard message content.
- Redact code and message details in logs.
- Fall back to the manual MFA bridge on OAuth failure, no matching email,
  ambiguous multiple codes, or timeout.

## Outcome

Implemented on `claude/p17-mypay-browser-connector-foundation`.

### 2026-05-03 Codex review feedback — addressed (commit forthcoming)

Codex flagged three issues; all three are fixed in the follow-up commit:

1. **F1 — auth-state detection (hard blocker, fixed).**
   The base-class `_is_post_login` / `_is_session_valid` would treat
   the public `https://mypay.dfas.mil/` landing page as authenticated
   because the URL contains no login keywords and the marketing copy
   includes dashboard-like words ("Account", "Welcome"). myPay-specific
   overrides now require **positive** post-login markers:

   * `_UNAUTH_URL_HINTS` (login / signin / challenge / mfa / verify /
     otp / passwordreset / forgot / register) short-circuit to False.
   * `_POST_LOGIN_URL_HINTS` (`/retireepay`, `/ras`, `/myaccount`,
     `/dashboard`) short-circuit to True.
   * Otherwise, a visible Logout / Sign Out / "Retiree Account
     Statement" / "View RAS" / `href*="logout"` / `href*="RetireePay"`
     element must be present.

   `_is_session_valid` now navigates to `export_url`, applies the
   strict `_is_post_login` check, and returns False when no positive
   markers are visible. Five regression tests pin the contract:
   `test_is_post_login_rejects_public_landing_page`,
   `test_is_post_login_rejects_login_url_even_with_dashboard_text`,
   `test_is_post_login_accepts_post_login_url`,
   `test_is_post_login_accepts_visible_logout_link`,
   `test_is_session_valid_rejects_public_landing_page`,
   `test_is_session_valid_accepts_authenticated_session`.

2. **F2 — RAS-only guard now runs ahead of any DB write (hard blocker, fixed).**
   The previous `ingest_ras_pdf` ran the full
   `ingest_document` (which staged bytes, INSERTed `document_drops`,
   called `parser.commit`, and dispatched the post-commit pipeline)
   THEN checked `outcome.parser_type`. A misclassified file (e.g. a
   TSP statement that the parser bucket happily recognizes as
   `tsp_statement`) would have written `investment_holdings` /
   `portfolio_snapshots` rows under `mypay`'s name before the check
   fired.

   The shared helper now accepts `expected_parser_type` and runs the
   pre-stage `get_parser` check FIRST. On mismatch, it raises
   `RecognitionError` before ANY of: byte staging, `document_drops`
   INSERT, `parser.parse`, `parser.commit`, `resolve_owner_id`, or
   `run_post_commit_pipeline`. `ingest_ras_pdf` calls
   `ingest_document(..., expected_parser_type="mypay_ras")`. New test
   `test_ingest_ras_pdf_refuses_recognized_non_ras_before_db_write`
   wires a fake `tsp_statement` parser whose `.parse` / `.commit` /
   `.resolve_owner_id` raise on call, and verifies that
   `document_drops`, `payroll_snapshots`, and the pipeline dispatch
   list are all empty after the refusal.

3. **F3 — push-approval / phone-app MFA now surfaces as prompted (fixed).**
   When no code-input field renders after login, the connector now
   broadcasts `MFA_REQUIRED` with prompt text that tells the user to
   approve the sign-in in the browser tab or authenticator app, sets
   `_mfa_prompted = True`, and THEN polls for post-login state via
   the base lifecycle. Previously this branch silently fell back to
   the base poll without surfacing anything to the dashboard. The
   broadcast is wrapped in a `try/except` so a missing SSE bus
   degrades to silent polling rather than crashing the connector.
   New test `test_wait_for_mfa_no_code_field_broadcasts_push_approval`
   pins the exact event shape and the prompt content ("approve" plus
   "browser" or "app").

All review-feedback fixes verified:

```
python -m pytest tests/test_mypay_connector.py tests/test_document_connector_ingest.py -q
# 25 passed (17 original + 8 new regression tests)

python -m pytest tests/test_t04_mypay.py tests/test_t02_document_drop.py \
    tests/test_document_drop_trust.py tests/test_payroll.py \
    tests/test_payroll_flow.py tests/test_result_writer_investment.py \
    tests/test_refresh_orchestrator.py tests/test_dal.py \
    tests/test_document_drops.py -q
# 79 passed, 2 skipped
```

---

### Initial implementation (cf5b503)

### What changed

- **`extractors/mypay_connector.py` (new)** — `MyPayConnector(InstitutionConnector)`
  with `institution="mypay"`, `display_name="myPay (DFAS)"`,
  `login_url=https://mypay.dfas.mil/`. Implements `_perform_login`
  (broker creds + Password Manager fallback), `_wait_for_mfa`
  (delegates to an `OTPProvider`, sets `_mfa_prompted=True` only
  when actually waiting), `_navigate_to_ras` + `_download_latest_ras`
  (heuristic link probing for Retiree Account Statement → expect_download
  → save to `raw_exports/mypay/mypay_ras_<YYYY-MM>_<timestamp>.pdf`),
  `_trigger_export` (downloads + ingests via the shared helper, uses
  a `_marker_no_new_ras` synthetic balance entry to satisfy the
  lifecycle's "no data" branch when nothing new is available without
  writing a real `balance_snapshots` row), and `_perform_logout`. A
  module-level `ingest_ras_pdf(filename, content)` exposes the ingest
  routing for tests and refuses non-`mypay_ras` parser types as a
  defense-in-depth guard.
- **`extractors/otp_provider.py` (new)** — Small `OTPProvider` ABC with
  one method, `wait_for_code(institution, *, challenge_started_at,
  hint, timeout_seconds)`. Ships `ManualMFABridgeOTPProvider` (today's
  default) which broadcasts `sse_topics.MFA_REQUIRED` and routes to
  `backend.mfa_bridge.wait_for_code`. Module docstring captures the
  Gmail OAuth follow-on contract (least-privilege scope, gitignored
  token storage, sender/window filters, OTP-only extraction with
  redacted logs, manual fallback on every failure mode).
- **`extractors/__init__.py`** — `mypay` registered in
  `CONNECTOR_REGISTRY`; `MyPayConnector` re-exported.
- **`extractors/selector_registry.yaml`** — New `mypay` group with
  conservatively seeded login / MFA / RAS / logout selectors. They
  have NOT been validated against a live myPay session (see
  blockers below); the AI backstop / DOM Healer firms them up on the
  first real run.
- **`config/refresh_policy.yaml`** — `mypay` entry: 720h cadence
  (matches the existing tier-3 monthly RAS expectation in
  `dal/freshness.py`), 1 retry with a 1-hour backoff, `mfa_expected:
  email`, `extraction_method: document`, fatal-vs-retryable error
  buckets aligned with TSP.
- **`backend/document_ingest.py` (new)** — Shared upload-then-commit
  helper. `stage_document` mirrors the upload half (recognize, parse,
  stage in `raw_exports/document_drop`, INSERT `document_drops` with
  `committed_at IS NULL` and `summary_json={file_id, staged: true}`).
  `commit_staged_document` mirrors the commit half (re-parse, enforce
  `can_commit`, parser commit, UPDATE `document_drops` with
  `committed_at` + final `summary_json` + re-stamped `owner_id`).
  `ingest_document` is the connector-friendly one-shot wrapper.
  Public `RecognitionError` and `ParseBlockedError` keep the router's
  HTTP 422 / 409 mapping intact. `PARSER_INSTITUTION_MAP` is the
  canonical mapping previously inlined in the router; the connector
  path imports it so `mypay_ras` always fires the post-commit
  pipeline for `"mypay"`.
- **`backend/routers/documents.py`** — Refactored to call
  `stage_document` / `commit_staged_document` from the helper. No
  observable behavior change: same response shapes, same HTTP codes,
  same staging directory, same `summary_json` shape, same
  `PARSER_INSTITUTION_MAP` post-commit dispatch. Existing tests
  (`tests/test_t02_document_drop.py`,
  `tests/test_document_drops.py`,
  `tests/test_document_drop_trust.py`) continue to pass.
- **`backend/result_writer.py`** — Two narrow guards:
  1. `result.balances` filtered to entries whose key does not start
     with `_marker` so connector-side no-data sentinels (myPay's
     `_marker_no_new_ras`) never reach `record_balance` /
     `get_latest_balances`.
  2. `result.files` filtered to `.csv` suffix before the
     `pd.read_csv` loop. PDFs (or any other non-CSV the
     connector might emit) are logged and skipped — they cannot
     enter the transaction-CSV branch and therefore cannot raise
     a `csv_parse_failure` notification.
- **`docs/data-lineage/lineage/document_upload_commit.yaml`** — Origin
  rewritten to describe both manual and connector entry points and
  to point at the new `backend/document_ingest.py` as the shared
  helper.
- **`docs/data-lineage/events.yaml`** — `document_upload_commit`
  description / primary_origin updated to mention the connector path.
- **`docs/COMMANDS.md`** — New snippet showing the dev/manual
  invocation `python run_all.py --institutions mypay --force --dev`.
- **Tests (new)** —
  - `tests/test_mypay_connector.py` — connector registry
    membership, factory class identity, default OTP provider
    identity, MFA fill-and-submit happy path (stub provider), MFA
    end-to-end via the real `backend.mfa_bridge`, MFA timeout
    returns False (with `_mfa_prompted=True`), MFA session-reuse
    skips the provider, `result_writer` skips PDF entries (with
    a `pd.read_csv` sentinel that explodes if invoked),
    `result_writer` still processes CSV entries, `result_writer`
    skips `_marker_*` balance sentinels.
  - `tests/test_document_connector_ingest.py` — `ingest_document`
    writes both `payroll_snapshots` AND a committed
    `document_drops` row from a parser-backed RAS PDF; the
    `mypay_ras` parser_type triggers the post-commit pipeline
    for `"mypay"` (via the shared helper); recognition failure
    raises `RecognitionError`; the silent-failure guard surfaces
    as `ParseBlockedError` with no `payroll_snapshots` write;
    `ingest_ras_pdf` refuses non-RAS PDFs;
    `stage_document` writes a pending `document_drops` row with
    `committed_at IS NULL` and the canonical
    `summary_json={"file_id", "staged": true}` shape.

### What was verified

```
python -m py_compile extractors/mypay_connector.py \
    extractors/otp_provider.py extractors/__init__.py \
    backend/document_ingest.py backend/result_writer.py \
    backend/routers/documents.py
# OK

python -m pytest tests/test_t04_mypay.py tests/test_t02_document_drop.py -q
# 36 passed, 2 skipped

python -m pytest tests/test_mypay_connector.py tests/test_document_connector_ingest.py -q
# 17 passed

python -m pytest tests/test_document_drop_trust.py tests/test_payroll.py \
    tests/test_payroll_flow.py tests/test_result_writer_investment.py -q
# 23 passed

python -m pytest tests/test_refresh_orchestrator.py tests/test_dal.py -q
# 17 passed

python -m pytest tests/ -q --ignore=tests/test_failure_modes.py
# 587 passed, 2 skipped, 2 failed — both failures pre-exist on
# clean main and are unrelated to this task:
#   - tests/test_notifications_producers.py::test_bill_overdue_emits_notification
#     (date-sensitive bill window assertion)
#   - tests/test_trusted_seed.py::test_trusted_seed_repeats_full_db_fingerprint
#     (trusted-seed fingerprint pin drifted from a prior change)
# Confirmed by running the same two cases on clean main with the
# branch's changes stashed — both still fail there.
```

Targeted ripgrep checks:

- `rg "mypay|mypay_ras|MFA_REQUIRED|wait_for_code|document_drops|payroll_snapshots" extractors backend dal tests docs`
  surfaces the new connector + helper + tests + lineage updates
  alongside existing mypay parser surfaces; no spurious hits.
- `rg -i "gmail|oauth|imap|otp" extractors backend docs tests` surfaces
  ONLY documentation-style references in `extractors/otp_provider.py`
  and `extractors/mypay_connector.py` describing the Gmail OAuth
  follow-on. No Gmail OAuth, IMAP polling, browser scraping, token
  persistence, or inbox access is implemented in this branch.

### What remains (live blockers)

A live `python run_all.py --institutions mypay --force --dev` walk-through
was NOT performed in this branch. Blockers, in order of how likely they
are to need attention before the connector lights up green for real:

1. **Selectors are unverified.** `extractors/selector_registry.yaml`
   `mypay.login.username/password/submit`, `mypay.mfa.code_input/
   submit`, `mypay.ras.section_link/download_button`, and
   `mypay.logout.signout_link` were seeded from public DFAS
   conventions, not a real DOM dump. The AI backstop / DOM Healer
   should heal these on the first successful run, but the user may
   need to manually log in and capture the DOM if the form ids
   diverge significantly. Suggested first-run action: launch
   `--dev` mode and run with broker creds preloaded so the browser
   stays open and a screenshot can be captured for selector
   pinning.
2. **myPay's actual MFA factor menu has not been observed.** The
   connector handles the email-OTP path (the documented default for
   DFAS retiree accounts) and gracefully falls back to the base
   lifecycle's post-login polling for push-approval factors. If
   the live account is configured for SMS-only, an SMS adapter
   similar to the TSP `extractors.sms_otp` Phone-Link bridge would
   slot into the same `OTPProvider` seam.
3. **No accounts.yaml entry for myPay yet.** The connector tolerates
   an empty account list and the parser already handles owner
   attribution on its own, but adding a `mypay:` block with a
   placeholder `last4` would let the freshness dashboard count
   active accounts. This was deliberately deferred — the prompt
   said myPay "may not have normal account configs" so the
   foundation works without one.
4. **Tier promotion deferred.** `dal/freshness.py` still classifies
   `mypay` as tier 3 (document drop) with a 720h refresh
   expectation. Promotion to tier 2 should follow a successful
   live run; doing it speculatively would make the freshness pill
   blink "stale" until the connector actually succeeds.

### Follow-on: Gmail OAuth OTP automation

Captured for the next prompt — NOT implemented here. The
`OTPProvider` ABC in `extractors/otp_provider.py` is the seam: the
follow-on slice swaps `default_provider()` to return a
`GmailOAuthOTPProvider` while leaving login / navigation / download
/ ingest in `MyPayConnector` untouched. Design contract from the
prompt is preserved verbatim in `extractors/otp_provider.py`'s module
docstring (least-privilege Gmail scope, keyring/gitignored token
store, post-`challenge_started_at` window filter, sender + subject
hint filters, OTP-only extraction with redacted logs, manual fallback
on every failure mode). No Gmail OAuth, IMAP, browser scraping, token
persistence, or inbox access of any kind landed in this branch.
