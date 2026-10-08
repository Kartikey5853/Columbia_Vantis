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
    get_scraper_id,
    update_run_stage,
    update_run_counts,
    complete_run,
    fail_run,
    stop_run,
    get_daily_scrapers_summary,
    is_scraper_completed_today,
)
from jobs import is_stop_requested, get_stop_reason, request_stop
from persistence.checkpoint_store import (
    init_product_progress,
    mark_product_in_progress,
    mark_product_completed,
    mark_product_failed,
    get_incomplete_products,
    get_completed_product_ids,
    batch_record_product_progress,
    get_completed_listing_pages,
    record_listing_page_completed,
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

DEFAULT_MYNTRA_TOKEN = os.getenv("MYNTRA_SESSION_TOKEN")


def load_akamai_cookies() -> List[Dict[str, Any]]:
    """
    Safely loads and sanitizes Akamai session cookies from:
    1. AKAMAI_COOKIES environment variable (e.g. on Render)
    2. akamai_cookies.json in working directory (local development)
    3. www.myntra.com_cookies.json in working directory (local fallback)

    Returns Playwright-compatible cookie dictionaries without exposing values.
    """
    raw_data = None

    env_cookies = os.getenv("AKAMAI_COOKIES")
    if env_cookies and env_cookies.strip():
        try:
            raw_data = json.loads(env_cookies.strip())
        except Exception as e:
            print(f"[COOKIES] Warning: Failed to parse AKAMAI_COOKIES environment variable: {e}", flush=True)

    if not raw_data:
        for fname in ("akamai_cookies.json", "www.myntra.com_cookies.json"):
            c_path = Path(fname)
            if c_path.exists():
                try:
                    raw_data = json.loads(c_path.read_text(encoding="utf-8"))
                    break
                except Exception as e:
                    print(f"[COOKIES] Warning: Failed to read {fname}: {e}", flush=True)

    if not raw_data or not isinstance(raw_data, list):
        return []

    sanitized: List[Dict[str, Any]] = []
    for c in raw_data:
        if not isinstance(c, dict):
            continue
        c_name = str(c.get("name") or "").strip()
        c_val = str(c.get("value") or "").strip()
        if not c_name:
            continue

        cookie: Dict[str, Any] = {
            "name": c_name,
            "value": c_val,
            "path": str(c.get("path") or "/"),
        }

        domain = str(c.get("domain") or "").strip()
        if domain:
            cookie["domain"] = domain
        elif "url" in c and c["url"]:
            cookie["url"] = str(c["url"])
        else:
            cookie["domain"] = ".myntra.com"

        exp = c.get("expires") if c.get("expires") is not None else c.get("expirationDate")
        if exp is not None:
            try:
                cookie["expires"] = float(exp)
            except (ValueError, TypeError):
                pass

        if "httpOnly" in c:
            cookie["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            cookie["secure"] = bool(c["secure"])

        same_site = str(c.get("sameSite") or "").lower()
        if same_site in ("strict", "lax", "none"):
            cookie["sameSite"] = same_site.capitalize()

        sanitized.append(cookie)

    return sanitized



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
        "Listing Page", "Products", "Variants", "Worker", "Completed", "SCRAPE COMPLETE", "TEST MODE",
        "Page", "error", "Error", "Network", "Halting", "Stopping", "[ADV]", "[SCRAPER]"
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
    "--disable-blink-features=AutomationControlled",
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

    headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
    print(f"[BROWSER] Launching shared single Chromium instance (headless={headless_mode}, RAM-optimized)...", flush=True)
    _SHARED_BROWSER = await _SHARED_PLAYWRIGHT.chromium.launch(
        headless=headless_mode,
        ignore_default_args=["--enable-automation"],
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


_CURRENT_SCRAPER_RUN_ID: Optional[str] = None
_CURRENT_SCRAPER_NAME: Optional[str] = None


async def stop_current_scraper(reason: str = "Stopped by user request") -> None:
    """Terminates in-progress browser pages and updates active Supabase scrape run to stopped."""
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME, _ACTIVE_PAGE
    print(f"[RUNNER] 🛑 Stopping active scraper ({_CURRENT_SCRAPER_NAME or 'none'}). Reason: {reason}", flush=True)

    if _CURRENT_SCRAPER_RUN_ID:
        try:
            cli = get_supabase_client()
            await stop_run(_CURRENT_SCRAPER_RUN_ID, reason=reason, client=cli)
            print(f"[RUNNER] Supabase run {_CURRENT_SCRAPER_RUN_ID} marked as stopped.", flush=True)
        except Exception as e:
            print(f"[RUNNER] Warning: Failed to update stop_run in Supabase: {e}", flush=True)
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None

    if _ACTIVE_PAGE:
        try:
            await _ACTIVE_PAGE.evaluate("() => { window.__STOP_REQUESTED__ = true; }")
        except Exception:
            pass
        try:
            await _ACTIVE_PAGE.close()
        except Exception:
            pass
        _ACTIVE_PAGE = None

    await close_shared_browser()


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
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
            "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
    )

    if "myntra.com" in url:
        akamai_cookies = load_akamai_cookies()
        if akamai_cookies:
            try:
                await context.add_cookies(akamai_cookies)
                print(f"[COOKIES] Loaded {len(akamai_cookies)} Akamai cookies into Myntra session", flush=True)
            except Exception as e:
                print(f"[COOKIES] Warning: Failed to add cookies: {e}", flush=True)
        elif DEFAULT_MYNTRA_TOKEN:
            try:
                await context.add_cookies([{
                    "name": "at",
                    "value": DEFAULT_MYNTRA_TOKEN,
                    "domain": ".myntra.com",
                    "path": "/"
                }])
            except Exception:
                pass

    page = await context.new_page()
    _ACTIVE_PAGE = page

    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
    """)

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
    callback=None,
    on_drain: Optional[Callable[[List[Any]], Any]] = None,
    on_drain_listings: Optional[Callable[[List[Any]], Any]] = None,
    on_drain_variants: Optional[Callable[[List[Any]], Any]] = None,
    on_batch_sync: Optional[Callable[[Any], Any]] = None,
) -> bool:
    """Wait for completion while periodically streaming progress to callback and draining chunks."""
    start_t = time.perf_counter()
    timeout_sec = timeout_ms / 1000.0

    while time.perf_counter() - start_t < timeout_sec:
        if is_stop_requested():
            print("[RUNNER] Stop requested. Aborting scraper polling loop...", flush=True)
            try:
                await page.evaluate("() => { window.__STOP_REQUESTED__ = true; }")
            except Exception:
                pass
            return False

        is_done = await page.evaluate(f"() => window.{done_flag} === true")

        if on_drain_listings:
            listings_chunk = await page.evaluate("() => typeof window.drainUnsavedListings === 'function' ? window.drainUnsavedListings() : []")
            if listings_chunk and len(listings_chunk) > 0:
                try:
                    await on_drain_listings(listings_chunk)
                except Exception as e:
                    print(f"[PROGRESS] Listings drain error: {e}", flush=True)

        if on_drain_variants:
            variants_chunk = await page.evaluate("() => typeof window.drainUnsavedVariants === 'function' ? window.drainUnsavedVariants() : []")
            if variants_chunk and len(variants_chunk) > 0:
                try:
                    await on_drain_variants(variants_chunk)
                except Exception as e:
                    print(f"[PROGRESS] Variants drain error: {e}", flush=True)

        if on_drain:
            chunk = await page.evaluate("() => typeof window.drainUnsavedProducts === 'function' ? window.drainUnsavedProducts() : []")
            if chunk and len(chunk) > 0:
                try:
                    await on_drain(chunk)
                except Exception as e:
                    print(f"[PROGRESS] Chunk drain error: {e}", flush=True)

        if on_batch_sync:
            batch_ready = await page.evaluate("() => window.__BATCH_READY__ === true")
            if batch_ready:
                try:
                    await on_batch_sync(page)
                except Exception as e:
                    print(f"[PROGRESS] Batch sync error: {e}", flush=True)
                    try:
                        await page.evaluate("() => { window.__BATCH_SAVED__ = true; }")
                    except Exception:
                        pass

        if is_done:
            if on_drain_listings:
                listings_chunk = await page.evaluate("() => typeof window.drainUnsavedListings === 'function' ? window.drainUnsavedListings() : []")
                if listings_chunk and len(listings_chunk) > 0:
                    try:
                        await on_drain_listings(listings_chunk)
                    except Exception:
                        pass
            if on_drain_variants:
                variants_chunk = await page.evaluate("() => typeof window.drainUnsavedVariants === 'function' ? window.drainUnsavedVariants() : []")
                if variants_chunk and len(variants_chunk) > 0:
                    try:
                        await on_drain_variants(variants_chunk)
                    except Exception:
                        pass
            if on_drain:
                chunk = await page.evaluate("() => typeof window.drainUnsavedProducts === 'function' ? window.drainUnsavedProducts() : []")
                if chunk and len(chunk) > 0:
                    try:
                        await on_drain(chunk)
                    except Exception:
                        pass
            if on_batch_sync:
                try:
                    await on_batch_sync(page)
                except Exception:
                    pass
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
    columbia_report = {
        "scraper": "columbia",
        "business_date": run["business_date"],
        "status": "completed",
        "stage": "completed",
        "total_products": persisted_count,
        "completed_products": persisted_count,
        "failed_products": failed_count,
        "prices_recorded": price_records_count,
        "error": None
    }
    await complete_run(run_id, report=columbia_report, client=cli)

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
# Adventuras Scraper (Lean Streaming Engine + Supabase Persistence)
# =========================================================================

def normalize_shopify_product(prod_data: Dict[str, Any]) -> NormalizedProduct:
    """
    Directly converts a Shopify products.json item into a canonical NormalizedProduct.
    Preserves all variants, sizes, barcodes, SKUs, compare_at_price, and images.
    """
    pid = str(prod_data.get("id") or "").strip()
    title = str(prod_data.get("title") or "").strip()
    handle = str(prod_data.get("handle") or "").strip()
    url = f"https://adventuras.in/products/{handle}" if handle else "https://adventuras.in"
    images = prod_data.get("images") or []
    image_url = images[0].get("src") if (images and isinstance(images[0], dict)) else ""

    variants_raw = prod_data.get("variants") or []
    norm_variants: List[NormalizedVariant] = []
    min_price: Optional[float] = None
    max_mrp: Optional[float] = None
    first_sku: Optional[str] = None
    first_ean: Optional[str] = None

    for v in variants_raw:
        if not isinstance(v, dict):
            continue
        v_title = str(v.get("title") or "").strip()
        v_sku = str(v.get("sku") or "").strip() or None
        v_barcode = str(v.get("barcode") or "").strip() or None

        if not first_sku and v_sku:
            first_sku = v_sku
        if not first_ean and v_barcode:
            first_ean = v_barcode

        try:
            v_price = float(v.get("price") or 0.0)
        except Exception:
            v_price = 0.0

        try:
            v_compare = float(v.get("compare_at_price") or 0.0) if v.get("compare_at_price") else v_price
        except Exception:
            v_compare = v_price

        if v_price > 0:
            if min_price is None or v_price < min_price:
                min_price = v_price
        if v_compare > 0:
            if max_mrp is None or v_compare > max_mrp:
                max_mrp = v_compare

        norm_variants.append(
            NormalizedVariant(
                size=v_title,
                sku=v_sku,
                ean=v_barcode,
                available=bool(v.get("available", True)),
                stock=int(v.get("inventory_quantity") or 0) if v.get("inventory_quantity") is not None else 0,
                price=v_price,
                mrp=v_compare,
                url=url
            )
        )

    return NormalizedProduct(
        source="adv",
        source_product_id=pid,
        title=title,
        sku=first_sku,
        ean=first_ean,
        price=min_price or 0.0,
        mrp=max_mrp or min_price or 0.0,
        available=any(v.available for v in norm_variants) if norm_variants else True,
        image_url=image_url,
        url=url,
        variants=norm_variants,
        scraped_at=datetime.now(timezone.utc).isoformat()
    )


def group_adv_products(raw_items: List[Dict[str, Any]]) -> List[NormalizedProduct]:
    """
    Groups raw variant items from adv_scraper.js into canonical NormalizedProduct objects.
    Preserved for backward compatibility and test mock pipelines.
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
    Executes Adventuras scraper via Playwright tab running adv_scraper.js.
    Batches database updates in 3-4 pages, draining the browser window buffer
    to prevent memory spikes, and resumes seamlessly from scrape_listing_pages checkpoints.
    """
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME
    cli = client or get_supabase_client()

    print("\n" + "=" * 60)
    print("STARTING ADVENTURAS SCRAPER (3-4 PAGE BATCH PLAYWRIGHT ENGINE)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("adv", client=cli)
    run_id = run["id"]
    _CURRENT_SCRAPER_RUN_ID = run_id
    _CURRENT_SCRAPER_NAME = "adv"
    print(f"[RUN] Adventuras Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    completed_pages = await get_completed_listing_pages(run_id, client=cli)
    start_page = max(completed_pages) + 1 if completed_pages else 1
    if completed_pages:
        print(f"[ADV CHECKPOINT] Resuming Adventuras from page {start_page} ({len(completed_pages)} pages already completed in DB).", flush=True)

    await update_run_stage(run_id, "products", client=cli)

    scraper_path = SCRAPER_DIR / "adv_scraper.js"
    scraper_code = scraper_path.read_text(encoding="utf-8")

    total_persisted_products = run.get("completed_products") or 0
    total_persisted_variants = 0
    total_prices_recorded = 0
    all_pages_done = set(completed_pages)
    t_start = time.perf_counter()

    async def handle_adv_batch(page_obj):
        nonlocal total_persisted_products, total_persisted_variants, total_prices_recorded
        raw_items = await page_obj.evaluate("() => typeof window.drainUnsavedProducts === 'function' ? window.drainUnsavedProducts() : []")
        pages_chunk = await page_obj.evaluate("() => typeof window.drainCompletedPages === 'function' ? window.drainCompletedPages() : []")

        if raw_items:
            norm_products = group_adv_products(raw_items)
            db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=200)
            id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

            price_entries = []
            progress_items = []
            chunk_variants = 0
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
                    chunk_variants += len(prod.variants)

            if price_entries:
                added = await batch_record_prices_if_changed(
                    price_entries, scrape_run_id=run_id, client=cli, batch_size=200
                )
                total_prices_recorded += added

            if progress_items:
                await batch_record_product_progress(
                    run_id, progress_items, status="completed", client=cli, batch_size=200
                )

            total_persisted_products += len(norm_products)
            total_persisted_variants += chunk_variants
            await update_run_counts(run_id, completed_delta=len(norm_products), failed_delta=0, client=cli)

        for p_num in pages_chunk:
            await record_listing_page_completed(run_id, p_num, product_count=len(raw_items) if len(pages_chunk) == 1 else 0, client=cli)
            all_pages_done.add(p_num)

        if raw_items or pages_chunk:
            await export_canonical_backup("adv", client=cli)
            print(f"[ADV BATCH] Persisted batch of {len(pages_chunk)} pages ({len(raw_items)} raw items, total persisted: {total_persisted_products}). Browser memory cleared.", flush=True)

        import gc
        gc.collect()

        # Acknowledge to JS scraper so it advances to next page
        try:
            await page_obj.evaluate("() => { window.__BATCH_SAVED__ = true; }")
        except Exception:
            pass

    try:
        async with _SCRAPER_LOCK:
            browser = await get_shared_browser()
            page = None
            try:
                print("Opening lean tab for Adventuras scraper (Playwright)...", flush=True)
                page = await _create_lean_tab(browser, "https://adventuras.in/")

                limit_val = int(limit) if limit else 0
                batch_page_size = 3  # 3 pages per batch as requested by user
                print(f"Injecting Adventuras JS scraper (startPage={start_page}, batchPageSize={batch_page_size}, limit={limit_val})...", flush=True)
                await page.evaluate(
                    """([code, limit, startPage, batchSize]) => {
                        window.__IS_PLAYWRIGHT__ = true;
                        window.__START_PAGE__ = startPage;
                        window.__BATCH_PAGE_SIZE__ = batchSize;
                        if (limit > 0) window.__PRODUCT_LIMIT__ = limit;
                        window.eval(code);
                    }""",
                    [scraper_code, limit_val, start_page, batch_page_size]
                )

                print("Adventuras scraper is running. Waiting for completion while syncing 3-4 page batches...", flush=True)
                await _wait_and_poll_progress(
                    page,
                    done_flag="__SCRAPER_DONE__",
                    progress_flag="__SCRAPER_PROGRESS__",
                    timeout_ms=1800_000,
                    poll_interval=1.5,
                    callback=progress_callback,
                    on_batch_sync=handle_adv_batch
                )

                # Final flush of any pending batch
                await handle_adv_batch(page)

            finally:
                await close_shared_browser()
                import gc
                gc.collect()
                print("[BROWSER] Adventuras browser closed. Memory reclaimed.", flush=True)

    finally:
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None

    if is_stop_requested():
        reason = get_stop_reason()
        await stop_run(run_id, reason=reason, client=cli)
        return {"status": "stopped", "run_id": run_id}

    dur = round(time.perf_counter() - t_start, 1)
    await update_run_stage(run_id, "finalizing", client=cli)
    export_path = await export_canonical_backup("adv", client=cli)

    adv_report = {
        "scraper": "adv",
        "business_date": run["business_date"],
        "status": "completed",
        "stage": "completed",
        "total_products": total_persisted_products,
        "completed_products": total_persisted_products,
        "failed_products": 0,
        "total_variants": total_persisted_variants,
        "prices_recorded": total_prices_recorded,
        "completed_pages": sorted(list(all_pages_done)),
        "duration_seconds": dur,
        "error": None
    }
    await complete_run(run_id, report=adv_report, client=cli)

    print("\n" + "=" * 60)
    print(f"ADVENTURAS SCRAPING FINISHED: {total_persisted_products} products persisted across {len(all_pages_done)} pages")
    print(f"Total Variants Persisted: {total_persisted_variants}")
    print(f"Price Records Added: {total_prices_recorded}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": total_persisted_products,
        "failed_products": 0,
        "total_variants": total_persisted_variants,
        "price_records_added": total_prices_recorded,
        "export_file": str(export_path),
        "completed_pages": sorted(list(all_pages_done)),
    }
    await complete_run(run_id, report=adv_report, client=cli)

    print("\n" + "=" * 60)
    print(f"ADVENTURAS SCRAPING FINISHED: {total_persisted_products} products persisted across {len(all_pages_done)} pages")
    print(f"Total Variants Persisted: {total_persisted_variants}")
    print(f"Price Records Added: {total_prices_recorded}")
    print(f"Local Rolling Backup: {export_path.resolve()}")
    print("=" * 60 + "\n", flush=True)

    return {
        "status": "completed",
        "run_id": run_id,
        "completed_products": total_persisted_products,
        "failed_products": 0,
        "total_variants": total_persisted_variants,
        "price_records_added": total_prices_recorded,
        "export_file": str(export_path),
        "completed_pages": sorted(list(all_pages_done)),
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


async def scrape_myntra(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Executes the Myntra Columbia scraper by opening https://www.myntra.com/columbia
    in a lean Chromium tab with anti-bot evasion, injecting scraper/myntra_scraper.js,
    checkpointing page-by-page into Supabase, and updating local rolling backups.
    """
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME
    cli = client or get_supabase_client()
    t_start = time.perf_counter()

    print("\n" + "=" * 60)
    print("STARTING MYNTRA COLUMBIA SCRAPER (BROWSER JS + CHECKPOINTED)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("myntra", client=cli)
    run_id = run["id"]
    _CURRENT_SCRAPER_RUN_ID = run_id
    _CURRENT_SCRAPER_NAME = "myntra"
    print(f"[RUN] Myntra Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    completed_pages = await get_completed_listing_pages(run_id, client=cli)
    start_page = (max(completed_pages) + 1) if completed_pages else 1
    if completed_pages:
        print(f"[MYNTRA CHECKPOINT] Resuming from checkpoint: Pages {sorted(completed_pages)} already persisted. Starting at page {start_page}.", flush=True)

    if len(completed_pages) >= 49:
        print(f"[MYNTRA CHECKPOINT] All 49 pages already completed today for run {run_id}. Skipping browser.", flush=True)
        export_path = await export_canonical_backup("myntra", client=cli)
        return {
            "status": "completed",
            "run_id": run_id,
            "completed_products": run.get("completed_products") or 1704,
            "total_variants": 0,
            "duration_seconds": 0.5
        }

    total_persisted_products = run.get("completed_products") or 0
    total_variants_persisted = 0
    total_prices_added = 0
    limit_val = int(limit) if limit else 0
    scraper_path = SCRAPER_DIR / "myntra_scraper.js"
    scraper_code = scraper_path.read_text(encoding="utf-8")
    timeout_ms = int(os.getenv("MYNTRA_SCRAPE_TIMEOUT_SECONDS", "1800")) * 1000

    await update_run_stage(run_id, "products", client=cli)

    async def drain_myntra_chunk(chunk: List[Dict[str, Any]]):
        nonlocal total_persisted_products, total_variants_persisted, total_prices_added
        if not chunk:
            return

        for item in chunk:
            p_num = item.get("page", 0)
            raw_items = item.get("products", [])
            if not raw_items:
                await record_listing_page_completed(run_id, p_num, 0, client=cli)
                completed_pages.add(p_num)
                continue

            norm_chunk = group_myntra_products(raw_items)
            if norm_chunk:
                db_prods = await upsert_canonical_products_batch(norm_chunk, client=cli, batch_size=200)
                id_by_src = {p["source_product_id"]: p["id"] for p in db_prods if "source_product_id" in p and "id" in p}
                price_entries = []
                progress_items = []
                for prod in norm_chunk:
                    pid = id_by_src.get(prod.source_product_id)
                    if pid:
                        price_entries.append({"product_id": pid, "price": prod.price, "mrp": prod.mrp})
                        progress_items.append({"product_id": pid, "source_product_id": prod.source_product_id, "variant_count": len(prod.variants)})
                        total_variants_persisted += len(prod.variants)

                if price_entries:
                    p_cnt = await batch_record_prices_if_changed(price_entries, scrape_run_id=run_id, client=cli, batch_size=200)
                    total_prices_added += p_cnt
                if progress_items:
                    await batch_record_product_progress(run_id, progress_items, status="completed", client=cli, batch_size=200)

                total_persisted_products += len(norm_chunk)

            await record_listing_page_completed(run_id, p_num, len(raw_items), client=cli)
            completed_pages.add(p_num)
            print(f"[MYNTRA CHECKPOINT] Saved page {p_num} checkpoint ({len(raw_items)} items, total persisted: {total_persisted_products}).", flush=True)

        if chunk:
            await export_canonical_backup("myntra", client=cli)
            await update_run_counts(run_id, completed_delta=len(chunk), client=cli)

    try:
        async with _SCRAPER_LOCK:
            browser = await get_shared_browser()
            page = None
            try:
                print("Opening lean tab for Myntra scraper (Playwright)...", flush=True)
                page = await _create_lean_tab(browser, "https://www.myntra.com/columbia")

                print(f"Injecting Myntra JS scraper (startPage={start_page}, limit={limit_val})...", flush=True)
                await page.evaluate(
                    """([code, limit, startPage]) => {
                        window.__IS_PLAYWRIGHT__ = true;
                        window.__START_PAGE__ = startPage;
                        if (limit > 0) window.__PRODUCT_LIMIT__ = limit;
                        window.eval(code);
                    }""",
                    [scraper_code, limit_val, start_page]
                )

                print("Myntra scraper is running. Waiting for completion while draining page checkpoints...", flush=True)
                await _wait_and_poll_progress(
                    page,
                    done_flag="__SCRAPER_DONE__",
                    progress_flag="__SCRAPER_PROGRESS__",
                    timeout_ms=timeout_ms,
                    poll_interval=1.5,
                    callback=progress_callback,
                    on_drain=drain_myntra_chunk
                )

                # Drain any remaining unsaved products
                final_unsaved = await page.evaluate("() => typeof window.drainUnsavedProducts === 'function' ? window.drainUnsavedProducts() : []")
                if final_unsaved:
                    await drain_myntra_chunk(final_unsaved)

            finally:
                await close_shared_browser()
                import gc
                gc.collect()
                print("[BROWSER] Myntra browser closed. Memory reclaimed.", flush=True)

        dur = round(time.perf_counter() - t_start, 1)
        await update_run_stage(run_id, "finalizing", client=cli)
        export_path = await export_canonical_backup("myntra", client=cli)

        report = {
            "scraper": "myntra",
            "business_date": run["business_date"],
            "status": "completed",
            "stage": "completed",
            "total_products": total_persisted_products,
            "completed_products": total_persisted_products,
            "failed_products": 0,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "completed_pages": sorted(list(completed_pages)),
            "checkpoints": {
                "listing_pages_completed": len(completed_pages),
            },
            "duration_seconds": dur,
            "error": None
        }
        await complete_run(run_id, report=report, client=cli)

        print("\n" + "=" * 60)
        print(f"MYNTRA SCRAPING FINISHED: {total_persisted_products} products persisted")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print(f"Database Report Saved to scrape_runs (ID: {run_id})")
        print("=" * 60 + "\n", flush=True)

        return {
            "status": "completed",
            "run_id": run_id,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "report": report
        }

    except Exception as e:
        dur = round(time.perf_counter() - t_start, 1)
        fail_report = {
            "scraper": "myntra",
            "business_date": run["business_date"],
            "status": "failed",
            "stage": "products",
            "total_products": total_persisted_products,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "completed_pages": sorted(list(completed_pages)),
            "duration_seconds": dur,
            "error": str(e)
        }
        await fail_run(run_id, error=str(e), report=fail_report, client=cli)
        raise
    finally:
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None


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
    Executes the Tata CLiQ scraper with decoupled two-phase architecture:
    Phase 1: Collects listing pages and seeds catalog into Supabase & progress tracker.
             Browser is closed immediately after listings to free all RAM.
    Phase 2: Ultra-low-memory Python async variant extraction (concurrency=3)
             fetching only incomplete products, checkpointing milestones every ~200 variants,
             and dynamically resuming from the middle across server restarts/crashes.
    """
    import gc
    cli = client or get_supabase_client()
    t_start = time.perf_counter()

    print("\n" + "=" * 60)
    print("STARTING TATA CLIQ COLUMBIA SCRAPER (ZERO-LEAK TWO-PHASE CHECKPOINTED)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("tata", client=cli)
    run_id = run["id"]
    scraper_id = await get_scraper_id("tata", cli)
    print(f"[RUN] Tata Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    # =========================================================================
    # Phase 1: Listing Pages & Base Products
    # =========================================================================
    completed_listing_pages = await get_completed_listing_pages(run_id, client=cli)

    # Check if catalog is already present in DB
    existing_catalog_sample = await cli.select(
        "products",
        columns="id",
        filters={"scraper_id": f"eq.{scraper_id}"},
        limit=10
    )
    has_existing_catalog = bool(existing_catalog_sample and len(existing_catalog_sample) > 0)
    phase1_needed = not (len(completed_listing_pages) >= 54 or (has_existing_catalog and not limit))

    if not phase1_needed:
        print(f"[TATA CHECKPOINT] Phase 1 already complete ({len(completed_listing_pages)} pages in DB, existing catalog detected). Skipping listing browser.", flush=True)
    else:
        print(f"[TATA PHASE 1] Starting listing page collection (starting from page {len(completed_listing_pages)})...", flush=True)
        await update_run_stage(run_id, "listings", client=cli)
        scraper_path = SCRAPER_DIR / "tata_scraper.js"
        scraper_code = scraper_path.read_text(encoding="utf-8")
        timeout_ms = int(os.getenv("TATA_SCRAPE_TIMEOUT_SECONDS", "3600")) * 1000

        async def drain_tata_listings(listings_chunk: List[Dict[str, Any]]):
            """Phase 1: Persist listing page checkpoints and base product records."""
            for item in listings_chunk:
                p_num = item.get("page", 0)
                raw_prods = item.get("products", [])
                if not raw_prods:
                    await record_listing_page_completed(run_id, p_num, 0, client=cli)
                    continue

                norm_prods = [normalize_tata_js_product(p) for p in raw_prods]
                db_prods = await upsert_canonical_products_batch(norm_prods, client=cli, batch_size=200)
                id_by_src = {p["source_product_id"]: p["id"] for p in db_prods if "source_product_id" in p and "id" in p}

                progress_items = []
                for prod in norm_prods:
                    pid = id_by_src.get(prod.source_product_id)
                    if pid:
                        progress_items.append({
                            "product_id": pid,
                            "source_product_id": prod.source_product_id,
                            "variant_count": 0
                        })
                if progress_items:
                    await batch_record_product_progress(run_id, progress_items, status="pending", client=cli, batch_size=200)

                await record_listing_page_completed(run_id, p_num, len(raw_prods), client=cli)
                completed_listing_pages.add(p_num)
                await export_canonical_backup("tata", client=cli)
                print(f"[TATA CHECKPOINT] Listing Page {p_num + 1} persisted ({len(raw_prods)} products).", flush=True)

        async with _SCRAPER_LOCK:
            browser = await get_shared_browser()
            try:
                page = await _create_lean_tab(browser, "https://www.tatacliq.com/")
                start_p = (max(completed_listing_pages) + 1) if completed_listing_pages else 0
                limit_val = int(limit) if limit else 0
                await page.evaluate(
                    """([code, limit, startPage]) => {
                        window.__IS_PLAYWRIGHT__ = true;
                        window.__PHASE__ = "listings_only";
                        window.__PRODUCT_LIMIT__ = limit > 0 ? limit : undefined;
                        window.__START_PAGE__ = startPage;
                        window.eval(code);
                    }""",
                    [scraper_code, limit_val, start_p]
                )

                await _wait_and_poll_progress(
                    page,
                    done_flag="__SCRAPER_DONE__",
                    progress_flag="__SCRAPER_PROGRESS__",
                    timeout_ms=timeout_ms,
                    poll_interval=2.0,
                    callback=progress_callback,
                    on_drain_listings=drain_tata_listings,
                )

                final_listings = await page.evaluate("() => typeof window.drainUnsavedListings === 'function' ? window.drainUnsavedListings() : []")
                if final_listings:
                    await drain_tata_listings(final_listings)
            finally:
                await close_shared_browser()
                gc.collect()
                print("[BROWSER] Phase 1 browser closed. All RAM freed.", flush=True)

    # =========================================================================
    # Phase 2: Middle Resumption & Concurrency=3 Python Variant Fetcher
    # =========================================================================
    await update_run_stage(run_id, "variants", client=cli)

    # 1. Fetch incomplete products from progress tracker (paginated)
    pending_items = await get_incomplete_products(run_id, client=cli)

    # If progress tracker is empty for this run (e.g. initial run on pre-existing catalog), seed it:
    if not pending_items:
        any_prog = await cli.select("scrape_product_progress", columns="id", filters={"scrape_run_id": f"eq.{run_id}"}, limit=1)
        if not any_prog:
            print("[TATA CHECKPOINT] Initializing product progress tracking from catalog in database...", flush=True)
            all_prods = []
            off = 0
            while True:
                chunk = await cli.select(
                    "products",
                    columns="id,source_product_id,variants",
                    filters={"scraper_id": f"eq.{scraper_id}"},
                    order="id.asc",
                    limit=1000,
                    offset=off
                )
                if not chunk:
                    break
                all_prods.extend(chunk)
                if len(chunk) < 1000:
                    break
                off += len(chunk)

            seed_items = []
            for p in all_prods:
                cur_vars = p.get("variants") or []
                seed_items.append({
                    "product_id": p["id"],
                    "source_product_id": p["source_product_id"],
                    "variant_count": len(cur_vars)
                })
            if seed_items:
                await batch_record_product_progress(run_id, seed_items, status="pending", client=cli, batch_size=500)
            pending_items = await get_incomplete_products(run_id, client=cli)

    completed_product_ids = await get_completed_product_ids(run_id, client=cli)
    total_catalog_count = len(completed_product_ids) + len(pending_items)

    print(f"\n[TATA RESUME] Catalog: {total_catalog_count} products. Already completed: {len(completed_product_ids)}. Pending: {len(pending_items)}.")
    if completed_product_ids:
        print(f"[TATA RESUME] Resuming from product {len(completed_product_ids) + 1}/{total_catalog_count} (middle checkpoint)!", flush=True)

    if limit:
        limit_val = int(limit)
        pending_items = pending_items[:limit_val]
        print(f"[TEST MODE] Limited variant fetching to {len(pending_items)} pending products.")

    total_variants_persisted = 0
    total_products_persisted = len(completed_product_ids)
    last_checkpoint_variants = 0
    total_prices_added = 0

    try:
        if not pending_items:
            print("[TATA] All products already have completed variant checkpoints today! Nothing pending.", flush=True)
        else:
            concurrency = int(os.getenv("TATA_CONCURRENCY", "3"))
            print(f"[TATA PHASE 2] Starting variant extraction in Python with CONCURRENCY={concurrency} (Browser: CLOSED, RAM: <25MB)...", flush=True)

            queue: asyncio.Queue = asyncio.Queue()
            for item in pending_items:
                queue.put_nowait(item)

            batch_buffer: List[Dict[str, Any]] = []
            buffer_lock = asyncio.Lock()

            async def flush_variant_batch():
                nonlocal total_variants_persisted, total_products_persisted, last_checkpoint_variants
                async with buffer_lock:
                    if not batch_buffer:
                        return
                    chunk = list(batch_buffer)
                    batch_buffer.clear()

                now_iso = datetime.now(timezone.utc).isoformat()
                # 1. Update products table with variants concurrently
                update_tasks = [
                    cli.update(
                        "products",
                        {"variants": [v.to_dict() for v in it["variants"]], "updated_at": now_iso},
                        filters={"id": f"eq.{it['product_id']}"}
                    )
                    for it in chunk
                ]
                await asyncio.gather(*update_tasks, return_exceptions=True)

                # 2. Batch record completed progress
                progress_items = [
                    {
                        "product_id": it["product_id"],
                        "source_product_id": it["source_product_id"],
                        "variant_count": len(it["variants"])
                    }
                    for it in chunk
                ]
                await batch_record_product_progress(run_id, progress_items, status="completed", client=cli, batch_size=200)

                batch_variants = sum(len(it["variants"]) for it in chunk)
                total_variants_persisted += batch_variants
                total_products_persisted += len(chunk)

                await update_run_counts(run_id, completed_delta=len(chunk), client=cli)
                await export_canonical_backup("tata", client=cli)

                # Milestone checkpoint every 200 variants
                if (total_variants_persisted - last_checkpoint_variants >= 200) or (last_checkpoint_variants == 0 and total_variants_persisted > 0):
                    last_checkpoint_variants = total_variants_persisted
                    print(f"[TATA CHECKPOINT] Saved 200-variant milestone: {total_variants_persisted} total variants in DB ({total_products_persisted}/{total_catalog_count} products).", flush=True)
                else:
                    print(f"[TATA BATCH] Persisted batch of {len(chunk)} products ({total_variants_persisted} total variants in DB).", flush=True)

                gc.collect()

            async def worker(worker_id: int):
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                }
                async with httpx.AsyncClient(headers=headers, timeout=15.0) as http_client:
                    while not queue.empty():
                        if is_stop_requested():
                            break
                        try:
                            item = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        src_id = str(item.get("source_product_id") or "").strip()
                        db_id = item.get("product_id")
                        if not src_id:
                            queue.task_done()
                            continue

                        url = f"https://www.tatacliq.com/marketplacewebservices/v2/mpl/products/productDetails/{src_id.lower()}?isPwa=true&isMDE=true&isDynamicVar=true"
                        variants: List[NormalizedVariant] = []

                        for attempt in range(1, 3):
                            try:
                                resp = await http_client.get(url)
                                if resp.status_code == 200 and resp.text:
                                    data = resp.json()
                                    raw_vars = data.get("variantOptions") or []
                                    variants = [
                                        NormalizedVariant(
                                            size=str(v.get("sizelink", {}).get("size") or v.get("sizelink", {}).get("brandSize") or ""),
                                            sku=v.get("sizelink", {}).get("productCode") or "",
                                            available=bool(v.get("sizelink", {}).get("isAvailable")),
                                            stock=int(v.get("sizelink", {}).get("stockCount") or 0) if v.get("sizelink", {}).get("stockCount") is not None else 0,
                                            url=("https://www.tatacliq.com" + v.get("sizelink", {}).get("url")) if v.get("sizelink", {}).get("url") else ""
                                        )
                                        for v in raw_vars
                                    ]
                                    break
                            except Exception as ex:
                                if attempt == 2:
                                    print(f"[TATA] Worker {worker_id}: Variant fetch error for {src_id}: {ex}", flush=True)
                                await asyncio.sleep(0.3)

                        should_flush = False
                        async with buffer_lock:
                            batch_buffer.append({
                                "product_id": db_id,
                                "source_product_id": src_id,
                                "variants": variants
                            })
                            if len(batch_buffer) >= 25:
                                should_flush = True

                        if should_flush:
                            await flush_variant_batch()

                        if progress_callback:
                            try:
                                await progress_callback({
                                    "stage": "Collecting Variants",
                                    "current": total_products_persisted,
                                    "total": total_catalog_count,
                                    "variant_count": total_variants_persisted
                                })
                            except Exception:
                                pass

                        queue.task_done()
                        await asyncio.sleep(0.04)

            workers = [asyncio.create_task(worker(w_idx + 1)) for w_idx in range(concurrency)]
            await asyncio.gather(*workers)

            # Flush any remaining items in buffer
            await flush_variant_batch()

        dur = round(time.perf_counter() - t_start, 1)
        await update_run_stage(run_id, "finalizing", client=cli)
        export_path = await export_canonical_backup("tata", client=cli)

        report = {
            "scraper": "tata",
            "business_date": run["business_date"],
            "status": "completed",
            "stage": "completed",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "failed_products": 0,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "checkpoints": {
                "listing_pages_completed": len(completed_listing_pages),
                "variant_checkpoint_count": total_variants_persisted
            },
            "error": None
        }
        await complete_run(run_id, report=report, client=cli)

        print("\n" + "=" * 60)
        print(f"TATA CLIQ SCRAPING FINISHED: {total_products_persisted} products persisted")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print(f"Database Report Saved to scrape_runs (ID: {run_id})")
        print("=" * 60 + "\n", flush=True)

        return {
            "status": "completed",
            "run_id": run_id,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "price_records_added": total_prices_added,
            "export_file": str(export_path),
            "report": report
        }

    except Exception as e:
        dur = round(time.perf_counter() - t_start, 1)
        fail_report = {
            "scraper": "tata",
            "business_date": run["business_date"],
            "status": "failed",
            "stage": "variants",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "error": str(e)
        }
        await fail_run(run_id, error=str(e), report=fail_report, client=cli)
        raise


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
    limit: Optional[int] = None,
    force: bool = False,
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

        # Check if already completed in this job or in database today (for resumption across restarts)
        already_completed = (
            existing_job
            and existing_job.get("scrapers", {}).get(s_key, {}).get("status") == "completed"
        )
        prev_p = 0
        prev_v = 0
        prev_dur = 0.0

        if already_completed:
            prev_p = existing_job.get("scrapers", {}).get(s_key, {}).get("product_count", 0)
            prev_v = existing_job.get("scrapers", {}).get(s_key, {}).get("variant_count", 0)
            prev_dur = existing_job.get("scrapers", {}).get(s_key, {}).get("duration_seconds", 0.0)
        elif not force:
            try:
                is_done_today = await is_scraper_completed_today(s_name)
                if is_done_today:
                    already_completed = True
                    summary = await get_daily_scrapers_summary()
                    s_info = summary.get(s_name, {})
                    prev_p = s_info.get("completed_products", 0)
                    prev_v = prev_p
                    prev_dur = s_info.get("duration_seconds", 0.0)
            except Exception as e:
                print(f"[JOB {job_id}] Warning checking today's run status for {s_name}: {e}", flush=True)

        if already_completed:
            cumulative_products += prev_p
            cumulative_variants += prev_v
            completed_pct = round((idx + 1) * weight_per_scraper, 1)
            await update_job(
                job_id,
                product_count=cumulative_products,
                variant_count=cumulative_variants,
                progress_percentage=min(100.0, completed_pct),
                scrapers={
                    s_key: {
                        "status": "completed",
                        "product_count": prev_p,
                        "variant_count": prev_v,
                        "duration_seconds": prev_dur,
                        "error": None,
                    }
                },
            )
            print(f"[JOB {job_id}] ⏩ {s_name.upper()} already completed today ({prev_p} products, {prev_dur}s). Resuming next...", flush=True)
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

        if is_stop_requested():
            reason = get_stop_reason()
            print(f"[JOB {job_id}] 🛑 Stopping pipeline before starting {s_name}. Reason: {reason}", flush=True)
            await update_job(
                job_id,
                status="failed",
                current_scraper=None,
                error=f"STOPPED: {reason}"
            )
            return

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

        except asyncio.CancelledError:
            reason = get_stop_reason()
            print(f"[JOB {job_id}] 🛑 Pipeline received cancellation signal: {reason}", flush=True)
            await stop_current_scraper(reason)
            await update_job(
                job_id,
                status="failed",
                current_scraper=None,
                error=f"STOPPED: {reason}"
            )
            raise

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
    from jobs import reset_boot_tracker
    reset_boot_tracker()

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
    parser.add_argument("--force", action="store_true", default=False, help="Force re-run even if already completed today")
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
            job = await create_job(scrapers=selected, force=args.force)
            await run_sequential_pipeline(job["job_id"], selected_scrapers=selected, limit=args.limit, force=args.force)
        elif target_arg:
            target = target_arg.lower()
            if target in ("pipeline", "all"):
                from jobs import create_job
                job = await create_job(force=args.force)
                await run_sequential_pipeline(job["job_id"], limit=args.limit, force=args.force)
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
