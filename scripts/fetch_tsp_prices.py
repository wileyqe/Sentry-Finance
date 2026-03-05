"""
One-time script to download TSP share price history from tsp.gov via Playwright.

TSP.gov blocks programmatic HTTP requests (Cloudflare), so we use
a real browser to navigate to the share price history page, select
the date range, and download the CSV.

Usage:
    python scripts/fetch_tsp_prices.py

Output:
    raw_exports/TSP/share_prices.csv
"""

import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_exports" / "TSP"
DEST = RAW_DIR / "share_prices.csv"

# Date range: from before the statement start to today
START_DATE = "2024-03-01"  # Go back before statement period
END_DATE = date.today().strftime("%Y-%m-%d")


def main():
    from playwright.sync_api import sync_playwright

    print("\n  \U0001f3db\ufe0f  Fetching TSP Share Prices via Browser")
    print(f"  📅  Range: {START_DATE} → {END_DATE}")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="chrome")
        page = browser.new_page()

        # Navigate to the share price history page
        print("  📍  Navigating to tsp.gov share price history...")
        page.goto(
            "https://www.tsp.gov/fund-performance/share-price-history/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)

        # The page has:
        # - Start/End date pickers
        # - Fund selection checkboxes
        # - A "Download results" button
        #
        # We need to:
        # 1. Set the start date
        # 2. Set the end date
        # 3. Check "L Funds" checkbox (to include all L funds)
        # 4. Click "Download results"

        # Try to find and fill the date inputs
        try:
            # Select "All" for investment funds to get everything
            # Look for radio/checkbox options
            page.wait_for_timeout(2000)

            # Set start date
            start_input = page.query_selector(
                'input[name="startdate"], input#startDate, input[aria-label*="start" i]'
            )
            if start_input:
                start_input.click()
                start_input.fill(START_DATE.replace("-", "/"))
                print(f"  ✓ Start date: {START_DATE}")

            # Set end date
            end_input = page.query_selector(
                'input[name="enddate"], input#endDate, input[aria-label*="end" i]'
            )
            if end_input:
                end_input.click()
                end_input.fill(END_DATE.replace("-", "/"))
                print(f"  ✓ End date: {END_DATE}")

            # Check L Funds
            l_funds_check = page.query_selector(
                'input[value="lfunds"], label:has-text("L Fund") input'
            )
            if l_funds_check:
                l_funds_check.check()
                print("  ✓ L Funds selected")

            page.wait_for_timeout(1000)

            # Look for download/submit button
            with page.expect_download(timeout=30000) as download_info:
                download_btn = page.query_selector(
                    'button:has-text("Download"), a:has-text("Download"), '
                    'input[type="submit"][value*="Download"]'
                )
                if download_btn:
                    download_btn.click()
                    print("  ✓ Download triggered")

            download = download_info.value
            download.save_as(str(DEST))
            print(f"  ✓ Saved: {DEST}")

        except Exception as e:
            print(f"  ⚠ Automated download failed: {e}")
            print("\n  Manual fallback:")
            print(f"  1. The browser is open at tsp.gov")
            print(f"  2. Select start date: {START_DATE}")
            print(f"  3. Select end date: {END_DATE}")
            print("  4. Check both 'Individual Funds' and 'L Funds'")
            print("  5. Click 'Download results'")
            print(f"  6. Save the file as: {DEST}")
            print("\n  Press Enter when done (or Ctrl+C to abort)...")
            try:
                input()
            except KeyboardInterrupt:
                pass

        browser.close()

    # Verify the download
    if DEST.exists():
        import pandas as pd

        df = pd.read_csv(DEST)
        print(f"\n  ✅  Downloaded {len(df)} rows of TSP share price data")
        print(f"  Columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  Date range: {df.iloc[0, 0]} → {df.iloc[-1, 0]}")
    else:
        print(f"\n  ❌  File not found at {DEST}")
        sys.exit(1)


if __name__ == "__main__":
    main()
