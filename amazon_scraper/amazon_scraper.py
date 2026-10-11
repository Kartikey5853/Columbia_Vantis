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
    "--no-zygote",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-extensions",
    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
    "--disable-ipc-flooding-protection",
    "--disable-renderer-backgrounding",
    "--js-flags=--max-old-space-size=64",
    "--disable-blink-features=AutomationControlled",
]

DEFAULT_SELLERS_FILE = Path(__file__).resolve().parent / "sellers.txt"
DEFAULT_OUTPUT_DIR = Path("data") / "amazon"
SEARCH_RESULT_SELECTOR = 'div[data-component-type="s-search-result"]'
MAX_EMPTY_PAGES = 2


async def _block_non_document_resources(route):
    """Aggressively blocks all assets, scripts, stylesheets, and fonts to ensure pure zero-JS HTML DOM."""
    res_type = route.request.resource_type
    if res_type in ("image", "media", "font", "stylesheet", "script", "other"):
        try:
            await route.abort()
        except Exception:
            pass
        return
    try:
        await route.continue_()
    except Exception:
        pass


async def _fetch_seller_page(browser: Browser, page_url: str, timeout: int = 45000) -> Dict[str, Any]:
    """Fetches a single Amazon seller page in an isolated context and destroys both page and context immediately."""
    context = await browser.new_context(
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )
    page = await context.new_page()
    await page.route("**/*", _block_non_document_resources)
    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await page.wait_for_selector(SEARCH_RESULT_SELECTOR, timeout=12000)
        except Exception:
            pass
        data = await page.evaluate(EXTRACT_CARDS_JS)
        return data or {}
    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass


async def run_amazon_scraper(
    sellers: Optional[Union[List[Union[str, SellerTarget]], str, Path]] = None,
    limit: Optional[int] = None,
    max_pages: int = 500,
    headless: bool = True,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    chunk_callback: Optional[Callable[[List[Dict[str, Any]]], Any]] = None,
    existing_browser: Optional[Browser] = None,
) -> Dict[str, Any]:
    """
    Main asynchronous Amazon scraper runner.
    Uses ultra-low-memory per-page context isolation (destroying tabs & contexts after every page)
    and relaunches Chromium every 10 pages to prevent memory leaks.
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
    print("[amazon](init) STARTING AMAZON PLAYWRIGHT SCRAPER (SINGLE BROWSER, ULTRA-LOW RAM)")
    print(f"[amazon](config) Configured Sellers: {len(targets)}")
    for t in targets:
        print(f"[amazon](config)   • Seller ID: {t.seller_id} ({t.name})")
    print("=" * 65, flush=True)

    products: Dict[str, Dict[str, Any]] = {}
    pending_chunk: List[Dict[str, Any]] = []
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

        pages_since_browser_recycle = 0

        for seller_idx, seller in enumerate(targets):
            print("\n" + "-" * 60)
            print(f"[amazon](collecting data) [{seller_idx + 1}/{len(targets)}] Scraping Seller: {seller.name} ({seller.seller_id})")
            print(f"[amazon](collecting data) Base URL: {seller.base_url}")
            print("-" * 60, flush=True)

            consecutive_empty_pages = 0

            for page_no in range(1, max_pages + 1):
                # Check product limit
                if limit and len(products) >= limit:
                    print(f"[amazon](collecting data) Reached product limit of {limit}. Stopping pagination.")
                    break

                # Recycle entire browser process every 10 pages to fully reclaim OS memory
                pages_since_browser_recycle += 1
                if pages_since_browser_recycle > 10 and own_browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    browser = await playwright_instance.chromium.launch(
                        headless=headless,
                        ignore_default_args=["--enable-automation"],
                        args=LOW_MEMORY_CHROMIUM_ARGS,
                    )
                    pages_since_browser_recycle = 1
                    gc.collect()

                page_url = seller.get_page_url(page_no)
                page_success = False

                for attempt in range(1, 4):
                    try:
                        # Human-like delay
                        await asyncio.sleep(random.uniform(0.6, 1.2))

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

                        print(f"[amazon](collecting data) [{seller.name}] Page {page_no:02d} (Attempt {attempt}/3)...", flush=True)
                        data = await _fetch_seller_page(browser, page_url, timeout=50000)

                        items = data.get("items", [])
                        has_next = data.get("hasNext", False)
                        no_results = data.get("noResults", False)
                        is_bot = data.get("isBot", False)
                        is_503 = data.get("is503", False)

                        if is_bot or is_503:
                            reason = "bot challenge" if is_bot else "transient 503"
                            print(f"[amazon](bot guard) Amazon presented {reason} on page {page_no} (Attempt {attempt}/3). Retrying in 4s...")
                            await asyncio.sleep(4.0)
                            continue

                        if len(items) == 0:
                            if no_results:
                                print(f"[amazon](collecting data) Amazon returned 'No results' for seller {seller.name} at page {page_no}. Reached end of catalog.")
                                consecutive_empty_pages = MAX_EMPTY_PAGES
                                page_success = True
                                break
                            
                            # If no cards found and not explicit no-results, retry attempt first before treating as empty
                            if attempt < 3:
                                print(f"[amazon](collecting data) 0 items parsed on page {page_no}. Retrying attempt {attempt + 1}...")
                                await asyncio.sleep(3.0)
                                continue

                            consecutive_empty_pages += 1
                            if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                                print(f"[amazon](collecting data) {MAX_EMPTY_PAGES} consecutive empty pages encountered. Seller finished at page {page_no}.")
                                page_success = True
                                break
                        else:
                            consecutive_empty_pages = 0

                        # Merge into master dict
                        prev_count = len(products)
                        seen, columbia_acc, rejected = merge_extracted_items(
                            products, items, seller.seller_id, seller.name
                        )
                        total_cards_seen += seen
                        total_columbia_accepted += columbia_acc
                        total_rejected += rejected

                        # Collect new products added in this page for streaming persistence
                        if chunk_callback and len(products) > prev_count:
                            new_items = list(products.values())[prev_count:]
                            pending_chunk.extend(new_items)
                            if len(pending_chunk) >= 20 or page_no % 2 == 0:
                                try:
                                    res = chunk_callback(pending_chunk)
                                    if asyncio.iscoroutine(res):
                                        await res
                                    pending_chunk = []
                                    gc.collect()
                                except Exception as cb_err:
                                    print(f"[amazon](storing in database) Warning in chunk_callback: {cb_err}")

                        print(
                            f"[amazon](collecting data) ↳ Page {page_no:02d} | Cards: {len(items):02d} | "
                            f"Columbia: {columbia_acc:02d} | Unique ASINs: {len(products)}"
                        )

                        page_success = True

                        # If next button disabled or absent and cards were fewer than standard 16
                        if not has_next:
                            print(f"[amazon](collecting data) No next page button found on page {page_no}. Reached end of seller catalog.")
                            break

                        break  # Break retry loop on success

                    except Exception as exc:
                        print(f"[amazon](collecting data) Error on page {page_no} (Attempt {attempt}/3): {exc}", flush=True)
                        await asyncio.sleep(2.5)

                if not page_success and consecutive_empty_pages >= MAX_EMPTY_PAGES:
                    break

                if page_success and not has_next:
                    print(f"[amazon](collecting data) Reached last page of catalog for seller {seller.name} at page {page_no}.")
                    break

                if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                    break

            # Flush any remaining items in pending_chunk for this seller
            if chunk_callback and pending_chunk:
                try:
                    res = chunk_callback(pending_chunk)
                    if asyncio.iscoroutine(res):
                        await res
                    pending_chunk = []
                except Exception as cb_err:
                    print(f"[amazon](storing in database) Warning in chunk_callback: {cb_err}")

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
        print("[amazon](cleanup) Playwright browser closed. RAM reclaimed.", flush=True)

    elapsed_total = time.perf_counter() - start_time
    minutes = int(elapsed_total // 60)
    seconds = elapsed_total % 60

    print("\n" + "=" * 65)
    print("                AMAZON SCRAPE COMPLETE SUMMARY")
    print("=" * 65)
    print(f"[amazon](summary) Total Cards Seen        : {total_cards_seen:,}")
    print(f"[amazon](summary) Columbia Products Found : {total_columbia_accepted:,}")
    print(f"[amazon](summary) Other Products Seen     : {total_rejected:,}")
    print(f"[amazon](summary) Total Unique ASINs      : {len(products):,}")
    print(f"[amazon](summary) Execution Time          : {minutes} min {seconds:.1f} sec ({elapsed_total:.1f}s)")
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
