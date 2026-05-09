# P17-T42: myPay Live Selector And MFA Walkthrough

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/64

## Context

P17-T25 shipped the myPay browser connector foundation: login wiring,
manual MFA bridge support, RAS PDF download, and parser-backed ingest
through the existing document-drop pipeline. The branch was intentionally
unit-tested without a live myPay session.

The remaining blocker before building Gmail OAuth OTP automation is live
shape. The connector has conservative selectors for login, MFA, RAS
navigation, download, and logout, but those selectors have not been proven
against a real myPay/DFAS session. The actual MFA factor menu has also not
been observed. This task is the small HITL walkthrough that turns those
unknowns into receipts.

This task is HITL because it may require credentials, live browser
interaction, and MFA approval. Do not attempt unattended credential work.

## Starting State

- `extractors/mypay_connector.py` is merged and registered as `mypay`.
- `extractors/otp_provider.py` exposes the `OTPProvider` seam.
- `extractors/selector_registry.yaml` includes seeded myPay selectors that
  may need live pinning.
- `backend/mfa_bridge.py`, `backend/routers/mfa.py`, and the dashboard MFA
  modal are the current manual second-factor path.
- `backend/document_ingest.py` provides the shared parser-backed ingest path.
- `docs/COMMANDS.md` documents:

```powershell
$env:SENTRY_DB_PATH = "$PWD\data\dummy.db"
$env:SENTRY_DB_MODE = "trusted"
python run_all.py --institutions mypay --force --dev
```

## Task

1. Start from clean, up-to-date `main` on a dedicated branch:
   `codex/p17-t42-mypay-live-selector-mfa-walkthrough`.
2. Run the Graph Context Check before edits:

```powershell
python tools\graphify\query_local.py impact "myPay live selector MFA walkthrough RAS download OTP provider"
```

3. Run the myPay connector in dev mode only with the user present:

```powershell
$env:SENTRY_DB_PATH = "$PWD\data\dummy.db"
$env:SENTRY_DB_MODE = "trusted"
python run_all.py --institutions mypay --force --dev
```

4. Observe the live flow without committing sensitive artifacts:
   - login form selectors,
   - post-login markers,
   - MFA factor menu shape,
   - email-code input and submit selectors, if present,
   - push/app approval behavior, if present,
   - RAS navigation and download selectors,
   - logout selector.
5. If live selectors differ, update only the myPay selector entries and
   tests needed to pin the observed contract. Prefer stable attributes and
   visible text over brittle generated IDs.
6. Confirm whether the connector can download and ingest a RAS PDF. Do not
   commit the downloaded PDF, screenshots, raw emails, OTPs, credentials,
   cookies, tokens, or full DOM dumps.
7. Record the outcome below: what worked, what selectors changed, what MFA
   shape was observed, whether ingest succeeded, and what remains for Gmail
   OAuth OTP automation.

## Non-Goals

- Do not implement Gmail OAuth, IMAP polling, browser Gmail scraping, or token
  persistence.
- Do not change the myPay parser unless a live RAS parse failure requires a
  tiny targeted hardening with tests.
- Do not promote myPay freshness tier until the connector succeeds enough to
  justify the UX consequence.
- Do not commit live PDFs, screenshots, emails, OTPs, account identifiers, or
  credential material.

## Verification

Run the focused unit checks even if the live walkthrough blocks:

```powershell
python -m py_compile extractors\mypay_connector.py extractors\otp_provider.py backend\document_ingest.py
python -m pytest tests\test_mypay_connector.py tests\test_document_connector_ingest.py -q
python -m pytest tests\test_t04_mypay.py tests\test_t02_document_drop.py -q
```

If selector or MFA behavior changed, add or update focused tests for that
behavior. Before commit, run leakage checks:

```powershell
git diff --name-only
rg -n "password|secret|token|otp|code|cookie|session|ras_.*\.pdf|mypay_ras_.*\.pdf" .
git status --short
```

Any hit must be a redacted documentation/test reference or intentionally
gitignored local file. Real live artifacts must not be tracked.

## Done Criteria

- Live myPay login/MFA/RAS selector facts are recorded in this prompt's
  Outcome section.
- Seeded selectors are either confirmed or updated with tests.
- If RAS download and ingest succeeded, the local DB has a committed
  `mypay_ras` document-drop row and `payroll_snapshots` row.
- If live walkthrough could not complete, the exact blocker is recorded.
- Gmail OAuth OTP automation has enough live facts to proceed or a clear
  blocker explaining what is still unknown.

## Outcome

Completed on `codex/p17-t42-mypay-live-selector-mfa-walkthrough`.

Live facts captured with the user present:

- Login fields rendered as `input[name="username"]` and
  `input[name="password"]` with Login ID / Password labels.
- MFA showed a factor-choice screen with radio inputs named `optin`; the user
  selected email and advanced with `Next`.
- Email OTP entry rendered as `input#onetimepin` with aria label
  `Your One-Time PIN`; submit button text was `Submit`.
- A periodic password-change prompt appeared. The connector now chooses
  `Remind Me Later` and records a `credential_action_needed` app
  notification so the deferred action is visible.
- The DoD consent route was `#/message`; the correct control is the bottom
  button text `I agree to the terms of the User Agreement`, not the User
  Agreement link.
- The retired-pay menu route was `#/militaryretired`; the RAS link was
  `Monthly Retiree Account Statement (eRAS)` with href
  `#/militaryretired/mras`.
- The eRAS page exposed `select[aria-label="MRAS History Select"]`.
- `Printer Friendly eRAS` opened `#pdfModal` with a blob-backed iframe titled
  `MRAS PDF`; the connector now fetches the iframe blob bytes instead of
  expecting a browser download event.

Local RAS parser cleanup:

- The user downloaded a local RAS to `raw_exports/mypay/RAS.pdf`.
- Git ignore coverage was verified for that exact path via `raw_exports/`.
- The PDF was used only as local sensitive input. No statement PDF,
  screenshot, DOM dump, credential, OTP, cookie, or account data is intended
  for commit.
- The live PDF parsed as a DFAS RAS but exposed two parser gaps: the pay
  period lives in the `NEW PAY DUE AS OF` header date, and monthly fields can
  share one pdfplumber text line. The parser now handles both and pins the
  behavior with synthetic fixtures.

Runtime fix from the live verification:

- The first `run_all.py --institutions mypay --force --dev` attempt reached
  the OTP screen but timed out because the user entered the OTP directly in the
  myPay browser tab instead of through the dashboard MFA bridge.
- The connector now waits for either a dashboard bridge code or direct browser
  advancement to post-login/password-change state. When the browser advances,
  it cancels the pending dashboard bridge wait and continues.
- myPay opts out of preserving the browser in `--dev` mode. After scraping it
  closes the eRAS PDF modal if present, logs out, declines the optional survey,
  closes the tab, and asks the direct runner to close the automation browser
  during final cleanup.

Verification:

- `python -m py_compile extractors\mypay_connector.py extractors\otp_provider.py backend\document_ingest.py dal\parsers\mypay_ras.py`
- `python -m pytest tests\test_mypay_connector.py tests\test_document_connector_ingest.py tests\test_t04_mypay.py tests\test_t02_document_drop.py tests\test_notifications_dal.py tests\test_institution_connector.py -q`
  - Result: 104 passed.
- Follow-up cleanup tests:
  `python -m pytest tests\test_mypay_connector.py tests\test_institution_connector.py -q`
  - Result: 41 passed.
- The existing authenticated myPay session was used to avoid another login.
  The connector navigated from `#/message` to `#/militaryretired/mras`,
  captured the blob-backed eRAS PDF, and ingested it.
- Trusted dummy DB evidence, without printing financial values:
  - latest `document_drops` row has `parser_type='mypay_ras'`, a file name,
    `committed_at`, and owner attribution;
  - latest `payroll_snapshots` row has `source='mypay_ras'`, pay period,
    gross/net fields present, and owner attribution.
- `git diff --check`
- `git status --ignored --short -- raw_exports\mypay` confirmed local RAS
  PDFs remain ignored.

No live PDFs, screenshots, full DOM dumps, emails, OTPs, credentials, cookies,
tokens, account identifiers, or statement values are committed.
