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

# Local parser utilities from amazon_v4
try:
    from amazon_v4.parser import (
        SellerTarget,
        parse_seller_entry,
        load_sellers_from_file,
        EXTRACT_CARDS_JS,
        merge_extracted_items,
        clean_price,
    )
except ImportError:
    from parser import (
        SellerTarget,
        parse_seller_entry,
        load_sellers_from_file,
        EXTRACT_CARDS_JS,
        merge_extracted_items,
        clean_price,
    )

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
    """Blocks non-document assets to speed up browsing and save bandwidth/RAM."""
    res_type = route.request.resource_type
    if res_type in ("image", "media", "font", "stylesheet", "other"):
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
    """Fetches a single Amazon seller page in an isolated context and evaluates cards."""
    context = await browser.new_context(
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )
    page = await context.new_page()
    await page.route("**/*", _block_non_document_resources)
    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await page.wait_for_selector(SEARCH_RESULT_SELECTOR, timeout=8000)
        except Exception:
            pass

        data = await page.evaluate(EXTRACT_CARDS_JS)
        return data if isinstance(data, dict) else {"items": []}
    finally:
        await page.close()
        await context.close()


async def run_amazon_scraper(
    sellers: Union[str, Path, List[SellerTarget]] = DEFAULT_SELLERS_FILE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_pages: int = 150,
    headless: bool = True,
    existing_browser: Optional[Browser] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    chunk_callback: Optional[Callable[[List[Dict[str, Any]]], Any]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes the Amazon Columbia scraper v4 across target sellers.
    Captures:
    - Actual price & M.R.P. (List price)
    - Stock status & exact quantity left
    - Payment offers (Bank discounts, EMI options, Cashback)
    """
    start_time = time.perf_counter()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    targets: List[SellerTarget] = []
    if isinstance(sellers, (str, Path)):
        p = Path(sellers)
        if p.exists():
            targets = load_sellers_from_file(p)
        else:
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
        default_t = parse_seller_entry(
            "https://www.amazon.in/s?i=merchant-items&me=AUEEW31YCNC4K&s=popularity-rank&fs=true"
        )
        if default_t:
            targets = [default_t]

    print("\n" + "=" * 65)
    print("[amazon_v4](init) STARTING AMAZON V4 SCRAPER (OFFERS, STOCK, & DUAL PRICES)")
    print(f"[amazon_v4](config) Configured Sellers: {len(targets)}")
    for t in targets:
        print(f"[amazon_v4](config)   • Seller ID: {t.seller_id} ({t.name})")
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
            print(f"[amazon_v4](collecting) [{seller_idx + 1}/{len(targets)}] Scraping Seller: {seller.name} ({seller.seller_id})")
            print(f"[amazon_v4](collecting) Base URL: {seller.base_url}")
            print("-" * 60, flush=True)

            consecutive_empty_pages = 0

            for page_no in range(1, max_pages + 1):
                if limit and len(products) >= limit:
                    print(f"[amazon_v4](collecting) Reached limit of {limit}. Stopping pagination.")
                    break

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

                        print(f"[amazon_v4](collecting) [{seller.name}] Page {page_no:02d} (Attempt {attempt}/3)...", flush=True)
                        data = await _fetch_seller_page(browser, page_url, timeout=50000)

                        items = data.get("items", [])
                        has_next = data.get("hasNext", False)
                        no_results = data.get("noResults", False)
                        is_bot = data.get("isBot", False)
                        is_503 = data.get("is503", False)

                        if is_bot or is_503:
                            wait_sec = attempt * 8
                            print(f"[amazon_v4](bot/503 warning) Seller {seller.name} p.{page_no}: Waiting {wait_sec}s...")
                            await asyncio.sleep(wait_sec)
                            continue

                        cards_seen, acc, rej = merge_extracted_items(
                            products, items, seller.seller_id, seller.name
                        )
                        total_cards_seen += cards_seen
                        total_columbia_accepted += acc
                        total_rejected += rej

                        print(
                            f"[amazon_v4](page complete) [{seller.name}] Page {page_no:02d} done: "
                            f"{len(items)} cards | +{acc} Columbia (Total: {len(products)} products)"
                        )

                        # Stream chunk
                        if chunk_callback and items:
                            page_items = [products[it["asin"]] for it in items if it["asin"] in products]
                            pending_chunk.extend(page_items)
                            if len(pending_chunk) >= 50:
                                await chunk_callback(pending_chunk)
                                pending_chunk = []

                        page_success = True

                        if not items or no_results:
                            consecutive_empty_pages += 1
                            if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                                print(f"[amazon_v4](pagination) Hit {consecutive_empty_pages} consecutive empty pages. Ending seller.")
                                break
                        else:
                            consecutive_empty_pages = 0

                        if not has_next:
                            print(f"[amazon_v4](pagination) No next page indicator. Completed {seller.name}.")
                            break

                        break

                    except PlaywrightError as pe:
                        print(f"[amazon_v4](network error) Page {page_no} attempt {attempt}: {pe}")
                        await asyncio.sleep(3)
                    except Exception as e:
                        print(f"[amazon_v4](unexpected error) Page {page_no} attempt {attempt}: {e}")
                        await asyncio.sleep(3)

                if not page_success or consecutive_empty_pages >= MAX_EMPTY_PAGES or not has_next:
                    break

        if chunk_callback and pending_chunk:
            await chunk_callback(pending_chunk)
            pending_chunk = []

    finally:
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

    total_time = round(time.perf_counter() - start_time, 2)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    columbia_prods = [p for p in products.values() if p.get("is_columbia")]

    output_payload = {
        "schema_version": 2,
        "source": "amazonV4",
        "scrape_date": today_str,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_cards_seen": total_cards_seen,
        "columbia_products": len(columbia_prods),
        "unique_products": len(products),
        "execution_time_seconds": total_time,
        "products": list(products.values()),
    }

    dated_file = output_dir / f"{today_str}.json"
    latest_file = output_dir / "amazon_data.json"

    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print("[amazon_v4](finished) AMAZON V4 SCRAPE FINISHED SUCCESSFULLY")
    print(f"[amazon_v4](summary) Total Cards Processed: {total_cards_seen}")
    print(f"[amazon_v4](summary) Columbia Products:     {len(columbia_prods)}")
    print(f"[amazon_v4](summary) Unique ASINs Tracked:   {len(products)}")
    print(f"[amazon_v4](summary) Execution Time:         {total_time}s")
    print(f"[amazon_v4](summary) Saved JSON:             {latest_file}")
    print("=" * 65 + "\n", flush=True)

    return output_payload


def main():
    parser = argparse.ArgumentParser(description="Amazon Columbia Scraper v4")
    parser.add_argument("--sellers", type=str, default=str(DEFAULT_SELLERS_FILE))
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-pages", type=int, default=150)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    asyncio.run(
        run_amazon_scraper(
            sellers=args.sellers,
            output_dir=Path(args.output_dir),
            max_pages=args.max_pages,
            headless=args.headless,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
