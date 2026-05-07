# P17-T43: myPay Gmail OAuth OTP Automation

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/65

## Context

P17-T25 created the myPay browser connector and a small `OTPProvider` seam.
The current default provider is the manual MFA bridge: the user types the
email code into the dashboard. The desired endstate is local Gmail OAuth OTP
capture that reads only recent myPay/DFAS challenge messages, extracts only
the code, and falls back to manual MFA whenever the automated path is unsafe
or unavailable.

P17-T42 (#64) should run first so this slice starts with live selector and MFA
facts. If T42 is blocked, this task may still build a unit-tested provider
behind an opt-in setting, but it must not become the default until live myPay
MFA behavior is understood.

## Starting State

- `extractors/otp_provider.py` defines:
  `wait_for_code(institution, *, challenge_started_at, hint, timeout_seconds)`.
- `extractors/mypay_connector.py` calls the provider with
  `institution="mypay"`, `hint="dfas.mil"`, and the challenge start time.
- `ManualMFABridgeOTPProvider` is the default fallback.
- No Gmail OAuth, IMAP polling, browser Gmail scraping, token persistence, or
  inbox access is implemented today.
- The roadmap currently tracks this as the follow-on after P17-T25.

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

TBD.
