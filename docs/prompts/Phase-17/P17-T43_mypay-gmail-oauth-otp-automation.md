# P17-T43: myPay Gmail OAuth OTP Automation

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/65

## Context

P17-T25 created the myPay browser connector and a small `OTPProvider` seam.
The current default provider is the manual MFA bridge: the user types the
email code into the dashboard. The desired endstate is local Gmail OAuth OTP
capture that reads only recent myPay/DFAS challenge messages, extracts only
the code, and falls back to manual MFA whenever the automated path is unsafe
or unavailable.

P17-T42 (#64) produced the key MFA facts: myPay shows a factor-choice screen
with email selectable, then an OTP field at `input#onetimepin` with aria label
`Your One-Time PIN` and a `Submit` button. It also proved that users may enter
the OTP directly in the myPay browser tab instead of through the dashboard MFA
bridge. This task may now build a unit-tested provider behind an opt-in
setting, but it must not become the default until this slice proves OAuth
filtering, redaction, ambiguity handling, and manual fallback.

## Starting State

- `extractors/otp_provider.py` defines:
  `wait_for_code(institution, *, challenge_started_at, hint, timeout_seconds)`.
- `extractors/mypay_connector.py` calls the provider with
  `institution="mypay"`, `hint="dfas.mil"`, and the challenge start time.
- `ManualMFABridgeOTPProvider` is the default fallback.
- No Gmail OAuth, IMAP polling, browser Gmail scraping, token persistence, or
  inbox access is implemented today.
- P17-T42 observed email MFA, pinned the connector selector shape, and
  verified authenticated-session RAS download/ingest.
- The roadmap currently tracks this as the follow-on after P17-T42.

## Task

1. Start from clean, up-to-date `main` on a dedicated branch:
   `codex/p17-t43-mypay-gmail-oauth-otp-automation`.
2. Read P17-T25 and P17-T42 outcomes before editing.
3. Run the Graph Context Check:

```powershell
python tools\graphify\query_local.py impact "myPay Gmail OAuth OTP provider manual MFA fallback"
```

4. Add a local Gmail OTP provider that plugs into the existing
   `OTPProvider` seam. Suggested shape:
   - `extractors/gmail_otp_provider.py` or a focused sibling module,
   - a provider class such as `GmailOAuthOTPProvider`,
   - a small factory/config path that keeps the manual provider as fallback,
   - no provider-specific behavior inside `MyPayConnector` beyond selecting
     the provider.
5. Use the narrowest practical Gmail read scope, preferably `gmail.readonly`.
6. Store OAuth client/token material only outside tracked files:
   - keyring when available, or
   - a clearly gitignored local path under `secrets/` or equivalent.
7. Query only messages newer than `challenge_started_at` and only within the
   timeout window.
8. Filter to myPay/DFAS sender and subject/body hints. Treat multiple
   plausible codes as ambiguous and fall back to manual MFA.
9. Extract only the OTP code. Do not persist message bodies, subjects, sender
   addresses, or OTPs beyond the in-memory wait.
10. Redact OTPs and message details in logs.
11. Fall back to `ManualMFABridgeOTPProvider` on OAuth failure, no matching
   message, ambiguity, timeout, missing local config, or unavailable Gmail
   dependency.
12. Keep the implementation local-first and opt-in until a live myPay run
   proves the provider safe enough to become default.

## Non-Goals

- Do not scrape Gmail in a browser.
- Do not use IMAP.
- Do not add cloud persistence, telemetry, or external OTP services.
- Do not commit OAuth credentials, refresh tokens, access tokens, raw emails,
  OTPs, screenshots, PDFs, or live account details.
- Do not broaden the connector lifecycle, credential broker, or frontend MFA
  UI beyond what is needed for provider selection and safe fallback.

## Verification

Unit tests must use fake Gmail/OAuth clients and synthetic messages. Cover:

- messages older than `challenge_started_at` are ignored,
- sender/subject/body filters reject unrelated mail,
- a single matching code returns that code without logging it,
- no match returns manual fallback,
- multiple plausible codes return manual fallback,
- OAuth/config failure returns manual fallback,
- timeout returns `None` or manual fallback according to the provider contract,
- the provider never stores raw message bodies or OTPs in tracked files,
- `default_provider()` remains manual unless this task explicitly and safely
  wires an opt-in selection path.

Minimum commands:

```powershell
python -m py_compile extractors\otp_provider.py extractors\mypay_connector.py
python -m pytest tests\test_mypay_connector.py tests\test_document_connector_ingest.py -q
python -m pytest tests\test_t04_mypay.py tests\test_t02_document_drop.py -q
```

Add a new focused test file for the Gmail provider and include it in
verification. Run leakage checks before commit:

```powershell
rg -n "refresh_token|access_token|client_secret|password|otp|verification code" .
git diff --name-only
git status --short
```

Any hit must be a redacted test fixture, documentation reference, or
gitignored local file.

## Done Criteria

- A Gmail OAuth OTP provider exists behind the `OTPProvider` seam.
- Manual MFA remains the safe fallback for every failure/ambiguous path.
- OAuth/token material is kept out of tracked files.
- Tests prove date-window filtering, myPay/DFAS filtering, ambiguity handling,
  redaction, and fallback.
- The prompt Outcome records whether the provider is opt-in or default, and
  what live verification remains.

## Outcome

Implemented on `codex/p17-t43-mypay-gmail-oauth-otp-automation`.

What changed:

- Added `extractors/gmail_otp_provider.py` with
  `GmailOAuthOTPProvider`, using the Gmail API `gmail.readonly` scope.
- Kept manual MFA as the default. Gmail OTP is opt-in with
  `MYPAY_OTP_PROVIDER=gmail` or `SENTRY_MYPAY_OTP_PROVIDER=gmail`.
- OAuth client JSON is expected at
  `secrets/google/mypay_gmail_oauth_client.json`; refresh-token
  material is stored in the OS keyring when available, otherwise in the
  gitignored `secrets/google/mypay_gmail_oauth_token.json`.
- Added `scripts/setup_mypay_gmail_oauth.py` to run/refresh the local
  OAuth grant before a myPay scrape.
- The provider filters messages by Gmail internal date after
  `challenge_started_at`, DFAS/myPay sender/content hints, and a single
  six-digit code. Multiple distinct plausible codes are treated as
  ambiguous and fall back to manual MFA.
- Gmail polling is capped at 45 seconds by default (or
  `MYPAY_GMAIL_OTP_POLL_SECONDS`, capped by the connector timeout) so
  the provider does not burn the full 300-second MFA window before
  falling back to the dashboard bridge.
- Added fake-Gmail unit tests for old-message rejection, unrelated mail,
  single-code success without log leakage, no-match fallback, ambiguous
  fallback, OAuth/config fallback, timeout fallback, no raw body/code
  retention on the provider, and default-vs-opt-in provider selection.
- Updated `docs/COMMANDS.md`, `docs/ROADMAP.md`, and data-lineage
  events/lineage/inverse-index/diagrams for the new live-only OTP
  source.

Verification:

- `python -m py_compile extractors\otp_provider.py extractors\gmail_otp_provider.py extractors\mypay_connector.py scripts\setup_mypay_gmail_oauth.py`
- `python -m pytest tests\test_gmail_otp_provider.py tests\test_mypay_connector.py tests\test_document_connector_ingest.py -q`
  - Result: 45 passed.
- `python -m pytest tests\test_t04_mypay.py tests\test_t02_document_drop.py -q`
  - Result: 41 passed.
- `python docs\data-lineage\check_freshness.py`
- `git diff --check`
- `git check-ignore -v secrets\google\mypay_gmail_oauth_client.json secrets\google\mypay_gmail_oauth_token.json`
- Leakage scan:
  `rg -n "refresh_token|access_token|client_secret|password|otp|verification code" .`
  produced code/test/doc references only; gitignored `secrets/` was not
  scanned.

Broader suite:

- `python -m pytest tests\ -q --ignore=tests\test_failure_modes.py`
  - Result: 722 passed, 1 xfailed, 1 failed.
  - Failure was
    `tests/test_performance_by_asset_class.py::test_perf_by_class`,
    where the legacy performance call returned no rows and the test
    indexed an empty list. This slice did not touch investment
    performance code; focused myPay/Gmail/document verification passed.

Live verification remaining:

- Run `python scripts\setup_mypay_gmail_oauth.py` with the downloaded
  OAuth client JSON in place.
- Run a user-present myPay scrape with `MYPAY_OTP_PROVIDER=gmail`.
- Keep manual MFA fallback available and keep Gmail OTP opt-in until a
  live run proves the inbox filtering safe.
