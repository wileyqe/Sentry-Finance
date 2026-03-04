"""
extractors/dom_healer.py — Offline selector maintenance module.

Proactively checks all selectors in selector_registry.yaml against live
institution pages and uses an LLM to fix broken ones.

Usage:
    python -m extractors.dom_healer                     # Check all
    python -m extractors.dom_healer --fix               # Auto-fix broken
    python -m extractors.dom_healer --institution nfcu  # Check one

This is designed to run as a cron job (weekly) or manually triggered
BEFORE a full extraction run.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("sentry.extractors.dom_healer")

# ── Constants ────────────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
REPORT_PATH = _PROJECT_DIR / "dom_health_report.json"

# Pages to check per institution (no login required for these)
HEALTH_CHECK_URLS = {
    "nfcu": "https://www.navyfederal.org/",
    "chase": "https://www.chase.com/",
}


# ── Health Check ─────────────────────────────────────────────────────────────


def check_selectors(
    institution: str | None = None,
    fix: bool = False,
) -> dict:
    """Test all selectors against live pages and optionally auto-fix.

    Args:
        institution: Specific institution to check (None = all).
        fix: If True, use AI to generate fixes for broken selectors.

    Returns:
        Health report dict with pass/fail per selector group.
    """
    from extractors.ai_backstop import load_selectors, save_selectors

    registry = load_selectors()
    if not registry:
        print("  ❌  No selector registry found")
        return {}

    report = {"timestamp": datetime.now().isoformat(), "institutions": {}}

    institutions = [institution] if institution else list(registry.keys())

    for inst in institutions:
        if inst not in registry:
            print(f"  ⚠  Unknown institution: {inst}")
            continue

        url = HEALTH_CHECK_URLS.get(inst)
        if not url:
            print(f"  ⚠  No health-check URL for: {inst}")
            continue

        print(f"\n  🏥  Checking {inst} ({url})...")
        inst_report = _check_institution(inst, registry[inst], url, fix)
        report["institutions"][inst] = inst_report

        if fix and inst_report.get("fixes_applied", 0) > 0:
            save_selectors(registry)
            print(
                f"  💾  Updated selector_registry.yaml with {inst_report['fixes_applied']} fixes"
            )

    # Save report
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\n  📄  Report saved to: {REPORT_PATH.name}")

    return report


def _check_institution(inst: str, inst_config: dict, url: str, fix: bool) -> dict:
    """Check all selector groups for one institution."""
    from playwright.sync_api import TimeoutError  # noqa: F811
    from playwright.sync_api import sync_playwright

    inst_report = {
        "url": url,
        "groups": {},
        "total": 0,
        "passed": 0,
        "failed": 0,
        "fixes_applied": 0,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            channel="chrome",
        )
        page = browser.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  ❌  Could not load {url}: {e}")
            browser.close()
            return inst_report

        # Walk all selector groups in this institution
        _walk_and_check(inst_config, [], page, inst_report, fix, inst)

        browser.close()

    return inst_report


def _walk_and_check(
    config: dict, path: list[str], page, report: dict, fix: bool, institution: str
):
    """Recursively walk the registry tree and test selector groups."""
    if "selectors" in config and "intent" in config:
        # This is a leaf selector group — test it
        group_path = ".".join(path)
        _test_group(config, group_path, page, report, fix, institution)
        return

    for key, value in config.items():
        if isinstance(value, dict):
            _walk_and_check(value, path + [key], page, report, fix, institution)


def _test_group(
    group: dict, path: str, page, report: dict, fix: bool, institution: str
):
    """Test a single selector group against the live page."""
    intent = group.get("intent", path)
    selectors = group.get("selectors", [])
    report["total"] += 1

    # Skip template selectors (they need runtime data)
    has_templates = any("{" in s for s in selectors)
    if has_templates:
        report["groups"][path] = {
            "status": "skipped",
            "reason": "template selectors need runtime data",
            "intent": intent,
        }
        print(f"    ⏭  {path}: skipped (template selectors)")
        return

    # Try each selector
    working = []
    broken = []
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                working.append(sel)
            else:
                broken.append(sel)
        except Exception:
            broken.append(sel)

    if working:
        report["passed"] += 1
        report["groups"][path] = {
            "status": "pass",
            "working": working,
            "broken": broken,
            "intent": intent,
        }
        print(f"    ✔  {path}: {len(working)}/{len(selectors)} working")
    else:
        report["failed"] += 1
        result = {
            "status": "fail",
            "broken": broken,
            "intent": intent,
        }

        if fix:
            new_sel = _try_heal(page, group, institution, path)
            if new_sel:
                # Prepend the AI-found selector to the group
                group["selectors"].insert(0, new_sel)
                result["ai_fix"] = new_sel
                result["status"] = "healed"
                report["fixes_applied"] += 1
                print(f"    🔧  {path}: HEALED → {new_sel}")
            else:
                print(f"    ❌  {path}: FAILED (AI could not fix)")
        else:
            print(f"    ❌  {path}: ALL {len(selectors)} selectors broken")

        report["groups"][path] = result


def _try_heal(page, group: dict, institution: str, path: str) -> str | None:
    """Use the AI backstop to find a working selector for a broken group."""
    from extractors.ai_backstop import _call_gemini, _extract_relevant_html

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — cannot heal")
        return None

    html = _extract_relevant_html(page, group["intent"])
    suggested = _call_gemini(api_key, html, group["intent"], group["selectors"])

    if not suggested:
        return None

    # Validate against live DOM
    try:
        el = page.query_selector(suggested)
        if el and el.is_visible():
            return suggested
    except Exception as e:
        log.debug("Ignored exception: %s", e)

    log.warning("AI suggestion didn't match live DOM: %s", suggested)
    return None


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="DOM Healer — check and fix selectors in the registry"
    )
    parser.add_argument(
        "--institution",
        "-i",
        type=str,
        default=None,
        help="Check only this institution (nfcu, chase)",
    )
    parser.add_argument(
        "--fix", action="store_true", help="Auto-fix broken selectors using AI"
    )
    args = parser.parse_args()

    from config.logging_config import setup_logging

    setup_logging()

    print("\n  🏥  DOM Healer — Selector Health Check")
    print(f"  ⏰  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if args.fix:
        print("  🔧  Auto-fix mode ENABLED")
    print()

    report = check_selectors(institution=args.institution, fix=args.fix)

    # Summary
    for inst, data in report.get("institutions", {}).items():
        total = data.get("total", 0)
        passed = data.get("passed", 0)
        failed = data.get("failed", 0)
        fixes = data.get("fixes_applied", 0)
        print(
            f"\n  📊  {inst}: {passed}/{total} passed, {failed} failed, {fixes} healed"
        )


if __name__ == "__main__":
    main()
