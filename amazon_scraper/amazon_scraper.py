import argparse
import asyncio
import gc
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union

# Ensure UTF-8 output on Windows consoles
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

from playwright.async_api import async_playwright, Playwright, Browser, Page
from playwright._impl._errors import Error as PlaywrightError

# Local parser utilities
try:
    from amazon_scraper.parser import (
        SellerTarget,
        parse_seller_entry,
        load_sellers_from_file,
        EXTRACT_CARDS_JS,
        merge_extracted_items,
    )
except ImportError:
    from parser import (
        SellerTarget,
        parse_seller_entry,
        load_sellers_from_file,
        EXTRACT_CARDS_JS,
        merge_extracted_items,
    )

# =============================================================================
# Ultra-Low RAM Chromium Launch Configuration (< 150MB Memory footprint)
# =============================================================================
LOW_MEMORY_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--mute-audio",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-extensions",
    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
    "--disable-ipc-flooding-protection",
    "--disable-renderer-backgrounding",
    "--js-flags=--max-old-space-size=256",
    "--disable-blink-features=AutomationControlled",
]

DEFAULT_SELLERS_FILE = Path(__file__).resolve().parent / "sellers.txt"
DEFAULT_OUTPUT_DIR = Path("data") / "amazon"
SEARCH_RESULT_SELECTOR = 'div[data-component-type="s-search-result"]'
MAX_EMPTY_PAGES = 2


async def _setup_lean_page(browser: Browser) -> Page:
    """Creates a single lean Chromium page with media resource blocking."""
    context = await browser.new_context(
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )

    page = await context.new_page()

    # Aggressive resource blocking to preserve memory and network bandwidth
    async def block_resources(route):
        req = route.request
        res_type = req.resource_type
        url_lower = req.url.lower()

        if res_type in ("image", "media", "font"):
            try:
                await route.abort()
            except Exception:
                pass
            return

        tracker_keywords = (
            "google-analytics", "googletagmanager", "facebook", "doubleclick",
            "clarity.ms", "criteo", "hotjar", "omtrdc", "demdex", "tiqcdn",
            "scorecardresearch", "adroll", "datadog", "newrelic", "sentry"
        )
        if any(kw in url_lower for kw in tracker_keywords):
            try:
                await route.abort()
            except Exception:
                pass
            return

        try:
            await route.continue_()
        except Exception:
            pass

    await page.route("**/*", block_resources)
    return page


async def run_amazon_scraper(
    sellers: Optional[Union[List[Union[str, SellerTarget]], str, Path]] = None,
    limit: Optional[int] = None,
    max_pages: int = 500,
    headless: bool = True,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    existing_browser: Optional[Browser] = None,
) -> Dict[str, Any]:
    """
    Main asynchronous Amazon scraper runner.
    Uses a SINGLE Playwright browser instance and a single reused page tab
    to iterate all pages across all configured sellers with minimum RAM consumption.
    """
    start_time = time.perf_counter()

    # 1. Resolve seller targets
    targets: List[SellerTarget] = []
    if sellers is None:
        targets = load_sellers_from_file(DEFAULT_SELLERS_FILE)
    elif isinstance(sellers, (str, Path)):
        p = Path(sellers)
        if p.exists():
            targets = load_sellers_from_file(p)
        else:
            # Comma-separated sellers string
            for item in str(sellers).split(","):
                t = parse_seller_entry(item)
                if t:
                    targets.append(t)
    elif isinstance(sellers, list):
        for item in sellers:
            if isinstance(item, SellerTarget):
                targets.append(item)
            elif isinstance(item, str):
                t = parse_seller_entry(item)
                if t:
                    targets.append(t)

    if not targets:
        # Fallback to user default
        default_t = parse_seller_entry(
            "https://www.amazon.in/s?i=merchant-items&me=AUEEW31YCNC4K&s=popularity-rank&fs=true"
        )
        if default_t:
            targets = [default_t]

    print("\n" + "=" * 65)
    print("🚀 STARTING AMAZON PLAYWRIGHT SCRAPER (SINGLE BROWSER, ULTRA-LOW RAM)")
    print(f"Configured Sellers: {len(targets)}")
    for t in targets:
        print(f"  • Seller ID: {t.seller_id} ({t.name})")
    print("=" * 65, flush=True)

    products: Dict[str, Dict[str, Any]] = {}
    total_cards_seen = 0
    total_columbia_accepted = 0
    total_rejected = 0

    own_browser = False
    browser = existing_browser
    playwright_instance: Optional[Playwright] = None

    try:
        if browser is None:
            playwright_instance = await async_playwright().start()
            browser = await playwright_instance.chromium.launch(
                headless=headless,
                ignore_default_args=["--enable-automation"],
                args=LOW_MEMORY_CHROMIUM_ARGS,
            )
            own_browser = True

        # Create single reused tab
        page = await _setup_lean_page(browser)

        for seller_idx, seller in enumerate(targets):
            print("\n" + "-" * 60)
            print(f"[{seller_idx + 1}/{len(targets)}] Scraping Seller: {seller.name} ({seller.seller_id})")
            print(f"Base URL: {seller.base_url}")
            print("-" * 60, flush=True)

            consecutive_empty_pages = 0

            for page_no in range(1, max_pages + 1):
                # Check product limit
                if limit and len(products) >= limit:
                    print(f"Reached product limit of {limit}. Stopping pagination.")
                    break

                page_url = seller.get_page_url(page_no)
                page_success = False

                for attempt in range(1, 4):
                    try:
                        # Human-like delay
                        await asyncio.sleep(random.uniform(0.8, 1.6))

                        elapsed = int(time.perf_counter() - start_time)
                        if progress_callback:
                            try:
                                await progress_callback({
                                    "stage": f"Collecting: {seller.name}",
                                    "current": page_no,
                                    "total": max_pages,
                                    "unique_products": len(products),
                                    "elapsed_seconds": elapsed,
                                })
                            except Exception:
                                pass

                        # Reset session cookies between pages to bypass Amazon rate-limit fingerprinting
                        try:
                            await page.context.clear_cookies()
                        except Exception:
                            pass

                        print(f"[{seller.seller_id}] Page {page_no:02d} (Attempt {attempt}/3)...", flush=True)
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)

                        try:
                            await page.wait_for_selector(SEARCH_RESULT_SELECTOR, timeout=12000)
                        except Exception:
                            # Might be end of catalog or bot check
                            pass

                        # Extract items directly in Chromium V8 engine (zero Python RAM overhead)
                        data = await page.evaluate(EXTRACT_CARDS_JS)
                        items = data.get("items", [])
                        has_next = data.get("hasNext", False)
                        no_results = data.get("noResults", False)
                        is_bot = data.get("isBot", False)
                        is_503 = data.get("is503", False)

                        if is_bot or is_503:
                            reason = "bot challenge" if is_bot else "transient 503"
                            print(f"⚠️ [WARNING] Amazon presented {reason} on page {page_no} (Attempt {attempt}/3). Retrying in 4s...")
                            await asyncio.sleep(4.0)
                            continue

                        if len(items) == 0:
                            if no_results:
                                print(f"ℹ️ Amazon returned 'No results' for seller {seller.seller_id} at page {page_no}. Reached end of catalog.")
                                consecutive_empty_pages = MAX_EMPTY_PAGES
                                page_success = True
                                break
                            
                            # If no cards found and not explicit no-results, retry attempt first before treating as empty
                            if attempt < 3:
                                print(f"⚠️ [WARNING] 0 items parsed on page {page_no}. Retrying attempt {attempt + 1}...")
                                await asyncio.sleep(3.0)
                                continue

                            consecutive_empty_pages += 1
                            if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                                print(f"ℹ️ {MAX_EMPTY_PAGES} consecutive empty pages encountered. Seller finished at page {page_no}.")
                                page_success = True
                                break
                        else:
                            consecutive_empty_pages = 0

                        # Merge into master dict
                        seen, columbia_acc, rejected = merge_extracted_items(
                            products, items, seller.seller_id, seller.name
                        )
                        total_cards_seen += seen
                        total_columbia_accepted += columbia_acc
                        total_rejected += rejected

                        print(
                            f"  ↳ Page {page_no:02d} | Cards: {len(items):02d} | "
                            f"Columbia: {columbia_acc:02d} | Unique ASINs: {len(products)}"
                        )

                        page_success = True

                        # If next button disabled or absent and cards were fewer than standard 16
                        if not has_next:
                            print(f"ℹ️ No next page button found on page {page_no}. Reached end of seller catalog.")
                            break

                        break  # Break retry loop on success

                    except Exception as exc:
                        print(f"⚠️ Error on page {page_no} (Attempt {attempt}/3): {exc}", flush=True)
                        await asyncio.sleep(2.5)

                if not page_success and consecutive_empty_pages >= MAX_EMPTY_PAGES:
                    break

                if page_success and not has_next:
                    print(f"ℹ️ Reached last page of catalog for seller {seller.seller_id} at page {page_no}.")
                    break

                if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                    break

            # Reclaim garbage collection after each seller
            gc.collect()

    finally:
        # Gracefully shut down single browser tab and browser
        if own_browser:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    await playwright_instance.stop()
                except Exception:
                    pass
        gc.collect()
        print("[BROWSER] Playwright browser closed. RAM reclaimed.", flush=True)

    elapsed_total = time.perf_counter() - start_time
    minutes = int(elapsed_total // 60)
    seconds = elapsed_total % 60

    print("\n" + "=" * 65)
    print("                AMAZON SCRAPE COMPLETE SUMMARY")
    print("=" * 65)
    print(f"Total Cards Seen        : {total_cards_seen:,}")
    print(f"Columbia Products Found : {total_columbia_accepted:,}")
    print(f"Other Products Seen     : {total_rejected:,}")
    print(f"Total Unique ASINs      : {len(products):,}")
    print(f"Execution Time          : {minutes}m {seconds:.2f}s")
    print("=" * 65 + "\n", flush=True)

    # 4. Save snapshots matching old scraper format
    scraped_at = datetime.now(timezone.utc).isoformat()
    scrape_date = scraped_at[:10]
    payload = {
        "schema_version": 1,
        "source": "amazonV4",
        "scrape_date": scrape_date,
        "scraped_at": scraped_at,
        "total_cards_seen": total_cards_seen,
        "columbia_products": total_columbia_accepted,
        "unique_products": len(products),
        "products": list(products.values()),
    }

    # Save dated backup in data/amazon/YYYY-MM-DD.json
    dated_dir = DEFAULT_OUTPUT_DIR
    dated_dir.mkdir(parents=True, exist_ok=True)
    dated_file = dated_dir / f"{scrape_date}.json"
    dated_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"💾 Saved dated snapshot to: {dated_file.resolve()}")

    # Save backwards-compatible local files
    Path("seller_products.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    Path("amazon_products.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"💾 Saved local snapshot to: {Path('amazon_products.json').resolve()}")

    return {
        "status": "completed",
        "total_cards": total_cards_seen,
        "completed_products": len(products),
        "columbia_products": total_columbia_accepted,
        "unique_asins": len(products),
        "duration_seconds": round(elapsed_total, 2),
        "products": list(products.values()),
        "dated_file": str(dated_file),
    }


def cli_main():
    parser = argparse.ArgumentParser(description="Amazon Playwright Low-RAM Scraper")
    parser.add_argument(
        "--sellers", "-s",
        type=str,
        default=None,
        help="Path to sellers.txt, or a seller URL, or seller ID (e.g. AUEEW31YCNC4K)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Max unique products to extract (useful for testing)"
    )
    parser.add_argument(
        "--max-pages", "-p",
        type=int,
        default=500,
        help="Maximum pages to scrape per seller (default: 500)"
    )
    parser.add_argument(
        "--headless",
        type=lambda v: str(v).lower() in ("true", "1", "yes"),
        default=True,
        help="Run browser in headless mode (default: True)"
    )
    args = parser.parse_args()

    asyncio.run(
        run_amazon_scraper(
            sellers=args.sellers,
            limit=args.limit,
            max_pages=args.max_pages,
            headless=args.headless,
        )
    )


if __name__ == "__main__":
    cli_main()
