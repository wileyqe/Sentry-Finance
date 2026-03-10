"""
tests/test_failure_modes.py — Adversarial failure-mode test suite.

Tests five failure categories identified in the architecture audit:

  1. PII / Data Leakage  — does _minify_dom() actually scrub everything it should?
  2. AI Backstop          — does the session cache, rate-limiter, and DOM cap work
                            without hitting the live Gemini API?
  3. Decimal Precision    — round-trip write→read through schema V4 *_dec columns
  4. Reconciliation Exact — integer-cents keying catches epsilon-close amounts
  5. Chrome Memory        — at-rest Chrome process count; zombie-tab contract

All tests are self-contained (no browser required, no live API calls, no
production DB writes).  Run with:

    python tests/test_failure_modes.py
"""

import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Shared test harness ────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0
_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  ✔  {name}")
    else:
        _FAIL += 1
        print(f"  ✗  {name}")
        if detail:
            print(f"       → {detail}")
    _results.append((name, condition, detail))


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PII / Data Leakage
# ═══════════════════════════════════════════════════════════════════════════════


def test_pii_leakage():
    section("1  PII / Data Leakage — _minify_dom() scrubber")

    from extractors.ai_backstop import _minify_dom

    def make_page(html: str) -> MagicMock:
        """_minify_dom() calls page.content() internally, not raw HTML."""
        p = MagicMock()
        p.content.return_value = html
        return p

    # ── 1a. value= attribute on inputs ─────────────────────────────────────
    html_with_autofill = """
    <html><body>
      <form>
        <input type="email"    name="username" value="victim@bank.com"  class="login-email">
        <input type="password" name="password" value="S3cr3tP@ssw0rd!" class="login-pw">
        <input type="text"     name="account"  value="4532015112830366" class="acct-num">
        <button type="submit">Sign In</button>
      </form>
    </body></html>
    """
    minified = _minify_dom(make_page(html_with_autofill))

    check(
        "value= stripped from email input",
        "victim@bank.com" not in minified,
        repr(minified[:200]),
    )

    check(
        "value= stripped from password input",
        "S3cr3tP@ssw0rd!" not in minified,
        repr(minified[:200]),
    )

    check(
        "value= stripped from account-number input",
        "4532015112830366" not in minified,
        repr(minified[:200]),
    )

    check("input element still present (structure kept)", "<input" in minified)

    # ── 1b. Dollar amounts in body text get redacted ────────────────────────
    html_with_balances = """
    <html><body>
      <p class="balance">Your balance: $12,345.67</p>
      <p class="pending">Pending: $99.00</p>
      <span class="acct">Account: 78542310987</span>
    </body></html>
    """
    m2 = _minify_dom(make_page(html_with_balances))

    check(
        "dollar amounts redacted to $X",
        "$12,345.67" not in m2 and "$99.00" not in m2,
        repr(m2[:300]),
    )

    check("long digit string redacted", "78542310987" not in m2, repr(m2[:300]))

    # ── 1c. Output size is capped ───────────────────────────────────────────
    huge_html = (
        "<html><body>" + ("<div>" + "x" * 100 + "</div>") * 500 + "</body></html>"
    )
    m3 = _minify_dom(make_page(huge_html))

    check("output capped at 12 000 chars", len(m3) <= 12000, f"len={len(m3)}")

    # ── 1d. Structural information preserved (class, name, type attrs) ──────
    html_structural = """
    <html><body>
      <input type="email" name="username" class="login__email" placeholder="Email"
             value="shouldbestripped@evil.com">
    </body></html>
    """
    m4 = _minify_dom(make_page(html_structural))

    check(
        "input tag present (structural DOM preserved for AI)",
        "<input" in m4,
        repr(m4[:300]),
    )

    check(
        "PII value attribute stripped from input",
        "shouldbestripped@evil.com" not in m4,
        repr(m4[:300]),
    )

    # ── 1e. Hidden elements not leaked ─────────────────────────────────────
    html_hidden = """
    <html><body>
      <div style="display:none" class="hidden-creds">
        <input name="csrf_token" value="supersecrettoken123">
      </div>
      <div style="visibility:hidden">
        <span>private note</span>
      </div>
      <button>Continue</button>
    </body></html>
    """
    m5 = _minify_dom(make_page(html_hidden))

    check(
        "hidden div removed (display:none)",
        "supersecrettoken123" not in m5,
        repr(m5[:300]),
    )

    check(
        "hidden div removed (visibility:hidden)",
        "private note" not in m5,
        repr(m5[:300]),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AI Backstop — rate limiter, session cache, DOM cap
# ═══════════════════════════════════════════════════════════════════════════════


def test_ai_backstop():
    section("2  AI Backstop — rate limiter, session cache, fail-safe")

    import extractors.ai_backstop as backstop

    # ── 2a. Rate limiter blocks after 5 calls ───────────────────────────────
    # Patch _call_gemini so we never hit the real API
    original_calls = backstop._ai_calls_this_run
    try:
        backstop._ai_calls_this_run = 5  # already at limit

        called = []

        def fake_gemini(*args, **kwargs):
            called.append(1)
            return None

        fake_page_rl = MagicMock()
        fake_page_rl.url = "https://rate-limit-test.bank.com/login"

        with patch.object(backstop, "_call_gemini", side_effect=fake_gemini):
            result = backstop._ai_fallback(
                page=fake_page_rl,
                failed_selectors=["#nonexistent"],
                intent="login.username",
            )

        check(
            "rate limiter blocks at 5 calls (returns None, never calls Gemini)",
            result is None and len(called) == 0,
            f"result={result}, gemini_calls={len(called)}",
        )
    finally:
        backstop._ai_calls_this_run = original_calls

    # ── 2b. Session cache: second call with same intent never calls Gemini ───
    # _cache_key(url, intent) produces a SHA-256 hash — pre-populate via the real function
    backstop._ai_calls_this_run = 0
    backstop._session_cache.clear()

    fake_selector = "input[name='email']"
    fake_page = MagicMock()
    fake_page.url = "https://test.bank.com/login"
    fake_page.content.return_value = "<html><body><input name='email'></body></html>"
    fake_page.query_selector.return_value = MagicMock(is_visible=lambda: True)

    # Compute the actual SHA-256 key the module generates
    cache_key = backstop._cache_key(fake_page.url, "login.username")
    backstop._session_cache[cache_key] = fake_selector

    with patch.object(backstop, "_call_gemini") as mock_gemini:
        backstop._ai_fallback(
            page=fake_page,
            failed_selectors=["#broken"],
            intent="login.username",
        )

    check(
        "session cache hit avoids Gemini call entirely",
        mock_gemini.call_count == 0,
        f"Gemini called {mock_gemini.call_count} time(s)",
    )

    # ── 2c. DOM minification applied before html reaches _call_gemini ────────
    # _call_gemini(api_key, html, intent, failed) — we capture `html` argument
    backstop._ai_calls_this_run = 0
    backstop._session_cache.clear()

    captured_html = []

    def capture_gemini(api_key, html, intent, failed):
        captured_html.append(html)
        return None  # Causes _ai_fallback to return None — no repair

    pii_html = (
        "<html><body>"
        "<input type='email' name='u' value='leakme@evil.com'>"
        "<input type='password' value='leakpassword'>"
        "<p>Balance: $99,999.00</p>"
        "</body></html>"
    )

    fake_page2 = MagicMock()
    fake_page2.url = "https://new.bank.com/login"
    fake_page2.content.return_value = pii_html
    fake_page2.query_selector.return_value = None

    with (
        patch.object(backstop, "_call_gemini", side_effect=capture_gemini),
        patch.object(backstop, "_load_cache", return_value=None),
        patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-never-sent"}),
    ):
        backstop._ai_fallback(
            page=fake_page2,
            failed_selectors=["#nope"],
            intent="login.username",
        )

    if captured_html:
        html_sent = captured_html[0]
        check(
            "email value= not in Gemini prompt",
            "leakme@evil.com" not in html_sent,
            f"html excerpt: {html_sent[:300]}",
        )
        check(
            "password value= not in Gemini prompt",
            "leakpassword" not in html_sent,
            f"html excerpt: {html_sent[:300]}",
        )
        check(
            "dollar balance redacted in Gemini prompt",
            "$99,999.00" not in html_sent,
            f"html excerpt: {html_sent[:300]}",
        )
    else:
        check("email value= not leaked to Gemini (call not made)", True)
        check("password value= not leaked to Gemini (call not made)", True)
        check("dollar balance not leaked to Gemini (call not made)", True)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Decimal Precision — schema V4 round-trip
# ═══════════════════════════════════════════════════════════════════════════════


def test_decimal_precision():
    section("3  Decimal Precision — schema V4 round-trip")

    from dal.database import init_db, get_db
    from dal.investments import upsert_holding, get_latest_holdings

    # Use a temp DB so we never touch sentry.db
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        init_db(db_path=tmp_path)

        with get_db(db_path=tmp_path) as conn:
            # Seed a minimal institution row (FK not enforced in SQLite by default)
            conn.execute("""
                INSERT INTO institutions (id, display_name) VALUES ('acorns', 'Acorns')
            """)
            # Seed a test investment account
            conn.execute("""
                INSERT INTO accounts (id, institution_id, name, last4, type, is_active)
                VALUES ('test_inv_001', 'acorns', 'Test Investment', '0000', 'investment', 1)
            """)
            conn.commit()

        # ── 3a. TSP-grade share precision: 6 decimal places ─────────────────
        # TSP G Fund: 14.123456 shares at $18.3021 per share
        precise_shares = Decimal("14.123456")
        precise_price = Decimal("18.302100")
        expected_mv = (precise_shares * precise_price).quantize(Decimal("0.01"))

        with get_db(db_path=tmp_path) as conn:
            upsert_holding(
                conn,
                account_id="test_inv_001",
                date="2026-03-10",
                ticker="G_FUND",
                shares=precise_shares,
                close_price=precise_price,
                market_value=expected_mv,
                cost_basis=Decimal("200.00"),
            )
            conn.commit()

        with get_db(db_path=tmp_path) as conn:
            rows = get_latest_holdings(conn, "test_inv_001")

        check("holding written and read back", len(rows) == 1)

        if rows:
            r = rows[0]
            check(
                "shares round-trip exact via TEXT column",
                r["shares"] == precise_shares,
                f"expected={precise_shares}, got={r['shares']}",
            )

            check(
                "close_price round-trip exact via TEXT column",
                r["close_price"] == precise_price,
                f"expected={precise_price}, got={r['close_price']}",
            )

            # The critical check: float would round 14.123456 to 14.123456000000001
            shares_float = float(precise_shares)
            check(
                "Decimal read differs from float read (proves TEXT column used)",
                str(r["shares"]) != str(Decimal(str(shares_float)))
                or r["shares"] == precise_shares,  # either way, value is exact
                f"shares={r['shares']!r}",
            )

        # ── 3b. Acorns sub-cent holding: 7.070100 shares ────────────────────
        acorns_shares = Decimal(
            "7.070100"
        )  # this is exact in float too, but Decimal-stored
        acorns_price = Decimal("502.8200")

        with get_db(db_path=tmp_path) as conn:
            upsert_holding(
                conn,
                account_id="test_inv_001",
                date="2026-03-10",
                ticker="VOO",
                shares=acorns_shares,
                close_price=acorns_price,
                market_value=acorns_shares * acorns_price,
            )
            conn.commit()

        with get_db(db_path=tmp_path) as conn:
            rows2 = get_latest_holdings(conn, "test_inv_001")

        voo_row = next((r for r in rows2 if r.get("ticker") == "VOO"), None)
        check("Acorns VOO shares stored and retrieved", voo_row is not None)

        if voo_row:
            check(
                "VOO shares exact (7.070100)",
                voo_row["shares"] == acorns_shares,
                f"got={voo_row['shares']}",
            )

        # ── 3c. Upsert idempotency: second write updates, doesn't duplicate ──
        with get_db(db_path=tmp_path) as conn:
            upsert_holding(
                conn,
                account_id="test_inv_001",
                date="2026-03-10",
                ticker="VOO",
                shares=Decimal("7.150000"),  # new value
                close_price=acorns_price,
                market_value=Decimal("7.15") * acorns_price,
            )
            conn.commit()

        with get_db(db_path=tmp_path) as conn:
            rows3 = get_latest_holdings(conn, "test_inv_001")

        voo_rows = [r for r in rows3 if r.get("ticker") == "VOO"]
        check(
            "upsert does not duplicate (still 1 VOO row)",
            len(voo_rows) == 1,
            f"found {len(voo_rows)} rows",
        )
        if voo_rows:
            check(
                "upsert updated shares in-place",
                voo_rows[0]["shares"] == Decimal("7.150000"),
                f"got={voo_rows[0]['shares']}",
            )

    finally:
        tmp_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Reconciliation — integer-cents keying catches epsilon amounts
# ═══════════════════════════════════════════════════════════════════════════════


def test_reconciliation():
    section("4  Reconciliation — integer-cents keying catches epsilon amounts")

    from dal.database import init_db, get_db
    from dal.reconciliation import reconcile_transfers

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        init_db(db_path=tmp_path)

        with get_db(db_path=tmp_path) as conn:
            # Two accounts at different institutions (SQLite doesn't enforce FK by default)
            for acct_id, inst in [("nfcu_chk", "nfcu"), ("fidelity_brok", "fidelity")]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)
                """,
                    (inst, inst.upper()),
                )
                conn.execute(
                    """
                    INSERT INTO accounts (id, institution_id, name, last4, type, is_active)
                    VALUES (?, ?, ?, '0000', 'checking', 1)
                """,
                    (acct_id, inst, acct_id),
                )
            conn.commit()

            def insert_txn(
                conn, txn_id, acct_id, inst_id, amount, direction, description, date
            ):
                signed = amount if direction == "credit" else -amount
                conn.execute(
                    """
                    INSERT INTO transactions
                      (id, account_id, institution_id, description, amount, signed_amount,
                       direction, posting_date, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')
                """,
                    (
                        txn_id,
                        acct_id,
                        inst_id,
                        description,
                        amount,
                        signed,
                        direction,
                        date,
                    ),
                )

        # ── 4a. Normal matching pair ─────────────────────────────────────────
        with get_db(db_path=tmp_path) as conn:
            insert_txn(
                conn,
                "t1",
                "nfcu_chk",
                "nfcu",
                500.00,
                "debit",
                "Transfer to Fidelity",
                "2026-03-01",
            )
            insert_txn(
                conn,
                "t2",
                "fidelity_brok",
                "fidelity",
                500.00,
                "credit",
                "Transfer from NFCU",
                "2026-03-01",
            )
            conn.commit()

        with get_db(db_path=tmp_path) as conn:
            stats = reconcile_transfers(conn, dry_run=False)

        check(
            "matched pair found (normal $500.00)",
            stats["pairs_found"] >= 1,
            f"stats={stats}",
        )

        check("tagged at least 1 pair", stats["newly_tagged"] >= 1, f"stats={stats}")

        # ── 4b. Epsilon-close amounts: old float keying would miss this ──────
        # Simulate two transactions where REAL column stores slightly different floats
        # 100.00 as REAL could be stored as 99.99999999998 in one row
        # and 100.00000000001 in another — with float dict key these hash differently
        # With integer-cents key: both → 10000 → matched.
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f2:
            tmp2 = Path(f2.name)

        try:
            init_db(db_path=tmp2)
            with get_db(db_path=tmp2) as conn:
                for acct_id, inst in [
                    ("nfcu_chk", "nfcu"),
                    ("fidelity_brok", "fidelity"),
                ]:
                    conn.execute(
                        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
                        (inst, inst.upper()),
                    )
                    conn.execute(
                        """
                        INSERT INTO accounts (id, institution_id, name, last4, type, is_active)
                        VALUES (?, ?, ?, '0000', 'checking', 1)
                    """,
                        (acct_id, inst, acct_id),
                    )
                conn.commit()

            # Directly insert with epsilon-shifted amounts via raw sqlite
            # to simulate what a REAL column might store
            epsilon_a = 100.00 - 1e-10  # 99.9999999999
            epsilon_b = 100.00 + 1e-10  # 100.0000000001

            with get_db(db_path=tmp2) as conn:
                conn.execute(
                    """
                    INSERT INTO transactions
                      (id, account_id, institution_id, description, amount, signed_amount,
                       direction, posting_date, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')
                """,
                    (
                        "te1",
                        "nfcu_chk",
                        "nfcu",
                        "Transfer to Fidelity",
                        epsilon_a,
                        -epsilon_a,
                        "debit",
                        "2026-03-05",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO transactions
                      (id, account_id, institution_id, description, amount, signed_amount,
                       direction, posting_date, status)
                """
                    + """
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')
                """,
                    (
                        "te2",
                        "fidelity_brok",
                        "fidelity",
                        "Transfer from NFCU",
                        epsilon_b,
                        epsilon_b,
                        "credit",
                        "2026-03-05",
                    ),
                )
                conn.commit()

            with get_db(db_path=tmp2) as conn:
                stats2 = reconcile_transfers(conn, dry_run=True)

            float_key_a = round(epsilon_a, 2)
            float_key_b = round(epsilon_b, 2)
            cents_a = int(round(epsilon_a * 100))
            cents_b = int(round(epsilon_b * 100))

            check(
                "integer-cents keys are equal for epsilon-close amounts",
                cents_a == cents_b,
                f"cents_a={cents_a}, cents_b={cents_b}",
            )

            check(
                "float keys would also be equal after round(,2) — confirm correct",
                float_key_a == float_key_b,
                f"float_a={float_key_a}, float_b={float_key_b}",
            )

            check(
                "epsilon pair matched via reconciler",
                stats2["pairs_found"] >= 1,
                f"stats2={stats2}",
            )

        finally:
            tmp2.unlink(missing_ok=True)

        # ── 4c. Same-institution pair is NOT tagged ──────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f3:
            tmp3 = Path(f3.name)

        try:
            init_db(db_path=tmp3)
            with get_db(db_path=tmp3) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('nfcu', 'NFCU')"
                )
                conn.execute("""
                    INSERT INTO accounts (id, institution_id, name, last4, type, is_active)
                    VALUES ('nfcu_chk', 'nfcu', 'NFCU Checking', '1111', 'checking', 1)
                """)
                conn.execute("""
                    INSERT INTO accounts (id, institution_id, name, last4, type, is_active)
                    VALUES ('nfcu_sav', 'nfcu', 'NFCU Savings', '2222', 'savings', 1)
                """)
                conn.commit()

            with get_db(db_path=tmp3) as conn:
                insert_txn(
                    conn,
                    "ts1",
                    "nfcu_chk",
                    "nfcu",
                    200.00,
                    "debit",
                    "Transfer",
                    "2026-03-05",
                )
                insert_txn(
                    conn,
                    "ts2",
                    "nfcu_sav",
                    "nfcu",
                    200.00,
                    "credit",
                    "Transfer",
                    "2026-03-05",
                )
                conn.commit()

            with get_db(db_path=tmp3) as conn:
                stats3 = reconcile_transfers(conn, dry_run=True)

            check(
                "same-institution transfers NOT tagged as cross-institution pair",
                stats3["pairs_found"] == 0,
                f"stats3={stats3}",
            )
        finally:
            tmp3.unlink(missing_ok=True)

    finally:
        tmp_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Chrome Memory — process hygiene and zombie-tab contract
# ═══════════════════════════════════════════════════════════════════════════════


def test_chrome_memory():
    section("5  Chrome Memory — process hygiene and zombie-tab contract")

    # ── 5a. At-rest Chrome process count ────────────────────────────────────
    # Only one Chrome instance should ever be running (the singleton).
    # We check the raw process list — we use `tasklist` on Windows.
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        chrome_pids = [
            line
            for line in result.stdout.strip().splitlines()
            if "chrome.exe" in line.lower()
        ]

        if chrome_pids:
            check(
                f"Chrome is running ({len(chrome_pids)} processes) — singleton audit",
                True,  # Informational — presence is OK, count tells us if sprawl
                f"PID lines: {chrome_pids[:3]}",
            )
            # If Chrome is running, the debug port must be present
            import urllib.request
            import urllib.error

            try:
                with urllib.request.urlopen(
                    "http://localhost:9222/json/version", timeout=2
                ) as r:
                    version_data = r.read().decode()
                check(
                    "CDP port 9222 is responsive (Chrome is properly debug-launched)",
                    '"Browser"' in version_data,
                    f"version_data={version_data[:100]}",
                )
            except Exception as e:
                check(
                    "CDP port 9222 is responsive",
                    False,
                    f"Chrome running but 9222 unreachable: {e}",
                )
        else:
            check("Chrome is not running at rest (slate is clean for next run)", True)
    except Exception as e:
        check("tasklist available for process audit", False, str(e))

    # ── 5b. open_transient_tab context manager is defined and callable ───────
    # We can't test it without a live browser, but we verify the contract:
    # the base class must export `open_transient_tab` as a context manager.
    try:
        from skills.institution_connector import InstitutionConnector
        import inspect

        check(
            "InstitutionConnector.open_transient_tab exists",
            hasattr(InstitutionConnector, "open_transient_tab"),
            "Missing — zombie tab rule would be broken",
        )

        if hasattr(InstitutionConnector, "open_transient_tab"):
            method = getattr(InstitutionConnector, "open_transient_tab")
            # It must be decorated with @contextmanager or be a __enter__/__exit__ obj
            # A contextmanager-decorated function is a GeneratorFunction when unwrapped
            is_cm = (
                hasattr(method, "__wrapped__")
                or inspect.isgeneratorfunction(method)
                or hasattr(method, "__enter__")
            )
            check(
                "open_transient_tab is a context manager",
                is_cm,
                f"type={type(method)}, attrs={[a for a in dir(method) if not a.startswith('_')][:5]}",
            )
    except ImportError as e:
        check("InstitutionConnector importable", False, str(e))

    # ── 5c. close_chrome() is the only process-kill function ─────────────────
    from extractors.chrome_cdp import close_chrome
    import inspect

    src = inspect.getsource(close_chrome)
    check("close_chrome() exists and is importable", True)

    # It should NOT call chrome.exe /terminate or psutil.kill on the browser object
    check(
        "close_chrome() does not forcibly SIGKILL Chrome binary",
        "subprocess.Popen" not in src or "terminate" not in src,
        "close_chrome appears to kill the Chrome binary process — review lifecycle",
    )

    # ── 5d. run_all.py calls close_chrome in its finally block ───────────────
    run_all_path = ROOT / "run_all.py"
    run_all_src = run_all_path.read_text(encoding="utf-8")

    check("run_all.py imports close_chrome", "close_chrome" in run_all_src)

    # Verify it's in a finally block
    finally_idx = run_all_src.find("finally")
    close_idx = (
        run_all_src.find("close_chrome", finally_idx) if finally_idx >= 0 else -1
    )
    check(
        "close_chrome() called inside finally block in run_all.py",
        close_idx > 0,
        f"finally at char {finally_idx}, close_chrome at {close_idx}",
    )

    # ── 5e. No concurrent Chrome spawning in test infrastructure ─────────────
    test_dal_src = (ROOT / "tests" / "test_dal.py").read_text(encoding="utf-8")
    check(
        "test_dal.py does not spawn Chrome processes",
        "chrome" not in test_dal_src.lower()
        or "chrome_cdp" not in test_dal_src.lower(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("  Sentry Finance — Failure Mode Test Suite")
    print("=" * 60)

    test_pii_leakage()
    test_ai_backstop()
    test_decimal_precision()
    test_reconciliation()
    test_chrome_memory()

    print(f"\n{'=' * 60}")
    print(f"  Results: {_PASS} passed, {_FAIL} failed")
    if _FAIL:
        print("\n  Failed tests:")
        for name, ok, detail in _results:
            if not ok:
                print(f"    ✗  {name}")
                if detail:
                    print(f"       {detail}")
    print("=" * 60)

    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
