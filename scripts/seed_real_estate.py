"""
scripts/seed_real_estate.py — Multi-source automated property valuation.

Looks up a property's estimated value from multiple online sources,
computes the mean, and stores each estimate + the mean in the
real_estate table for net worth computation.

Sources:
  1. Zillow (Zestimate) — autocomplete API + Playwright page scrape
  2. Redfin (Redfin Estimate) — Playwright search + navigate + scrape
  3. Realtor.com (RealEstimate) — Playwright search + navigate + scrape
  4. NFCU (if linked mortgage) — reads existing loan_details from DB

Usage:
    # Multi-source automated lookup
    python scripts/seed_real_estate.py --address "123 Main St, Springfield, VA 22150"

    # With linked mortgage (also pulls NFCU estimate if available)
    python scripts/seed_real_estate.py --address "123 Main St, Springfield, VA" --loan nfcu_6167

    # Manual override (skip online lookup, specify value directly)
    python scripts/seed_real_estate.py --name "Primary Residence" --value 385000 --loan nfcu_6167
"""

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
from dal.database import init_db, get_db

log = logging.getLogger("sentry.scripts.seed_real_estate")


# ── Browser helper ───────────────────────────────────────────────────────────


def _get_browser():
    """Get a Playwright browser connection via Chrome CDP."""
    from extractors.chrome_cdp import ensure_chrome_debuggable
    from playwright.sync_api import sync_playwright

    cdp_endpoint = ensure_chrome_debuggable()
    if not cdp_endpoint:
        return None, None, None

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_endpoint)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    return pw, browser, context


def _close_browser(pw):
    """Stop Playwright (but never close the Chrome singleton)."""
    if pw:
        try:
            pw.stop()
        except Exception:
            pass


# ── Source 1: Zillow ─────────────────────────────────────────────────────────


def _zillow_estimate(address: str, context) -> float | None:
    """Get Zestimate from Zillow.

    Step 1: Autocomplete API to find ZPID (lightweight, no browser).
    Step 2: Open property page in browser and extract Zestimate.
    """
    # Step 1: Find ZPID via autocomplete API
    try:
        resp = httpx.get(
            "https://www.zillowstatic.com/autocomplete/v3/suggestions",
            params={"q": address},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        zpid = results[0].get("metaData", {}).get("zpid")
        if not zpid:
            return None
    except Exception as e:
        log.warning("Zillow autocomplete failed: %s", e)
        return None

    if not context:
        return None

    # Step 2: Load property page
    page = context.new_page()
    try:
        page.goto(
            f"https://www.zillow.com/homedetails/{zpid}_zpid/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)

        zestimate = page.evaluate(r"""
            (() => {
                const body = document.body.innerText;
                let m = body.match(/Zestimate[®]?\s*[:.]?\s*\$([\d,]+)/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                m = body.match(/\$([\d,]+)\s*Zestimate/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                const html = document.documentElement.innerHTML;
                m = html.match(/"zestimate"\s*:\s*(\d+)/);
                if (m) return parseInt(m[1]);
                return null;
            })()
        """)
        return float(zestimate) if zestimate and zestimate > 10000 else None

    except Exception as e:
        log.warning("Zillow scrape failed: %s", e)
        return None
    finally:
        page.close()


# ── Source 2: Redfin ─────────────────────────────────────────────────────────


def _redfin_estimate(address: str, context) -> float | None:
    """Get Redfin Estimate by navigating the site.

    Flow: redfin.com → search box → type address → click autocomplete
    result → extract estimate from property detail page.
    """
    if not context:
        return None

    page = context.new_page()
    try:
        page.goto(
            "https://www.redfin.com", wait_until="domcontentloaded", timeout=30000
        )
        page.wait_for_timeout(2000)

        # Type address into search box (Redfin has duplicate search inputs)
        search = page.locator("#search-box-input").first
        if not search.count():
            search = page.locator("input[type='search']").first
        if not search.count():
            log.warning("Redfin: search input not found")
            return None

        search.click()
        search.fill(address)
        page.wait_for_timeout(2500)

        # Click the first autocomplete result
        result = page.locator(".item-row").first
        if not result.count():
            result = page.locator("[class*='SuggestionItem']").first
        if not result.count():
            log.warning("Redfin: no autocomplete results")
            return None

        result.click()
        page.wait_for_timeout(4000)

        # Extract the Redfin Estimate from the property detail page
        estimate = page.evaluate(r"""
            (() => {
                // Primary: data-rf-test-id for the price
                const abp = document.querySelector('[data-rf-test-id="abp-price"]');
                if (abp) {
                    const sv = abp.querySelector('.statsValue') || abp;
                    const text = sv.innerText;
                    const m = text.match(/\$([\d,]+)/);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
                // Fallback: look for Redfin Estimate text
                const body = document.body.innerText;
                let m = body.match(/Redfin Estimate\s*\$([\d,]+)/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                // Fallback: embedded JSON
                const html = document.documentElement.innerHTML;
                m = html.match(/"predictedValue"\s*:\s*(\d+)/);
                if (m) return parseInt(m[1]);
                m = html.match(/"estimatedValue"\s*:\s*(\d+)/);
                if (m) return parseInt(m[1]);
                return null;
            })()
        """)
        return float(estimate) if estimate and estimate > 10000 else None

    except Exception as e:
        log.warning("Redfin scrape failed: %s", e)
        return None
    finally:
        page.close()


# ── Source 3: Realtor.com ────────────────────────────────────────────────────


def _realtor_estimate(address: str, context) -> float | None:
    """Get Realtor.com RealEstimate by navigating the site.

    Flow: realtor.com → search box → type address → click autocomplete
    result → extract estimate from property detail page.
    """
    if not context:
        return None

    page = context.new_page()
    try:
        page.goto(
            "https://www.realtor.com", wait_until="domcontentloaded", timeout=30000
        )
        page.wait_for_timeout(2000)

        # Type address into search box
        search = page.locator('[role="combobox"]').first
        if not search.count():
            search = page.locator("input[type='search']").first
        if not search.count():
            search = page.locator("[class*='SearchInput']").first
        if not search.count():
            log.warning("Realtor.com: search input not found")
            return None

        search.click()
        search.fill(address)
        page.wait_for_timeout(2500)

        # Click the first autocomplete result
        result = page.locator("[class*='TypeaheadSuggestions'] button").first
        if not result.count():
            result = page.locator("[class*='suggestion'] button").first
        if not result.count():
            # Try pressing Enter to search
            search.press("Enter")
            page.wait_for_timeout(3000)
        else:
            result.click()

        page.wait_for_timeout(4000)

        # Extract the estimate from the property detail page
        estimate = page.evaluate(r"""
            (() => {
                // Primary: data-testid for the AVM estimate
                const avm = document.querySelector('[data-testid="avm_spot_offer_estimate"]');
                if (avm) {
                    const text = avm.innerText;
                    const m = text.match(/\$([\d,]+)/);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
                // Fallback: look for "Estimated value" in visible text
                const body = document.body.innerText;
                let m = body.match(/(?:Estimated value|RealEstimate)[^\$]*\$([\d,]+)/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                m = body.match(/\$([\d,]+)\s*(?:estimated|RealEstimate)/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                // Fallback: embedded JSON
                const html = document.documentElement.innerHTML;
                m = html.match(/"estimate"[^}]*"amount"\s*:\s*(\d+)/);
                if (m) return parseInt(m[1]);
                m = html.match(/"estimatedValue"\s*:\s*(\d+)/);
                if (m) return parseInt(m[1]);
                return null;
            })()
        """)
        return float(estimate) if estimate and estimate > 10000 else None

    except Exception as e:
        log.warning("Realtor.com scrape failed: %s", e)
        return None
    finally:
        page.close()


# ── Source 4: NFCU Mortgage Dashboard ────────────────────────────────────────


def _nfcu_estimate(loan_id: str | None) -> float | None:
    """Check if NFCU has a property value estimate in the DB.

    NFCU's mortgage dashboard sometimes shows an estimated home value.
    If captured by the connector, it'll be in loan_details as
    'estimated_home_value' or 'property_value'.
    """
    if not loan_id:
        return None

    try:
        with get_db() as conn:
            for field in ("estimated_home_value", "property_value", "home_value"):
                row = conn.execute(
                    "SELECT field_value FROM loan_details "
                    "WHERE account_id = ? AND field_name = ? "
                    "ORDER BY as_of DESC LIMIT 1",
                    (loan_id, field),
                ).fetchone()
                if row and row["field_value"]:
                    val = re.sub(r"[^0-9.]", "", str(row["field_value"]))
                    if val:
                        return float(val)
    except Exception as e:
        log.warning("NFCU DB lookup failed: %s", e)

    return None


# ── Orchestrator ─────────────────────────────────────────────────────────────


def lookup_property_value(address: str, loan_id: str | None = None) -> dict:
    """Look up property value from multiple sources and compute the mean.

    Returns:
        {
            "estimates": {"zillow": NNN, "redfin": NNN, ...},
            "mean": NNN,
            "name": "display name",
        }
    """
    print(f"  🔍  Looking up: {address}\n")

    estimates: dict[str, float] = {}

    # Source 1 (no browser): NFCU DB
    print("  📋  NFCU mortgage dashboard...", end=" ")
    nfcu_val = _nfcu_estimate(loan_id)
    if nfcu_val:
        estimates["nfcu"] = nfcu_val
        print(f"${nfcu_val:,.0f}")
    else:
        print("not available")

    # Start browser for remaining sources
    pw, browser, context = _get_browser()

    try:
        # Source 2: Zillow
        print("  🏡  Zillow Zestimate...", end=" ", flush=True)
        zest = _zillow_estimate(address, context)
        if zest:
            estimates["zillow"] = zest
            print(f"${zest:,.0f}")
        else:
            print("not available")

        # Source 3: Redfin
        print("  🏠  Redfin Estimate...", end=" ", flush=True)
        redfin = _redfin_estimate(address, context)
        if redfin:
            estimates["redfin"] = redfin
            print(f"${redfin:,.0f}")
        else:
            print("not available")

        # Source 4: Realtor.com
        print("  🏘️  Realtor.com...", end=" ", flush=True)
        realtor = _realtor_estimate(address, context)
        if realtor:
            estimates["realtor"] = realtor
            print(f"${realtor:,.0f}")
        else:
            print("not available")

    finally:
        _close_browser(pw)

    if not estimates:
        print("\n  ✗  No estimates found from any source.")
        return {"estimates": {}, "mean": 0, "name": address}

    mean_val = sum(estimates.values()) / len(estimates)

    print(f"\n  {'─' * 45}")
    print(f"  📊  Sources: {len(estimates)}")
    for src, val in sorted(estimates.items()):
        diff = val - mean_val
        print(
            f"      {src:12s}  ${val:>12,.0f}  ({'+' if diff >= 0 else ''}{diff:,.0f})"
        )
    print(f"  {'─' * 45}")
    print(f"  📐  Mean:      ${mean_val:>12,.0f}")

    # Determine display name from Zillow autocomplete if available
    display_name = address
    try:
        resp = httpx.get(
            "https://www.zillowstatic.com/autocomplete/v3/suggestions",
            params={"q": address},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                display_name = results[0].get("display", address)
    except Exception:
        pass

    return {
        "estimates": estimates,
        "mean": mean_val,
        "name": display_name,
    }


# ── Persistence ──────────────────────────────────────────────────────────────


def persist_valuation(
    name: str,
    value: float,
    source: str = "manual",
    loan_id: str | None = None,
    all_estimates: dict | None = None,
) -> None:
    """Store a property valuation in the database.

    Stores the mean as the primary record, plus individual source
    estimates as separate rows for auditability.
    """
    init_db()
    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        # Store the mean (or manual) value as the primary record
        conn.execute(
            """
            INSERT INTO real_estate (name, estimated_value, linked_loan_id, source, as_of)
            VALUES (?, ?, ?, ?, ?)
        """,
            (name, value, loan_id, source, now),
        )

        # Store individual source estimates for auditability
        if all_estimates:
            for src, val in all_estimates.items():
                conn.execute(
                    """
                    INSERT INTO real_estate (name, estimated_value, linked_loan_id, source, as_of)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (f"{name} [{src}]", val, loan_id, src, now),
                )

        conn.commit()

    print(f"\n  🏠  Recorded: {name}")
    print(f"      Value:  ${value:,.0f}  ({source})")
    if loan_id:
        print(f"      Linked loan: {loan_id}")
    if all_estimates:
        print(f"      Source estimates stored: {', '.join(all_estimates.keys())}")
    print(f"      As of: {now[:10]}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Multi-source property valuation for net worth"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--address", help="Property address for automated multi-source lookup"
    )
    group.add_argument(
        "--value", type=float, help="Manual property value (skips online lookup)"
    )

    parser.add_argument("--name", default=None, help="Property name (default: address)")
    parser.add_argument(
        "--loan", default=None, help="Linked loan account ID (e.g. nfcu_6167)"
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Valuation source label (auto-detected if using --address)",
    )

    args = parser.parse_args()

    if args.address:
        # Automated multi-source lookup
        result = lookup_property_value(args.address, args.loan)

        if result["mean"] > 0:
            name = args.name or result["name"]
            n_sources = len(result["estimates"])
            source = (
                f"mean({n_sources})"
                if n_sources > 1
                else list(result["estimates"].keys())[0]
            )
            persist_valuation(
                name, result["mean"], source, args.loan, result["estimates"]
            )
        else:
            print("\n  💡  No estimates found. You can specify the value manually:")
            print(
                f"      python scripts/seed_real_estate.py --value 350000 "
                f'--name "My House" --loan {args.loan or "nfcu_XXXX"}'
            )
            sys.exit(1)
    else:
        # Manual entry
        name = args.name or "Property"
        source = args.source or "manual"
        persist_valuation(name, args.value, source, args.loan)


if __name__ == "__main__":
    main()
