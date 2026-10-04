import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright


# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

TOKEN = os.getenv("SHOPIFY_TOKEN")

if not TOKEN:
    raise RuntimeError("SHOPIFY_TOKEN is missing from .env or environment")

TOKEN = TOKEN.strip().strip('"\'')


def log_console(msg):
    text = msg.text
    # Filter external website tracking and script noise
    ignore_patterns = (
        "GTM", "ShopifyAnalytics", "Shopify is not defined", "Meta Pixel",
        "LIQUID", "Samita", "Geolocation", "shop.app", "Ingest Labs",
        "addEventListener", "kp_customer_id", "Clear-Site-Data", "GyFTR"
    )
    if any(pat in text for pat in ignore_patterns):
        return

    # Highlight scraper activity
    scraper_keywords = ("Fetching Page", "fetched", "Done!", "Total SKUs", "Collected", "GraphQL", "HTTP")
    if any(kw in text for kw in scraper_keywords):
        try:
            print(f"[SCRAPER] {text}", flush=True)
        except Exception:
            pass


async def main():
    scraper_path = Path("columbia_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    async with async_playwright() as p:
        print("Launching Chromium browser...", flush=True)
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        page = await browser.new_page()

        page.on("console", log_console)
        page.on("pageerror", lambda exc: print(f"[PAGE ERROR] {exc}", flush=True))

        print("Navigating to Columbia Sportswear India...", flush=True)
        await page.goto(
            "https://www.columbiasportswear.co.in/",
            wait_until="domcontentloaded",
            timeout=60_000
        )

        print("Injecting and starting scraper...", flush=True)
        await page.evaluate(
            """([code, token]) => {
                window.__SHOPIFY_TOKEN__ = token;
                window.__IS_PLAYWRIGHT__ = true;
                window.eval(code);
            }""",
            [scraper_code, TOKEN]
        )

        print("Scraper is running. Waiting for completion...", flush=True)
        await page.wait_for_function(
            "() => window.__SCRAPER_DONE__ === true",
            timeout=180_000
        )

        products = await page.evaluate("() => window.output || []")

        print("\n" + "=" * 60, flush=True)
        print(f"SCRAPING FINISHED: {len(products)} total SKUs collected", flush=True)
        print("=" * 60, flush=True)

        if products:
            print("\nSample Product (first SKU):", flush=True)
            print(json.dumps(products[0], indent=2), flush=True)

        output_payload = {
            "schema_version": 1,
            "source": "columbia",
            "scrape_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "total_skus": len(products),
            "products": products
        }

        output_file = Path("columbia_products.json")
        output_file.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        print(f"\nSaved {len(products)} products to {output_file.resolve()}", flush=True)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())