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
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

TOKEN = os.getenv("SHOPIFY_TOKEN")
if TOKEN:
    TOKEN = TOKEN.strip().strip('"\'')


def log_console(msg):
    text = msg.text
    # Filter external website tracking and script noise
    ignore_patterns = (
        "GTM", "ShopifyAnalytics", "Shopify is not defined", "Meta Pixel",
        "LIQUID", "Samita", "Geolocation", "shop.app", "Ingest Labs",
        "addEventListener", "kp_customer_id", "Clear-Site-Data", "GyFTR",
        "MSDtrack", "ERR_HTTP2_PROTOCOL_ERROR"
    )
    if any(pat in text for pat in ignore_patterns):
        return

    # Highlight scraper activity
    scraper_keywords = (
        "Fetching", "fetched", "Done!", "Total SKUs", "Collected", "GraphQL", "HTTP",
        "Listing Page", "Products", "Variants", "Worker", "Completed", "SCRAPE COMPLETE"
    )
    if any(kw in text for kw in scraper_keywords):
        try:
            print(f"[SCRAPER] {text}", flush=True)
        except Exception:
            pass


async def _open_browser_page(p, url: str, timeout: int = 60_000):
    """Shared helper to launch Chromium and open an initial page."""
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    page = await browser.new_page()
    page.on("console", log_console)
    page.on("pageerror", lambda exc: print(f"[PAGE ERROR] {exc}", flush=True))

    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    return browser, page


async def scrape_columbia() -> dict:
    """Scrapes Columbia Sportswear India product data."""
    if not TOKEN:
        raise RuntimeError("SHOPIFY_TOKEN is missing from .env or environment")

    scraper_path = Path("columbia_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    async with async_playwright() as p:
        print("Launching browser for Columbia scraper...", flush=True)
        browser, page = await _open_browser_page(p, "https://www.columbiasportswear.co.in/")

        print("Injecting and starting Columbia scraper...", flush=True)
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
        print(f"COLUMBIA SCRAPING FINISHED: {len(products)} total SKUs collected", flush=True)
        print("=" * 60, flush=True)

        output_payload = {
            "schema_version": 1,
            "source": "columbia",
            "scrape_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "total_skus": len(products),
            "products": products
        }

        output_file = Path("columbia_products.json")
        output_file.write_text(
            json.dumps(output_payload, indent=2),
            encoding="utf-8"
        )
        print(f"Saved {len(products)} products to {output_file.resolve()}", flush=True)

        await browser.close()
        return output_payload


async def scrape_tata() -> dict:
    """Scrapes Tata CLiQ for Columbia products."""
    scraper_path = Path("tata_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    # Timeout for full Tata scrape (configurable via env)
    timeout_ms = int(os.getenv("TATA_SCRAPE_TIMEOUT_SECONDS", "900")) * 1000

    async with async_playwright() as p:
        print("Launching browser for Tata CLiQ scraper...", flush=True)
        browser, page = await _open_browser_page(p, "https://www.tatacliq.com/")

        print("Injecting and starting Tata CLiQ scraper...", flush=True)
        await page.evaluate(
            """([code]) => {
                window.__IS_PLAYWRIGHT__ = true;
                window.eval(code);
            }""",
            [scraper_code]
        )

        print("Tata scraper is running. Waiting for completion...", flush=True)
        await page.wait_for_function(
            "() => window.__SCRAPER_DONE__ === true",
            timeout=timeout_ms
        )

        result = await page.evaluate("() => window.scraperResult || null")

        if not result or not isinstance(result, dict):
            # Fallback if window.scraperResult was not populated
            products = await page.evaluate("() => window.output || []")
            result = {
                "schema_version": 1,
                "source": "tatacliq",
                "scrape_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "total_products": len(products),
                "total_variants": 0,
                "average_variants_per_product": 0.0,
                "products": products
            }

        total_p = result.get("total_products", len(result.get("products", [])))
        total_v = result.get("total_variants", 0)

        print("\n" + "=" * 60, flush=True)
        print(f"TATA CLIQ SCRAPING FINISHED: {total_p} products, {total_v} variants", flush=True)
        print("=" * 60, flush=True)

        output_file = Path("tatacliq_columbia_products.json")
        output_file.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8"
        )
        print(f"Saved {total_p} products to {output_file.resolve()}", flush=True)

        await browser.close()
        return result


# Backwards compatibility
main = scrape_columbia


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "columbia"
    if target.lower() in ("tata", "tatacliq"):
        asyncio.run(scrape_tata())
    else:
        asyncio.run(scrape_columbia())
