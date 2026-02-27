"""Helper script to start Playwright Codegen using the existing Chase profile."""

import os
from extractors.chase_connector import ChaseConnector


def main():
    print("Starting Chase in interactive Codegen mode...")
    connector = ChaseConnector(headless=False)

    # Use the connector's existing launch logic to get the correct profile
    # This automatically handles the "C:\ChromeAutomationProfile" CDP connection
    with connector._launch() as (context, page):
        print("\n" + "=" * 50)
        print("       PLAYWRIGHT INSPECTOR IS OPENING")
        print("=" * 50)
        print("1. Find the 'Playwright Inspector' window that just appeared.")
        print("2. Click the 'Record' button (red circle) at the top of the Inspector.")
        print(
            "3. Interact with the Chase website normally. Playwright will generate code."
        )
        print("4. Navigate to the area of the site you want to automate.")
        print(
            "5. When done, copy the code generated in the Inspector and paste it in our chat!"
        )
        print("   (To exit, close the Inspector window or press Ctrl+C here)")
        print("=" * 50 + "\n")

        # Navigate to Chase
        page.goto("https://www.chase.com", wait_until="domcontentloaded")

        # Pause execution and open the Playwright Inspector
        page.pause()


if __name__ == "__main__":
    main()
