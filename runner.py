import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import httpx
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

from persistence.models import NormalizedProduct, NormalizedVariant
from persistence.supabase_client import get_supabase_client
from persistence.run_store import (
    get_or_create_daily_run,
    update_run_stage,
    update_run_counts,
    complete_run,
    fail_run,
)
from persistence.checkpoint_store import (
    init_product_progress,
    mark_product_in_progress,
    mark_product_completed,
    mark_product_failed,
    get_incomplete_products,
    batch_record_product_progress,
)
from persistence.product_store import (
    upsert_canonical_product,
    upsert_canonical_products_batch,
    record_price_if_changed,
    batch_record_prices_if_changed,
)
from persistence.exporter import export_canonical_backup

SCRAPER_DIR = Path("scraper")

TOKEN = os.getenv("SHOPIFY_TOKEN")
if TOKEN:
    TOKEN = TOKEN.strip().strip('"\'')


def log_console(msg):
    text = msg.text
    ignore_patterns = (
        "GTM", "ShopifyAnalytics", "Shopify is not defined", "Meta Pixel",
        "LIQUID", "Samita", "Geolocation", "shop.app", "Ingest Labs",
        "addEventListener", "kp_customer_id", "Clear-Site-Data", "GyFTR",
        "MSDtrack", "ERR_HTTP2_PROTOCOL_ERROR"
    )
    if any(pat in text for pat in ignore_patterns):
        return

    scraper_keywords = (
        "Fetching", "fetched", "Done!", "Total SKUs", "Collected", "GraphQL", "HTTP",
        "Listing Page", "Products", "Variants", "Worker", "Completed", "SCRAPE COMPLETE", "TEST MODE"
    )
    if any(kw in text for kw in scraper_keywords):
        try:
            print(f"[SCRAPER] {text}", flush=True)
        except Exception:
            pass


# =========================================================================
# Shared Single Browser & Ultra-Low-RAM Infrastructure
# =========================================================================

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
    "--disable-http2",
]

_SHARED_PLAYWRIGHT = None
_SHARED_BROWSER = None
_ACTIVE_PAGE = None
_SCRAPER_LOCK = asyncio.Lock()


async def get_shared_browser():
    """Returns the persistent single Chromium instance, launching it if not yet started."""
    global _SHARED_PLAYWRIGHT, _SHARED_BROWSER
    if _SHARED_BROWSER and _SHARED_BROWSER.is_connected():
        return _SHARED_BROWSER

    if _SHARED_PLAYWRIGHT is None:
        _SHARED_PLAYWRIGHT = await async_playwright().start()

    print("[BROWSER] Launching shared single Chromium instance (RAM-optimized)...", flush=True)
    _SHARED_BROWSER = await _SHARED_PLAYWRIGHT.chromium.launch(
        headless=True,
        args=LOW_MEMORY_CHROMIUM_ARGS
    )
    return _SHARED_BROWSER


async def close_shared_browser():
    """Explicitly closes any open tab and shuts down the shared browser."""
    global _SHARED_PLAYWRIGHT, _SHARED_BROWSER, _ACTIVE_PAGE
    if _ACTIVE_PAGE:
        try:
            if not _ACTIVE_PAGE.is_closed():
                await _ACTIVE_PAGE.close()
        except Exception:
            pass
        _ACTIVE_PAGE = None

    if _SHARED_BROWSER:
        try:
            await _SHARED_BROWSER.close()
        except Exception:
            pass
        _SHARED_BROWSER = None

    if _SHARED_PLAYWRIGHT:
        try:
            await _SHARED_PLAYWRIGHT.stop()
        except Exception:
            pass
        _SHARED_PLAYWRIGHT = None


async def _create_lean_tab(browser, url: str, timeout: int = 60_000):
    """
    Open a single lean Chrome tab with aggressive resource blocking
    to minimize memory usage on constrained servers.
    """
    global _ACTIVE_PAGE
    if _ACTIVE_PAGE:
        try:
            if not _ACTIVE_PAGE.is_closed():
                await _ACTIVE_PAGE.close()
        except Exception:
            pass
        _ACTIVE_PAGE = None

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="en-US"
    )
    page = await context.new_page()
    _ACTIVE_PAGE = page

    page.on("console", log_console)
    page.on("pageerror", lambda exc: print(f"[PAGE ERROR] {exc}", flush=True))

    async def block_unnecessary_resources(route):
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
            "branch.io", "scorecardresearch", "adroll", "datadog", "newrelic",
            "sentry", "shopifyanalytics"
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

    await page.route("**/*", block_unnecessary_resources)

    for attempt in range(1, 4):
        try:
            print(f"[BROWSER] Navigating single tab to {url} (attempt {attempt}/3)...", flush=True)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            break
        except Exception as e:
            if attempt == 3:
                raise
            print(f"[BROWSER] Navigation retry {attempt}/3 due to: {e}", flush=True)
            await asyncio.sleep(2)
    return page


async def _wait_and_poll_progress(
    page,
    done_flag: str,
    progress_flag: str,
    timeout_ms: int,
    poll_interval: float = 2.0,
    callback=None
) -> bool:
    """Wait for completion while periodically streaming progress to callback."""
    start_t = time.perf_counter()
    timeout_sec = timeout_ms / 1000.0

    while time.perf_counter() - start_t < timeout_sec:
        is_done = await page.evaluate(f"() => window.{done_flag} === true")
        if is_done:
            return True

        if callback:
            prog = await page.evaluate(f"() => window.{progress_flag} || null")
            if prog:
                try:
                    await callback(prog)
                except Exception:
                    pass

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Scraper execution timed out after {timeout_sec} seconds")


# =========================================================================
# Columbia Product Normalization
# =========================================================================

def group_columbia_products(raw_items: List[Dict[str, Any]]) -> List[NormalizedProduct]:
    """
    Groups raw variant items from columbia_scraper.js into canonical NormalizedProduct objects.
    Each product has one canonical row per source_product_id with its variants JSON array.
    """
    grouped: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue

        if pid not in grouped:
            grouped[pid] = {
                "source_product_id": pid,
                "title": item.get("title") or "",
                "sku": item.get("sku"),
                "ean": item.get("ean"),
                "price": float(item.get("price") or 0.0),
                "mrp": float(item.get("mrp") or 0.0) if item.get("mrp") else None,
                "available": bool(item.get("available")),
                "image_url": item.get("image_url"),
                "url": item.get("url"),
                "variants": [],
            }

        # Add variant
        variant = NormalizedVariant(
            size="",
            sku=item.get("sku"),
            ean=item.get("ean"),
            available=bool(item.get("available")),
            price=float(item.get("price") or 0.0),
            mrp=float(item.get("mrp") or 0.0) if item.get("mrp") else None,
            url=item.get("url"),
        )
        grouped[pid]["variants"].append(variant)

    norm_products = []
    for pid, data in grouped.items():
        norm_products.append(
            NormalizedProduct(
                source="columbia",
                source_product_id=data["source_product_id"],
                title=data["title"],
                sku=data["sku"],
                ean=data["ean"],
                price=data["price"],
                mrp=data["mrp"],
                available=data["available"],
                image_url=data["image_url"],
                url=data["url"],
                variants=data["variants"],
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return norm_products


# =========================================================================
# Columbia Sportswear Scraper (Browser JS + Supabase Persistence)
# =========================================================================

async def scrape_columbia(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Scrapes Columbia Sportswear India product data using the browser JS scraper,
    then normalizes and persists canonical products and price history into Supabase.
    """
    if not TOKEN:
        raise RuntimeError("SHOPIFY_TOKEN is missing from .env or environment")

    cli = client or get_supabase_client()
    print("\n" + "=" * 60)
    print("STARTING COLUMBIA SPORTSWEAR INDIA SCRAPER")
    print("=" * 60, flush=True)

    # 1. Initialize or resume daily scrape run
    run = await get_or_create_daily_run("columbia", client=cli)
    run_id = run["id"]
    print(f"[RUN] Columbia Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    scraper_path = SCRAPER_DIR / "columbia_scraper.js"
    scraper_code = scraper_path.read_text(encoding="utf-8")

    raw_products = []
    async with _SCRAPER_LOCK:
        browser = await get_shared_browser()
        page = None
        try:
            print("Opening lean tab for Columbia scraper...", flush=True)
            page = await _create_lean_tab(browser, "https://www.columbiasportswear.co.in/")

            limit_val = int(limit) if limit else 0
            print("Injecting and starting Columbia scraper...", flush=True)
            await page.evaluate(
                """([code, token, limit]) => {
                    window.__SHOPIFY_TOKEN__ = token;
                    window.__IS_PLAYWRIGHT__ = true;
                    if (limit > 0) window.__PRODUCT_LIMIT__ = limit;
                    window.eval(code);
                }""",
                [scraper_code, TOKEN, limit_val]
            )

            print("Columbia scraper is running. Waiting for completion...", flush=True)
            await _wait_and_poll_progress(
                page,
                done_flag="__SCRAPER_DONE__",
                progress_flag="__SCRAPER_PROGRESS__",
                timeout_ms=180_000,
                poll_interval=1.5,
                callback=progress_callback
            )

            result = await page.evaluate("() => window.scraperResult || null")
            if result and isinstance(result, dict):
                raw_products = result.get("products", [])
            else:
                raw_products = await page.evaluate("() => window.output || []")

        finally:
            await close_shared_browser()
            import gc
            gc.collect()
            print("[BROWSER] Columbia browser closed. Memory reclaimed.", flush=True)

    # 2. Normalize raw products into canonical product structures
    await update_run_stage(run_id, "products", client=cli)
    norm_products = group_columbia_products(raw_products)
    if limit:
        norm_products = norm_products[:limit]

    # 2. Batch Persist into Supabase in chunks of 200
    batch_size = 200
    print(f"\n[PERSISTENCE] Persisting {len(norm_products)} canonical Columbia products to Supabase (batches of {batch_size})...")

    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=batch_size)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    for prod in norm_products:
        pid = id_by_src.get(prod.source_product_id)
        if pid:
            price_entries.append({
                "product_id": pid,
                "price": prod.price,
                "mrp": prod.mrp
            })
            progress_items.append({
                "product_id": pid,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants)
            })

    # Batch record prices (500 per call)
    price_records_count = await batch_record_prices_if_changed(
        price_entries, scrape_run_id=run_id, client=cli, batch_size=batch_size
    )

    # Batch record checkpoints (500 per call)
    await batch_record_product_progress(
        run_id, progress_items, status="completed", client=cli, batch_size=batch_size
    )

    persisted_count = len(progress_items)
    failed_count = len(norm_products) - persisted_count
    await update_run_counts(run_id, completed_delta=persisted_count, failed_delta=failed_count, client=cli)

    # 3. Finalize run and export local rolling backup
    await update_run_stage(run_id, "finalizing", client=cli)
    export_path = await export_canonical_backup("columbia", client=cli)
    await complete_run(run_id, client=cli)

    print("\n" + "=" * 60)
    print(f"COLUMBIA SCRAPING FINISHED: {persisted_count} products persisted")
    print(f"Price Records Added: {price_records_count}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": persisted_count,
        "failed_products": failed_count,
        "price_records_added": price_records_count,
        "export_file": str(export_path),
        "products": [p.to_dict() for p in norm_products],
    }


# =========================================================================
# Adventuras Scraper (Browser JS + Supabase Persistence)
# =========================================================================

def group_adv_products(raw_items: List[Dict[str, Any]]) -> List[NormalizedProduct]:
    """
    Groups raw variant items from adv_scraper.js into canonical NormalizedProduct objects.
    Each product has one canonical row per source_product_id with its variants JSON array.
    """
    grouped: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue

        if pid not in grouped:
            grouped[pid] = {
                "source_product_id": pid,
                "title": item.get("title") or "",
                "sku": item.get("sku") or None,
                "ean": item.get("ean") or None,
                "price": float(item.get("price") or 0.0),
                "mrp": float(item.get("mrp") or 0.0) if item.get("mrp") else None,
                "image_url": item.get("image_url") or "",
                "url": item.get("url") or "",
                "variants": [],
            }

        var = NormalizedVariant(
            size=str(item.get("size") or ""),
            sku=item.get("sku") or None,
            available=True,
            stock=0,
            url=item.get("url") or "",
        )
        grouped[pid]["variants"].append(var)
        p_val = float(item.get("price") or 0.0)
        if p_val > 0 and (grouped[pid]["price"] == 0 or p_val < grouped[pid]["price"]):
            grouped[pid]["price"] = p_val
        m_val = float(item.get("mrp") or 0.0) if item.get("mrp") else None
        if m_val and (grouped[pid]["mrp"] is None or m_val > grouped[pid]["mrp"]):
            grouped[pid]["mrp"] = m_val

    result = []
    scraped_iso = datetime.now(timezone.utc).isoformat()
    for pid, g in grouped.items():
        result.append(
            NormalizedProduct(
                source="adv",
                source_product_id=pid,
                title=g["title"],
                sku=g["sku"],
                ean=g["ean"],
                price=g["price"],
                mrp=g["mrp"],
                available=True,
                image_url=g["image_url"],
                url=g["url"],
                variants=g["variants"],
                scraped_at=scraped_iso,
            )
        )
    return result


async def scrape_adv(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Executes the Adventuras browser scraper (adv_scraper.js) via Playwright,
    then normalizes and persists all canonical products, variants, and price history to Supabase.
    """
    cli = client or get_supabase_client()
    scraper_path = SCRAPER_DIR / "adv_scraper.js"
    scraper_code = scraper_path.read_text(encoding="utf-8")

    print("\n" + "=" * 60)
    print("STARTING ADVENTURAS SCRAPER (BROWSER JS)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("adv", client=cli)
    run_id = run["id"]
    print(f"[RUN] Adventuras Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    raw_items = []
    async with _SCRAPER_LOCK:
        browser = await get_shared_browser()
        page = None
        try:
            print("Opening lean tab for Adventuras scraper...", flush=True)
            page = await _create_lean_tab(browser, "https://adventuras.in/")

            limit_val = int(limit) if limit else 0
            print("Injecting and starting Adventuras scraper...", flush=True)
            await page.evaluate(
                """([code, limit]) => {
                    window.__IS_PLAYWRIGHT__ = true;
                    if (limit > 0) window.__PRODUCT_LIMIT__ = limit;
                    window.eval(code);
                }""",
                [scraper_code, limit_val]
            )

            print("Adventuras scraper is running. Waiting for completion...", flush=True)
            await _wait_and_poll_progress(
                page,
                done_flag="__SCRAPER_DONE__",
                progress_flag="__SCRAPER_PROGRESS__",
                timeout_ms=300_000,
                poll_interval=1.5,
                callback=progress_callback
            )

            result = await page.evaluate("() => window.scraperResult || null")
            if result and isinstance(result, dict):
                raw_items = result.get("products", [])
            else:
                raw_items = await page.evaluate("() => window.output || []")

        finally:
            await close_shared_browser()
            import gc
            gc.collect()
            print("[BROWSER] Adventuras browser closed. Memory reclaimed.", flush=True)

    await update_run_stage(run_id, "products", client=cli)
    norm_products = group_adv_products(raw_items)
    if limit:
        norm_products = norm_products[:limit]

    batch_size = 200
    print(f"\n[PERSISTENCE] Persisting {len(norm_products)} canonical Adventuras products to Supabase (batches of {batch_size})...")

    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=batch_size)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    total_variants_persisted = 0
    for prod in norm_products:
        pid = id_by_src.get(prod.source_product_id)
        if pid:
            price_entries.append({
                "product_id": pid,
                "price": prod.price,
                "mrp": prod.mrp
            })
            progress_items.append({
                "product_id": pid,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants)
            })
            total_variants_persisted += len(prod.variants)

    price_records_count = await batch_record_prices_if_changed(
        price_entries, scrape_run_id=run_id, client=cli, batch_size=batch_size
    )

    await batch_record_product_progress(
        run_id, progress_items, status="completed", client=cli, batch_size=batch_size
    )

    persisted_count = len(progress_items)
    failed_count = len(norm_products) - persisted_count
    await update_run_counts(run_id, completed_delta=persisted_count, failed_delta=failed_count, client=cli)

    await update_run_stage(run_id, "finalizing", client=cli)
    export_path = await export_canonical_backup("adv", client=cli)
    await complete_run(run_id, client=cli)

    print("\n" + "=" * 60)
    print(f"ADVENTURAS SCRAPING FINISHED: {persisted_count} products persisted")
    print(f"Total Variants Persisted: {total_variants_persisted}")
    print(f"Price Records Added: {price_records_count}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": persisted_count,
        "failed_products": failed_count,
        "total_variants": total_variants_persisted,
        "price_records_added": price_records_count,
        "export_file": str(export_path),
        "products": [p.to_dict() for p in norm_products],
    }


# =========================================================================
# Myntra Scraper (Browser JS + Supabase Persistence)
# =========================================================================

def group_myntra_products(raw_items: List[Dict[str, Any]]) -> List[NormalizedProduct]:
    """
    Groups raw variant items from myntra_scraper.js into canonical NormalizedProduct objects.
    Each product has one canonical row per source_product_id with its variants JSON array.
    """
    grouped: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue

        if pid not in grouped:
            grouped[pid] = {
                "source_product_id": pid,
                "title": item.get("title") or "",
                "sku": item.get("sku") or None,
                "ean": item.get("ean") or None,
                "price": float(item.get("price") or 0.0),
                "mrp": float(item.get("mrp") or 0.0) if item.get("mrp") else None,
                "image_url": item.get("image_url") or "",
                "url": item.get("url") or "",
                "variants": [],
            }

        var = NormalizedVariant(
            size=str(item.get("size") or ""),
            sku=str(item.get("variant_id") or "") or None,
            available=True,
            stock=0,
            url=item.get("url") or "",
        )
        grouped[pid]["variants"].append(var)
        p_val = float(item.get("price") or 0.0)
        if p_val > 0 and (grouped[pid]["price"] == 0 or p_val < grouped[pid]["price"]):
            grouped[pid]["price"] = p_val
        m_val = float(item.get("mrp") or 0.0) if item.get("mrp") else None
        if m_val and (grouped[pid]["mrp"] is None or m_val > grouped[pid]["mrp"]):
            grouped[pid]["mrp"] = m_val

    result = []
    scraped_iso = datetime.now(timezone.utc).isoformat()
    for pid, g in grouped.items():
        result.append(
            NormalizedProduct(
                source="myntra",
                source_product_id=pid,
                title=g["title"],
                sku=g["sku"],
                ean=g["ean"],
                price=g["price"],
                mrp=g["mrp"],
                available=True,
                image_url=g["image_url"],
                url=g["url"],
                variants=g["variants"],
                scraped_at=scraped_iso,
            )
        )
    return result


async def fetch_myntra_raw_items(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
) -> List[Dict[str, Any]]:
    """
    Directly fetches Myntra Columbia products matching scraper/myntra_scraper.js extraction logic.
    Maintains session cookies from the web storefront and pages through the gateway search API.
    """
    rows = 50
    page = 1
    all_products: List[Dict[str, Any]] = []
    pagination_ctx = None
    scraped_iso = datetime.now(timezone.utc).isoformat()
    limit_val = int(limit) if limit else 0

    headers_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(http2=False, headers=headers_base, follow_redirects=True, timeout=20.0) as client:
        print("[MYNTRA] Initializing storefront session cookies...", flush=True)
        try:
            await client.get("https://www.myntra.com/")
        except Exception as e:
            print(f"[MYNTRA] Note: Homepage visit: {e}", flush=True)

        while True:
            offset = 0 if page == 1 else ((page - 1) * rows) - 1
            url = (
                f"https://www.myntra.com/gateway/v4/search/columbia"
                f"?rawQuery=columbia&rows={rows}&o={offset}&plaEnabled=true&xdEnabled=false&isFacet=true&p={page}&pincode=500038"
            )
            api_headers = {
                "Accept": "application/json",
                "Referer": "https://www.myntra.com/columbia",
                "x-meta-app": "channel=web",
            }
            if pagination_ctx:
                api_headers["pagination-context"] = pagination_ctx

            try:
                resp = await client.get(url, headers=api_headers)
            except Exception as e:
                print(f"[MYNTRA] Request failed on page {page}: {e}", flush=True)
                break

            if resp.status_code != 200:
                print(f"[MYNTRA] Non-200 HTTP status {resp.status_code} on page {page}", flush=True)
                break

            pagination_ctx = resp.headers.get("pagination-context")
            data = resp.json()
            products = (
                data.get("products")
                or (data.get("results") or {}).get("products")
                or (data.get("searchData") or {}).get("results", {}).get("products")
                or []
            )

            total_count = int(data.get("totalCount") or 0)
            total_pages = max(1, (total_count + rows - 1) // rows)

            for prod in products:
                pid = str(prod.get("productId") or prod.get("id") or "").strip()
                if not pid:
                    continue

                inv = prod.get("inventoryInfo")
                size_entries = []
                if isinstance(inv, list) and inv:
                    size_entries = inv
                else:
                    raw_sizes = str(prod.get("sizes") or "")
                    if raw_sizes:
                        size_entries = [{"label": s.strip(), "skuId": ""} for s in raw_sizes.split(",") if s.strip()]

                if not size_entries:
                    size_entries = [{"label": "", "skuId": ""}]

                for se in size_entries:
                    size_label = se.get("label") or prod.get("size") or prod.get("sizeName") or prod.get("variantSize") or ""
                    sku_id = str(se.get("skuId") or prod.get("buyButtonWinnerSkuId") or prod.get("variantId") or prod.get("variant_id") or prod.get("sku") or "")
                    color = prod.get("primaryColour") or prod.get("color") or prod.get("colorName") or prod.get("variantColor") or ""
                    landing = prod.get("landingPageUrl") or ""
                    p_url = f"https://www.myntra.com/{landing.lstrip('/')}" if landing else ""
                    disc_price = prod.get("discountedPrice")
                    raw_price = prod.get("price")
                    raw_mrp = prod.get("mrp")
                    price_val = float(disc_price if disc_price is not None else (raw_price if raw_price is not None else (raw_mrp or 0.0)))
                    mrp_val = float(raw_mrp if raw_mrp is not None else (raw_price if raw_price is not None else (disc_price or 0.0)))

                    all_products.append({
                        "product_id": pid,
                        "source": "myntra",
                        "sku": "",
                        "ean": "",
                        "size": size_label,
                        "color": color,
                        "variant_id": sku_id,
                        "title": prod.get("productName") or prod.get("name") or "",
                        "price": price_val,
                        "mrp": mrp_val,
                        "url": p_url,
                        "image_url": prod.get("searchImage") or prod.get("image") or "",
                        "available": True,
                        "scraped_at": scraped_iso,
                    })

                    if limit_val > 0 and len(all_products) >= limit_val:
                        break
                if limit_val > 0 and len(all_products) >= limit_val:
                    break

            if progress_callback:
                try:
                    await progress_callback({
                        "stage": "Collecting Products",
                        "current": page,
                        "total": total_pages,
                        "variant_count": len(all_products)
                    })
                except Exception:
                    pass

            print(f"[MYNTRA] Page {page}/{total_pages} processed ({len(products)} products, cumulative items: {len(all_products)})", flush=True)

            if limit_val > 0 and len(all_products) >= limit_val:
                print(f"[MYNTRA] Reached product limit {limit_val}. Stopping.", flush=True)
                break

            has_next = data.get("hasNextPage", False)
            if not has_next or len(products) == 0 or page >= total_pages:
                print("[MYNTRA] No more pages available. Finished collection.", flush=True)
                break

            page += 1
            await asyncio.sleep(0.3)

    return all_products


async def scrape_myntra(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Executes the Myntra Columbia scraper, normalizes products/variants,
    and persists canonical records and price history to Supabase.
    """
    cli = client or get_supabase_client()

    print("\n" + "=" * 60)
    print("STARTING MYNTRA COLUMBIA SCRAPER")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("myntra", client=cli)
    run_id = run["id"]
    print(f"[RUN] Myntra Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    raw_items = await fetch_myntra_raw_items(limit=limit, progress_callback=progress_callback)

    await update_run_stage(run_id, "products", client=cli)
    norm_products = group_myntra_products(raw_items)
    if limit:
        norm_products = norm_products[:limit]

    batch_size = 200
    print(f"\n[PERSISTENCE] Persisting {len(norm_products)} canonical Myntra products to Supabase (batches of {batch_size})...")

    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=batch_size)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    total_variants_persisted = 0
    for prod in norm_products:
        pid = id_by_src.get(prod.source_product_id)
        if pid:
            price_entries.append({
                "product_id": pid,
                "price": prod.price,
                "mrp": prod.mrp
            })
            progress_items.append({
                "product_id": pid,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants)
            })
            total_variants_persisted += len(prod.variants)

    price_records_count = await batch_record_prices_if_changed(
        price_entries, scrape_run_id=run_id, client=cli, batch_size=batch_size
    )

    await batch_record_product_progress(
        run_id, progress_items, status="completed", client=cli, batch_size=batch_size
    )

    persisted_count = len(progress_items)
    failed_count = len(norm_products) - persisted_count
    await update_run_counts(run_id, completed_delta=persisted_count, failed_delta=failed_count, client=cli)

    await update_run_stage(run_id, "finalizing", client=cli)
    export_path = await export_canonical_backup("myntra", client=cli)
    await complete_run(run_id, client=cli)

    print("\n" + "=" * 60)
    print(f"MYNTRA SCRAPING FINISHED: {persisted_count} products persisted")
    print(f"Total Variants Persisted: {total_variants_persisted}")
    print(f"Price Records Added: {price_records_count}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": persisted_count,
        "failed_products": failed_count,
        "total_variants": total_variants_persisted,
        "price_records_added": price_records_count,
        "export_file": str(export_path),
        "products": [p.to_dict() for p in norm_products],
    }


# =========================================================================
# Tata CLiQ Scraper (Browser JS + Supabase Persistence)
# =========================================================================

def normalize_tata_js_product(raw_p: Dict[str, Any]) -> NormalizedProduct:
    pid = str(raw_p.get("product_id") or "").strip()
    raw_vars = raw_p.get("variants") or []
    norm_vars = [
        NormalizedVariant(
            size=str(v.get("size") or ""),
            sku=v.get("sku"),
            available=bool(v.get("available")),
            stock=int(v.get("stock") or 0),
            url=v.get("url"),
        )
        for v in raw_vars
    ]

    return NormalizedProduct(
        source="tata",
        source_product_id=pid,
        title=str(raw_p.get("title") or "").strip(),
        sku=None,
        ean=None,
        price=float(raw_p.get("price") or 0.0),
        mrp=float(raw_p.get("mrp") or 0.0) if raw_p.get("mrp") else None,
        available=bool(raw_p.get("available")),
        image_url=raw_p.get("image_url"),
        url=raw_p.get("url"),
        variants=norm_vars,
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )


async def scrape_tata(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Executes the Tata CLiQ browser scraper (tata_scraper.js) via Playwright,
    then normalizes and persists all canonical products, variants, and price history to Supabase.
    """
    cli = client or get_supabase_client()
    scraper_path = SCRAPER_DIR / "tata_scraper.js"
    scraper_code = scraper_path.read_text(encoding="utf-8")

    # Timeout for full Tata scrape (default 3600s / 60 mins)
    timeout_ms = int(os.getenv("TATA_SCRAPE_TIMEOUT_SECONDS", "3600")) * 1000

    print("\n" + "=" * 60)
    print("STARTING TATA CLIQ COLUMBIA SCRAPER (BROWSER JS)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    # 1. Initialize or resume daily scrape run
    run = await get_or_create_daily_run("tata", client=cli)
    run_id = run["id"]
    print(f"[RUN] Tata Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    raw_items = []
    total_variants_from_js = 0

    async with _SCRAPER_LOCK:
        browser = await get_shared_browser()
        page = None
        try:
            print("Opening lean tab for Tata CLiQ scraper (on shared browser)...", flush=True)
            page = await _create_lean_tab(browser, "https://www.tatacliq.com/")

            tata_concurrency = int(os.getenv("TATA_CONCURRENCY", "7"))
            print(f"Injecting and starting Tata CLiQ scraper (CONCURRENCY={tata_concurrency})...", flush=True)
            limit_val = int(limit) if limit else 0
            await page.evaluate(
                """([code, limit, concurrency]) => {
                    window.__IS_PLAYWRIGHT__ = true;
                    window.__CONCURRENCY__ = concurrency;
                    window.__PRODUCT_LIMIT__ = limit > 0 ? limit : undefined;
                    window.eval(code);
                }""",
                [scraper_code, limit_val, tata_concurrency]
            )

            print("Tata scraper is running. Waiting for completion...", flush=True)
            await _wait_and_poll_progress(
                page,
                done_flag="__SCRAPER_DONE__",
                progress_flag="__SCRAPER_PROGRESS__",
                timeout_ms=timeout_ms,
                poll_interval=2.0,
                callback=progress_callback
            )

            result = await page.evaluate("() => window.scraperResult || null")
            if result and isinstance(result, dict):
                raw_items = result.get("products", [])
                total_variants_from_js = result.get("total_variants", 0)
            else:
                raw_items = await page.evaluate("() => window.output || []")

        finally:
            await close_shared_browser()
            import gc
            gc.collect()
            print("[BROWSER] Tata CLiQ browser closed. Memory reclaimed.", flush=True)

    # 2. Batch Persist into Supabase in chunks of 200
    await update_run_stage(run_id, "variants", client=cli)
    if limit:
        raw_items = raw_items[:limit]

    norm_products = [normalize_tata_js_product(item) for item in raw_items]
    batch_size = 200
    print(f"\n[PERSISTENCE] Persisting {len(norm_products)} Tata CLiQ products to Supabase (batches of {batch_size})...")

    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=batch_size)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    total_variants_persisted = 0
    for prod in norm_products:
        pid = id_by_src.get(prod.source_product_id)
        if pid:
            price_entries.append({
                "product_id": pid,
                "price": prod.price,
                "mrp": prod.mrp
            })
            progress_items.append({
                "product_id": pid,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants)
            })
            total_variants_persisted += len(prod.variants)

    # Batch record prices (500 per call)
    price_records_count = await batch_record_prices_if_changed(
        price_entries, scrape_run_id=run_id, client=cli, batch_size=batch_size
    )

    # Batch record checkpoints (500 per call)
    await batch_record_product_progress(
        run_id, progress_items, status="completed", client=cli, batch_size=batch_size
    )

    persisted_count = len(progress_items)
    failed_count = len(norm_products) - persisted_count
    await update_run_counts(run_id, completed_delta=persisted_count, failed_delta=failed_count, client=cli)

    # 3. Finalize run and export local rolling backup
    await update_run_stage(run_id, "finalizing", client=cli)
    export_path = await export_canonical_backup("tata", client=cli)
    await complete_run(run_id, client=cli)

    print("\n" + "=" * 60)
    print(f"TATA CLIQ SCRAPING FINISHED: {persisted_count} products persisted")
    print(f"Total Variants Persisted: {total_variants_persisted}")
    print(f"Price Records Added: {price_records_count}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": persisted_count,
        "failed_products": failed_count,
        "total_variants": total_variants_persisted or total_variants_from_js,
        "price_records_added": price_records_count,
        "export_file": str(export_path),
    }


# =========================================================================
# Sequential Pipeline Coordinator (Columbia -> Adventuras -> Myntra -> Tata CLiQ)
# =========================================================================

ORDERED_SCRAPERS = ["columbia", "adv", "myntra", "tata"]

SCRAPER_KEY_MAP = {
    "columbia": "columbia",
    "adv": "adv",
    "myntra": "myntra",
    "tata": "tatacliq",
}

SCRAPER_FUNCS = {
    "columbia": scrape_columbia,
    "adv": scrape_adv,
    "myntra": scrape_myntra,
    "tata": scrape_tata,
}


def normalize_scraper_names(scrapers: Optional[List[str]]) -> List[str]:
    """
    Normalizes scraper aliases and strictly enforces canonical sequential execution order:
    columbia -> adv -> myntra -> tata.
    """
    if not scrapers:
        return list(ORDERED_SCRAPERS)

    alias_map = {
        "columbia": "columbia",
        "columbiasportswear": "columbia",
        "adv": "adv",
        "adventuras": "adv",
        "myntra": "myntra",
        "tata": "tata",
        "tatacliq": "tata"
    }

    requested = set()
    for s in scrapers:
        if not s:
            continue
        norm = alias_map.get(str(s).strip().lower())
        if norm:
            requested.add(norm)

    filtered = [s for s in ORDERED_SCRAPERS if s in requested]
    return filtered or list(ORDERED_SCRAPERS)


async def run_sequential_pipeline(
    job_id: str,
    selected_scrapers: Optional[List[str]] = None,
    limit: Optional[int] = None
):
    """
    Coordinates sequential execution of scrapers (columbia -> adv -> myntra -> tata)
    with live job status updates and unified Supabase persistence.
    Supports running any subset of scrapers selectively.
    """
    from jobs import update_job, get_job

    active_scrapers = normalize_scraper_names(selected_scrapers)
    num_scrapers = len(active_scrapers)
    weight_per_scraper = 100.0 / num_scrapers if num_scrapers > 0 else 100.0

    print(f"\n[PIPELINE {job_id}] 🚀 Starting sequential pipeline with scrapers: {active_scrapers}")

    # Mark initial status
    first_scraper = active_scrapers[0]
    first_key = SCRAPER_KEY_MAP[first_scraper]
    init_scrapers_status = {SCRAPER_KEY_MAP[s]: {"status": "queued"} for s in active_scrapers}
    init_scrapers_status[first_key] = {"status": "running"}

    await update_job(
        job_id,
        status="running",
        current_scraper=first_key,
        scrapers=init_scrapers_status,
    )

    t_pipeline_start = time.perf_counter()
    cumulative_products = 0
    cumulative_variants = 0

    existing_job = await get_job(job_id)

    for idx, s_name in enumerate(active_scrapers):
        s_key = SCRAPER_KEY_MAP[s_name]
        step_base_pct = idx * weight_per_scraper

        # Check if already completed in this job (for resumption across restarts)
        already_completed = (
            existing_job
            and existing_job.get("scrapers", {}).get(s_key, {}).get("status") == "completed"
        )
        if already_completed:
            prev_p = existing_job.get("scrapers", {}).get(s_key, {}).get("product_count", 0)
            prev_v = existing_job.get("scrapers", {}).get(s_key, {}).get("variant_count", 0)
            cumulative_products += prev_p
            cumulative_variants += prev_v
            print(f"[JOB {job_id}] ⏩ {s_name.upper()} already completed ({prev_p} products). Resuming next...", flush=True)
            continue

        await update_job(
            job_id,
            current_scraper=s_key,
            scrapers={s_key: {"status": "running"}},
        )

        async def scraper_progress_cb(prog: dict):
            curr = prog.get("current", 0)
            tot = prog.get("total", 1)
            stage = prog.get("stage", "Running")
            local_pct = (curr / tot) if tot > 0 else 0.0
            overall_pct = step_base_pct + (local_pct * weight_per_scraper)
            metrics = {
                "stage": stage,
                "current": curr,
                "total": tot,
            }
            var_count = prog.get("variant_count", 0)
            kwargs = {
                "progress_percentage": min(99.0, round(overall_pct, 1)),
            }
            if var_count > 0:
                metrics["variant_count"] = var_count
                kwargs["variant_count"] = cumulative_variants + var_count

            kwargs["scrapers"] = {s_key: metrics}
            await update_job(job_id, **kwargs)

        try:
            t0 = time.perf_counter()
            runner_fn = SCRAPER_FUNCS[s_name]
            res = await runner_fn(limit=limit, progress_callback=scraper_progress_cb)
            dur = round(time.perf_counter() - t0, 1)

            prods = res.get("completed_products", len(res.get("products", [])))
            vars_cnt = res.get("total_variants", 0)
            cumulative_products += prods
            cumulative_variants += vars_cnt

            completed_pct = round((idx + 1) * weight_per_scraper, 1)
            await update_job(
                job_id,
                product_count=cumulative_products,
                variant_count=cumulative_variants,
                progress_percentage=min(100.0, completed_pct),
                scrapers={
                    s_key: {
                        "status": "completed",
                        "product_count": prods,
                        "variant_count": vars_cnt,
                        "duration_seconds": dur,
                        "error": None
                    }
                }
            )
            print(f"[JOB {job_id}] ✅ {s_name.upper()} COMPLETED ({prods} products, {vars_cnt} variants, {dur}s)", flush=True)

        except Exception as e:
            dur = round(time.perf_counter() - t_pipeline_start, 1)
            err_msg = f"{s_name.upper()} scraper failed: {e}"
            print(f"[JOB {job_id}] ❌ {err_msg}", flush=True)

            scrapers_update = {
                s_key: {
                    "status": "failed",
                    "duration_seconds": dur,
                    "error": str(e)
                }
            }
            # Mark any remaining scrapers as skipped
            for rem_name in active_scrapers[idx + 1:]:
                rem_key = SCRAPER_KEY_MAP[rem_name]
                scrapers_update[rem_key] = {
                    "status": "skipped",
                    "error": f"Skipped due to {s_name} failure (fail-fast)"
                }

            await update_job(
                job_id,
                status="failed",
                current_scraper=s_key,
                error=err_msg,
                scrapers=scrapers_update
            )
            return

    # All requested scrapers succeeded
    await update_job(
        job_id,
        status="completed",
        current_scraper=None,
        progress_percentage=100.0,
        product_count=cumulative_products,
        variant_count=cumulative_variants,
        error=None,
    )
    print(f"\n[JOB {job_id}] 🎉 ALL REQUESTED SCRAPERS ({', '.join(active_scrapers)}) COMPLETED SUCCESSFULLY!", flush=True)


main = scrape_columbia


async def _run_cli():
    parser = argparse.ArgumentParser(description="Unified Columbia Scrapers Pipeline")
    parser.add_argument("target", nargs="?", default=None, help="Target scraper: 'columbia', 'adv', 'myntra', 'tata', or 'pipeline'")
    parser.add_argument("--scraper", type=str, default=None, help="Scraper name: 'columbia', 'adv', 'myntra', 'tata', or 'pipeline'")
    parser.add_argument("--scrapers", type=str, default=None, help="Comma-separated scrapers e.g. 'columbia,adv' or 'all'")
    parser.add_argument("--limit", type=int, default=None, help="Product limit for test mode")
    args = parser.parse_args()

    scrapers_arg = args.scrapers
    target_arg = args.scraper or args.target

    try:
        if scrapers_arg:
            if scrapers_arg.strip().lower() in ("all", "pipeline"):
                selected = list(ORDERED_SCRAPERS)
            else:
                selected = [s.strip() for s in scrapers_arg.split(",") if s.strip()]
            from jobs import create_job
            job = await create_job(scrapers=selected)
            await run_sequential_pipeline(job["job_id"], selected_scrapers=selected, limit=args.limit)
        elif target_arg:
            target = target_arg.lower()
            if target in ("pipeline", "all"):
                from jobs import create_job
                job = await create_job()
                await run_sequential_pipeline(job["job_id"], limit=args.limit)
            elif target in ("tata", "tatacliq"):
                await scrape_tata(limit=args.limit)
            elif target in ("adv", "adventuras"):
                await scrape_adv(limit=args.limit)
            elif target in ("myntra",):
                await scrape_myntra(limit=args.limit)
            else:
                await scrape_columbia(limit=args.limit)
        else:
            await scrape_columbia(limit=args.limit)
    finally:
        await close_shared_browser()


if __name__ == "__main__":
    asyncio.run(_run_cli())
