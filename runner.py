import argparse
import asyncio
import json
import os
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
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
from persistence.profile_manager import (
    ProfileSession,
    package_and_upload_profile,
    run_myntra_diagnostic,
    get_profile_config,
)

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
_ACTIVE_PERSISTENT_CONTEXT = None
_SCRAPER_LOCK = asyncio.Lock()


async def get_shared_browser(headless: Optional[bool] = None):
    """
    Returns a persistent single Chromium instance, launching it if not yet started.
    Defaults to headless=True to minimize RAM (<150MB) on resource-constrained servers.
    Can be explicitly set to headless=False (e.g. for Myntra with Akamai protection under Xvfb).
    """
    global _SHARED_PLAYWRIGHT, _SHARED_BROWSER

    # Determine headless mode:
    # 1. Explicit parameter if passed
    # 2. PLAYWRIGHT_HEADLESS environment variable if defined
    # 3. Default True (ultra-low RAM for 512MB environments)
    if headless is not None:
        headless_mode = headless
    elif os.getenv("PLAYWRIGHT_HEADLESS") is not None:
        headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    else:
        headless_mode = True

    if _SHARED_BROWSER and _SHARED_BROWSER.is_connected():
        return _SHARED_BROWSER

    if _SHARED_PLAYWRIGHT is None:
        _SHARED_PLAYWRIGHT = await async_playwright().start()

    print(f"[BROWSER] Launching single Chromium instance (headless={headless_mode}, RAM-optimized)...", flush=True)
    _SHARED_BROWSER = await _SHARED_PLAYWRIGHT.chromium.launch(
        headless=headless_mode,
        ignore_default_args=["--enable-automation"],
        args=LOW_MEMORY_CHROMIUM_ARGS
    )
    return _SHARED_BROWSER


async def close_shared_browser():
    """Explicitly closes any open tab, active persistent context, and shuts down the shared browser."""
    global _SHARED_PLAYWRIGHT, _SHARED_BROWSER, _ACTIVE_PAGE, _ACTIVE_PERSISTENT_CONTEXT
    if _ACTIVE_PAGE:
        try:
            if not _ACTIVE_PAGE.is_closed():
                await _ACTIVE_PAGE.close()
        except Exception:
            pass
        _ACTIVE_PAGE = None

    if _ACTIVE_PERSISTENT_CONTEXT:
        try:
            await _ACTIVE_PERSISTENT_CONTEXT.close()
        except Exception:
            pass
        _ACTIVE_PERSISTENT_CONTEXT = None

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
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME, _ACTIVE_PAGE, _ACTIVE_PERSISTENT_CONTEXT
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

    if _ACTIVE_PERSISTENT_CONTEXT:
        try:
            await _ACTIVE_PERSISTENT_CONTEXT.close()
        except Exception:
            pass
        _ACTIVE_PERSISTENT_CONTEXT = None

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

COLUMBIA_GRAPHQL_ENDPOINT = "https://columbia-sportswear-india.myshopify.com/api/2025-07/graphql.json"

COLUMBIA_GRAPHQL_QUERY = """
query GetProducts($first:Int!, $after:String){
  products(
    first:$first
    after:$after
  ){
    edges{
      cursor
      node{
        id
        title
        handle
        featuredImage{
          url
        }
        variants(first:100){
          edges{
            node{
              sku
              barcode
              availableForSale
              price{
                amount
              }
              compareAtPrice{
                amount
              }
            }
          }
        }
      }
    }
    pageInfo{
      hasNextPage
      endCursor
    }
  }
}
"""


async def scrape_columbia(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Scrapes Columbia Sportswear India product data using native async Shopify GraphQL API.
    Runs with ultra-low memory footprint (~20MB RAM, zero Chromium processes),
    streaming each 250-product page directly into Supabase.
    """
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME
    if not TOKEN:
        raise RuntimeError("SHOPIFY_TOKEN is missing from .env or environment")

    cli = client or get_supabase_client()
    print("\n" + "=" * 60)
    print("STARTING COLUMBIA SPORTSWEAR INDIA SCRAPER (LEAN NATIVE GRAPHQL ENGINE)")
    print("=" * 60, flush=True)

    # 1. Initialize or resume daily scrape run
    run = await get_or_create_daily_run("columbia", client=cli)
    run_id = run["id"]
    _CURRENT_SCRAPER_RUN_ID = run_id
    _CURRENT_SCRAPER_NAME = "columbia"
    print(f"[RUN] Columbia Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    await update_run_stage(run_id, "products", client=cli)

    total_persisted_products = 0
    total_variants_persisted = 0
    total_prices_added = 0
    limit_val = int(limit) if limit else 0
    t_start = time.perf_counter()

    cursor = None
    has_next_page = True
    page = 1

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Storefront-Access-Token": TOKEN
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as http_client:
            while has_next_page:
                if is_stop_requested():
                    reason = get_stop_reason()
                    print(f"[COLUMBIA] 🛑 Stopping scraper due to stop signal: {reason}", flush=True)
                    break

                print(f"[SCRAPER] Fetching Page {page} (cursor: {cursor or 'start'})...", flush=True)
                if progress_callback:
                    try:
                        await progress_callback({
                            "stage": "Collecting Products",
                            "current": page,
                            "total": page + 1,
                            "variant_count": total_variants_persisted
                        })
                    except Exception:
                        pass

                payload_vars = {"first": 250, "after": cursor}
                req_body = {"query": COLUMBIA_GRAPHQL_QUERY, "variables": payload_vars}

                data = None
                for attempt in range(1, 5):
                    try:
                        resp = await http_client.post(COLUMBIA_GRAPHQL_ENDPOINT, headers=headers, json=req_body)
                        if resp.status_code != 200:
                            print(f"[SCRAPER] HTTP {resp.status_code} on Columbia page {page}, attempt {attempt}/4", flush=True)
                            if attempt < 4:
                                await asyncio.sleep(attempt * 2.0)
                                continue
                            break
                        res_json = resp.json()
                        if "errors" in res_json:
                            print(f"[SCRAPER] GraphQL errors on page {page}, attempt {attempt}/4: {res_json['errors']}", flush=True)
                            if attempt < 4:
                                await asyncio.sleep(attempt * 2.0)
                                continue
                            break
                        data = res_json.get("data", {}).get("products") or res_json.get("data", {}).get("search")
                        if data is not None:
                            break
                    except Exception as err:
                        print(f"[SCRAPER] Network error on Columbia page {page}, attempt {attempt}/4: {err}", flush=True)
                        if attempt < 4:
                            await asyncio.sleep(attempt * 2.0)

                if not data:
                    print(f"[SCRAPER] Stopping Columbia pagination at page {page} due to persistent error.", flush=True)
                    break

                edges = data.get("edges") or []
                if not edges:
                    print(f"[SCRAPER] Page {page} returned 0 products. Reached end of catalog.", flush=True)
                    break

                norm_chunk: List[NormalizedProduct] = []
                limit_reached = False
                for edge in edges:
                    node = edge.get("node") or {}
                    pid = str(node.get("id") or "").split("/")[-1]
                    title = str(node.get("title") or "").strip()
                    handle = str(node.get("handle") or "").strip()
                    image_url = (node.get("featuredImage") or {}).get("url") or ""
                    product_url = f"https://www.columbiasportswear.co.in/products/{handle}" if handle else "https://www.columbiasportswear.co.in"

                    variants: List[NormalizedVariant] = []
                    first_sku = None
                    first_ean = None
                    min_price = None
                    max_mrp = None

                    variant_edges = (node.get("variants") or {}).get("edges") or []
                    for v_edge in variant_edges:
                        v_node = v_edge.get("node") or {}
                        v_sku = str(v_node.get("sku") or "").strip() or None
                        v_barcode = str(v_node.get("barcode") or "").strip() or None
                        v_avail = bool(v_node.get("availableForSale", True))

                        try:
                            v_price = float((v_node.get("price") or {}).get("amount") or 0.0)
                        except Exception:
                            v_price = 0.0

                        try:
                            comp = v_node.get("compareAtPrice")
                            if comp and comp.get("amount"):
                                v_mrp = float(comp.get("amount") or 0.0)
                            else:
                                v_mrp = v_price
                        except Exception:
                            v_mrp = v_price

                        if not first_sku and v_sku:
                            first_sku = v_sku
                        if not first_ean and v_barcode:
                            first_ean = v_barcode
                        if v_price > 0:
                            if min_price is None or v_price < min_price:
                                min_price = v_price
                        if v_mrp > 0:
                            if max_mrp is None or v_mrp > max_mrp:
                                max_mrp = v_mrp

                        variants.append(
                            NormalizedVariant(
                                size="",
                                sku=v_sku,
                                ean=v_barcode,
                                available=v_avail,
                                price=v_price,
                                mrp=v_mrp if v_mrp > 0 else None,
                                url=product_url,
                            )
                        )

                    norm_chunk.append(
                        NormalizedProduct(
                            source="columbia",
                            source_product_id=pid,
                            title=title,
                            sku=first_sku or (variants[0].sku if variants else None),
                            ean=first_ean or (variants[0].ean if variants else None),
                            price=min_price or (variants[0].price if variants else 0.0),
                            mrp=max_mrp or (variants[0].mrp if variants else None),
                            available=any(v.available for v in variants) if variants else True,
                            image_url=image_url,
                            url=product_url,
                            variants=variants,
                            scraped_at=datetime.now(timezone.utc).isoformat(),
                        )
                    )

                    if limit_val > 0 and (total_persisted_products + len(norm_chunk)) >= limit_val:
                        limit_reached = True
                        break

                # Stream and persist chunk into Supabase
                if norm_chunk:
                    db_prods = await upsert_canonical_products_batch(norm_chunk, client=cli, batch_size=200)
                    id_by_src = {p["source_product_id"]: p["id"] for p in db_prods if "source_product_id" in p and "id" in p}

                    price_entries = []
                    progress_items = []
                    chunk_variants = 0
                    for prod in norm_chunk:
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
                        total_prices_added += added

                    if progress_items:
                        await batch_record_product_progress(
                            run_id, progress_items, status="completed", client=cli, batch_size=200
                        )

                    total_persisted_products += len(norm_chunk)
                    total_variants_persisted += chunk_variants
                    await update_run_counts(run_id, completed_delta=len(norm_chunk), client=cli)
                    print(f"[SCRAPER] Page {page}: fetched {len(edges)} products. Total SKUs so far: {total_variants_persisted}", flush=True)

                del norm_chunk
                import gc
                gc.collect()

                if limit_reached:
                    print(f"[SCRAPER] Product limit {limit_val} reached. Stopping Columbia pagination.", flush=True)
                    break

                page_info = data.get("pageInfo") or {}
                has_next_page = bool(page_info.get("hasNextPage")) and len(edges) > 0
                cursor = page_info.get("endCursor") or (edges[-1].get("cursor") if edges else None)
                page += 1
                if has_next_page:
                    await asyncio.sleep(0.3)

        total_pages = max(1, page - 1)
        print(f"[SCRAPER] Collected {total_variants_persisted} products across {total_pages} pages", flush=True)
        print("[SCRAPER] Done!", flush=True)
        print(f"[SCRAPER] Total SKUs: {total_variants_persisted}", flush=True)

        # Finalize run and export local rolling backup
        await update_run_stage(run_id, "finalizing", client=cli)
        export_path = await export_canonical_backup("columbia", client=cli)
        dur = round(time.perf_counter() - t_start, 1)
        columbia_report = {
            "scraper": "columbia",
            "business_date": run["business_date"],
            "status": "completed",
            "stage": "completed",
            "total_products": total_persisted_products,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "failed_products": 0,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "error": None
        }
        await complete_run(run_id, report=columbia_report, client=cli)

        if progress_callback:
            try:
                await progress_callback({
                    "stage": "Completed",
                    "current": total_pages,
                    "total": total_pages,
                    "variant_count": total_variants_persisted
                })
            except Exception:
                pass

        print("\n" + "=" * 60)
        print(f"COLUMBIA SCRAPING FINISHED: {total_persisted_products} products persisted")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print("=" * 60 + "\n", flush=True)

        return {
            "status": "completed",
            "run_id": run_id,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "failed_products": 0,
            "price_records_added": total_prices_added,
            "export_file": str(export_path),
        }

    except Exception as e:
        dur = round(time.perf_counter() - t_start, 1)
        fail_report = {
            "scraper": "columbia",
            "business_date": run["business_date"],
            "status": "failed",
            "stage": "products",
            "total_products": total_persisted_products,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "error": str(e)
        }
        await fail_run(run_id, error=str(e), report=fail_report, client=cli)
        raise
    finally:
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None


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
    print("\n" + "=" * 60)
    print("MYNTRA SCRAPER: DISABLED (Cookie/profile injection stopped to preserve RAM)")
    print("=" * 60, flush=True)
    return {
        "source": "myntra",
        "status": "skipped",
        "total_products": 0,
        "completed_products": 0,
        "total_variants": 0,
        "duration_seconds": 0.0,
        "message": "Myntra scraper disabled to keep RAM minimum."
    }
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
            # Ensure previous shared browser (e.g. from Columbia or Adventuras) is closed
            # so Myntra launches exclusively under low RAM
            await close_shared_browser()

            profile_info = None
            persistent_context = None
            playwright_inst = None
            diag_title = "unknown"
            diag_url = "unknown"
            diag_cookies = 0
            diag_error = None
            diag_details = {}

            # Execute within managed ProfileSession (download, validate, lock)
            async with ProfileSession(run_id=run_id, client=cli) as p_info:
                profile_info = p_info
                user_data_dir = profile_info["user_data_dir"]
                profile_name = profile_info.get("profile_name") or "Default"

                # Determine headless mode: default to False on Render (under Xvfb) for Akamai anti-bot evasion
                if os.getenv("PLAYWRIGHT_HEADLESS") is not None:
                    headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
                else:
                    headless_mode = False

                print(
                    f"[MYNTRA] 🚀 Launching Playwright persistent context (headless={headless_mode}, profile={profile_name}, user_data_dir={user_data_dir})...",
                    flush=True
                )

                args = list(LOW_MEMORY_CHROMIUM_ARGS)
                if profile_name:
                    args.append(f"--profile-directory={profile_name}")

                playwright_inst = await async_playwright().start()
                try:
                    persistent_context = await playwright_inst.chromium.launch_persistent_context(
                        user_data_dir=str(user_data_dir),
                        headless=headless_mode,
                        ignore_default_args=["--enable-automation"],
                        args=args,
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
                    _ACTIVE_PERSISTENT_CONTEXT = persistent_context

                    # Inspect restored cookies without revealing secret values
                    try:
                        restored_cookies = await persistent_context.cookies(["https://www.myntra.com"])
                        print(f"[COOKIES] Restored persistent profile has {len(restored_cookies)} cookies for .myntra.com", flush=True)
                    except Exception as e:
                        print(f"[COOKIES] Notice: Could not read cookies from persistent context: {e}", flush=True)

                    # Ingest any supplemental Akamai cookies configured in env
                    akamai_env_cookies = load_akamai_cookies()
                    if akamai_env_cookies:
                        try:
                            await persistent_context.add_cookies(akamai_env_cookies)
                            print(f"[COOKIES] Injected {len(akamai_env_cookies)} supplemental Akamai cookies into session", flush=True)
                        except Exception as e:
                            print(f"[COOKIES] Warning: Failed to inject supplemental cookies: {e}", flush=True)
                    elif DEFAULT_MYNTRA_TOKEN:
                        try:
                            await persistent_context.add_cookies([{
                                "name": "at",
                                "value": DEFAULT_MYNTRA_TOKEN,
                                "domain": ".myntra.com",
                                "path": "/"
                            }])
                        except Exception:
                            pass

                    page = persistent_context.pages[0] if persistent_context.pages else await persistent_context.new_page()
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

                    print("Navigating persistent tab to https://www.myntra.com/columbia...", flush=True)
                    for attempt in range(1, 4):
                        try:
                            await page.goto("https://www.myntra.com/columbia", wait_until="domcontentloaded", timeout=timeout_ms)
                            break
                        except Exception as e:
                            if attempt == 3:
                                raise
                            print(f"[MYNTRA] Navigation retry {attempt}/3 due to: {e}", flush=True)
                            await asyncio.sleep(2)

                    # Immediate anti-bot / challenge inspection
                    try:
                        nav_title = await page.title()
                        if any(term in nav_title.lower() for term in ("access denied", "maintenance", "blocked")):
                            print(f"[MYNTRA DIAGNOSTICS] ⚠️ Immediate challenge / maintenance response detected: '{nav_title}'", flush=True)
                    except Exception:
                        pass

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

                    # Capture rich session diagnostics
                    try:
                        diag_title = await page.title()
                    except Exception:
                        diag_title = "unknown"
                    try:
                        diag_url = page.url
                    except Exception:
                        diag_url = "unknown"
                    try:
                        diag_cookies = len(await persistent_context.cookies())
                    except Exception:
                        diag_cookies = 0
                    try:
                        diag_error = await page.evaluate("() => window.__SCRAPER_ERROR__ || null")
                    except Exception:
                        diag_error = None
                    try:
                        diag_details = await page.evaluate("() => window.__MYNTRA_DIAGNOSTICS__ || {}")
                    except Exception:
                        diag_details = {}

                finally:
                    # Cleanly close persistent browser BEFORE packaging or cleanup
                    _ACTIVE_PAGE = None
                    if persistent_context:
                        try:
                            await persistent_context.close()
                        except Exception:
                            pass
                        persistent_context = None
                        _ACTIVE_PERSISTENT_CONTEXT = None

                    if playwright_inst:
                        try:
                            await playwright_inst.stop()
                        except Exception:
                            pass
                        playwright_inst = None

                    import gc
                    gc.collect()
                    await asyncio.sleep(1.0)
                    print("[BROWSER] Myntra persistent browser closed cleanly. Memory reclaimed.", flush=True)

                # Persist profile ONLY if scrape was successful and not stopped
                if total_persisted_products > 0 and not is_stop_requested():
                    print(
                        f"[PROFILE] Scrape succeeded ({total_persisted_products} products). "
                        "Packaging and safely persisting updated profile to Supabase Storage...",
                        flush=True
                    )
                    try:
                        await package_and_upload_profile(profile_info, client=cli)
                    except Exception as e:
                        print(f"[PROFILE] Warning: Could not upload updated profile: {e}", flush=True)
                else:
                    print(
                        f"[PROFILE] Scrape finished with {total_persisted_products} products (status: failed/interrupted). "
                        "Preserving last known-good archive in Supabase Storage. Skipping upload.",
                        flush=True
                    )

        dur = round(time.perf_counter() - t_start, 1)
        await update_run_stage(run_id, "finalizing", client=cli)
        export_path = await export_canonical_backup("myntra", client=cli)

        err_msg = None
        if total_persisted_products == 0:
            http_st = diag_details.get("http_status", "unknown")
            body_prev = str(diag_details.get("body_preview") or "").strip().replace("\n", " ")[:120]
            err_msg = f"0 products collected. Error: {diag_error or 'Akamai/bot challenge page returned instead of JSON'}. (HTTP {http_st}, Title: '{diag_title}', Cookies: {diag_cookies}, Preview: '{body_prev}')"
            print(f"\n[MYNTRA DIAGNOSTICS] ⚠️ {err_msg}\n", flush=True)

        myntra_status = "failed" if total_persisted_products == 0 else "completed"

        report = {
            "scraper": "myntra",
            "business_date": run["business_date"],
            "status": myntra_status,
            "stage": "completed",
            "total_products": total_persisted_products,
            "completed_products": total_persisted_products,
            "failed_products": 0 if total_persisted_products > 0 else 1,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "completed_pages": sorted(list(completed_pages)),
            "checkpoints": {
                "listing_pages_completed": len(completed_pages),
            },
            "duration_seconds": dur,
            "error": err_msg,
            "diagnostics": {
                "page_title": diag_title,
                "current_url": diag_url,
                "cookies_injected": diag_cookies,
                "js_error": diag_error,
                "api_details": diag_details,
            }
        }
        await complete_run(run_id, report=report, client=cli)

        print("\n" + "=" * 60)
        print(f"MYNTRA SCRAPING FINISHED: {total_persisted_products} products persisted (Status: {myntra_status})")
        if err_msg:
            print(f"Diagnostics: {err_msg}")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print(f"Database Report Saved to scrape_runs (ID: {run_id})")
        print("=" * 60 + "\n", flush=True)

        return {
            "status": myntra_status,
            "run_id": run_id,
            "completed_products": total_persisted_products,
            "total_variants": total_variants_persisted,
            "error": err_msg,
            "diagnostics": report["diagnostics"],
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

    # Check if full catalog is already present in DB
    existing_catalog_sample = await cli.select(
        "products",
        columns="id",
        filters={"scraper_id": f"eq.{scraper_id}"},
        limit=1500
    )
    has_full_catalog = bool(existing_catalog_sample and len(existing_catalog_sample) >= 1500)
    phase1_needed = not (len(completed_listing_pages) >= 50 or (has_full_catalog and not limit))

    if not phase1_needed:
        print(f"[TATA CHECKPOINT] Phase 1 already complete ({len(completed_listing_pages)} pages in DB, full catalog detected). Skipping listing browser.", flush=True)
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
# Tata CLiQ Luxury Scraper (Browser JS Listings + Python PDP Checkpoints)
# =========================================================================

def normalize_tata_lux_js_product(raw_p: Dict[str, Any]) -> NormalizedProduct:
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
        source="tata_lux",
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


def _extract_tata_lux_pdp_variants_and_price(
    html: str,
    fallback_price: float = 0.0,
    fallback_mrp: float = 0.0
) -> Tuple[List[NormalizedVariant], float, float]:
    """
    Parses variantOptions / variantGroup and JSON-LD / HTML prices from Tata Luxury PDP HTML.
    Mirrors the logic in scraper/tata_lux_scraper.js.
    """
    variants: List[NormalizedVariant] = []
    price = 0.0
    mrp = 0.0

    # 1. Variant extraction from variantOptions
    marker = '"variantOptions":['
    idx = html.find(marker)
    if idx != -1:
        start = idx + len('"variantOptions":')
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(html)):
            c = html[i]
            if in_str:
                if escaped:
                    escaped = False
                elif c == '\\':
                    escaped = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
                continue
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    try:
                        raw_vars = json.loads(html[start:i+1])
                        for v in raw_vars:
                            sl = v.get("sizelink") or v.get("sizeLink") or v or {}
                            sku = str(sl.get("productCode") or "")
                            size = str(sl.get("size") or sl.get("brandSize") or "")
                            url_part = str(sl.get("url") or "")
                            if not sku and not size and not url_part:
                                continue
                            if url_part and not url_part.startswith("http"):
                                url_part = "https://luxury.tatacliq.com" + ("" if url_part.startswith("/") else "/") + url_part
                            stock_cnt = 0
                            try:
                                stock_cnt = int(sl.get("stockCount") or 0)
                            except Exception:
                                pass
                            variants.append(
                                NormalizedVariant(
                                    size=size,
                                    sku=sku or None,
                                    available=bool(sl.get("isAvailable")),
                                    stock=stock_cnt,
                                    url=url_part or None
                                )
                            )
                    except Exception:
                        pass
                    break

    # 1b. Fallback to variantGroup if variantOptions was empty
    if not variants and '"variantGroup"' in html:
        vg_marker = '"variantGroup":['
        vg_idx = html.find(vg_marker)
        if vg_idx != -1:
            vg_start = vg_idx + len('"variantGroup":')
            vg_depth = 0
            vg_in_str = False
            vg_escaped = False
            for i in range(vg_start, len(html)):
                c = html[i]
                if vg_in_str:
                    if vg_escaped:
                        vg_escaped = False
                    elif c == '\\':
                        vg_escaped = True
                    elif c == '"':
                        vg_in_str = False
                    continue
                if c == '"':
                    vg_in_str = True
                    continue
                if c == '[':
                    vg_depth += 1
                elif c == ']':
                    vg_depth -= 1
                    if vg_depth == 0:
                        try:
                            raw_groups = json.loads(html[vg_start:i+1])
                            for grp in raw_groups:
                                color_link = grp.get("colorLink") or grp.get("colorlink") or {}
                                size_opts = grp.get("sizeOptions") or []
                                for sz in size_opts:
                                    sku = str(sz.get("productCode") or "")
                                    size = str(sz.get("size") or sz.get("brandSize") or "")
                                    url_part = str(sz.get("url") or color_link.get("colorurl") or "")
                                    if not sku and not size and not url_part:
                                        continue
                                    if url_part and not url_part.startswith("http"):
                                        url_part = "https://luxury.tatacliq.com" + ("" if url_part.startswith("/") else "/") + url_part
                                    variants.append(
                                        NormalizedVariant(
                                            size=size,
                                            sku=sku or None,
                                            available=bool(sz.get("isAvailable")),
                                            stock=int(sz.get("stockCount") or 0) if sz.get("stockCount") is not None else 0,
                                            url=url_part or None
                                        )
                                    )
                        except Exception:
                            pass
                        break

    # Deduplicate variants by SKU, then size|url
    seen_vars = set()
    deduped_variants = []
    for v in variants:
        k = v.sku or f"{v.size}|{v.url}"
        if k not in seen_vars:
            seen_vars.add(k)
            deduped_variants.append(v)

    # 2. Price extraction
    # Method A: JSON-LD
    json_ld_matches = re.findall(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', html, re.DOTALL)
    for block in json_ld_matches:
        try:
            parsed = json.loads(block.strip())
            nodes = parsed if isinstance(parsed, list) else [parsed]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                offers = node.get("offers")
                if not offers:
                    continue
                offer_list = offers if isinstance(offers, list) else [offers]
                for off in offer_list:
                    if not isinstance(off, dict):
                        continue
                    p_val = off.get("price") or off.get("lowPrice")
                    if p_val:
                        try:
                            clean_p = float(str(p_val).replace(",", "").strip())
                            if clean_p > 0:
                                price = clean_p
                                mrp_val = off.get("highPrice") or off.get("price")
                                if mrp_val:
                                    mrp = float(str(mrp_val).replace(",", "").strip())
                                break
                        except Exception:
                            pass
                if price > 0:
                    break
        except Exception:
            pass
        if price > 0:
            break

    # Method B: Regex fallback
    if price == 0.0:
        sp_m = re.search(r'"(?:sellingPrice|salePrice|discountedPrice|offerPrice|finalPrice|currentPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', html, re.I)
        if sp_m:
            try:
                price = float(sp_m.group(1))
            except Exception:
                pass

    if mrp == 0.0:
        mrp_m = re.search(r'"(?:mrpPrice|mrp|listPrice|originalPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', html, re.I)
        if mrp_m:
            try:
                mrp = float(mrp_m.group(1))
            except Exception:
                pass

    if price == 0.0:
        price = fallback_price
    if mrp == 0.0:
        mrp = fallback_mrp or price

    return deduped_variants, price, mrp


async def scrape_tata_lux(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None
) -> Dict[str, Any]:
    """
    Executes the Tata CLiQ Luxury scraper with decoupled two-phase architecture:
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
    print("STARTING TATA CLIQ LUXURY SCRAPER (ZERO-LEAK TWO-PHASE CHECKPOINTED)")
    if limit:
        print(f"TEST MODE: Limited to {limit} products")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("tata_lux", client=cli)
    run_id = run["id"]
    scraper_id = await get_scraper_id("tata_lux", cli)
    print(f"[RUN] Tata Luxury Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    # =========================================================================
    # Phase 1: Listing Pages & Base Products
    # =========================================================================
    completed_listing_pages = await get_completed_listing_pages(run_id, client=cli)

    # Check if full catalog is already present in DB
    existing_catalog_sample = await cli.select(
        "products",
        columns="id",
        filters={"scraper_id": f"eq.{scraper_id}"},
        limit=1500
    )
    has_full_catalog = bool(existing_catalog_sample and len(existing_catalog_sample) >= 1500)
    phase1_needed = not (len(completed_listing_pages) >= 90 or (has_full_catalog and not limit))

    if not phase1_needed:
        print(f"[TATA LUX CHECKPOINT] Phase 1 already complete ({len(completed_listing_pages)} pages in DB, full catalog detected). Skipping listing browser.", flush=True)
    else:
        print(f"[TATA LUX PHASE 1] Starting listing page collection (starting from page {len(completed_listing_pages)})...", flush=True)
        await update_run_stage(run_id, "listings", client=cli)
        scraper_path = SCRAPER_DIR / "tata_lux_scraper.js"
        scraper_code = scraper_path.read_text(encoding="utf-8")
        timeout_ms = int(os.getenv("TATA_LUX_SCRAPE_TIMEOUT_SECONDS", "3600")) * 1000

        async def drain_tata_lux_listings(listings_chunk: List[Dict[str, Any]]):
            """Phase 1: Persist listing page checkpoints and base product records."""
            for item in listings_chunk:
                p_num = item.get("page", 0)
                raw_prods = item.get("products", [])
                if not raw_prods:
                    await record_listing_page_completed(run_id, p_num, 0, client=cli)
                    continue

                norm_prods = [normalize_tata_lux_js_product(p) for p in raw_prods]
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
                await export_canonical_backup("tata_lux", client=cli)
                print(f"[TATA LUX CHECKPOINT] Listing Page {p_num + 1} persisted ({len(raw_prods)} products).", flush=True)

        async with _SCRAPER_LOCK:
            await close_shared_browser()
            browser = await get_shared_browser(headless=True)
            try:
                page = await _create_lean_tab(browser, "https://luxury.tatacliq.com/")
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
                    on_drain_listings=drain_tata_lux_listings,
                )

                final_listings = await page.evaluate("() => typeof window.drainUnsavedListings === 'function' ? window.drainUnsavedListings() : []")
                if final_listings:
                    await drain_tata_lux_listings(final_listings)
            finally:
                await close_shared_browser()
                gc.collect()
                print("[BROWSER] Tata Lux Phase 1 browser closed. All RAM freed.", flush=True)

    # =========================================================================
    # Phase 2: Middle Resumption & Concurrency=3 Python Variant Fetcher
    # =========================================================================
    await update_run_stage(run_id, "variants", client=cli)

    pending_items = await get_incomplete_products(run_id, client=cli)

    if not pending_items:
        any_prog = await cli.select("scrape_product_progress", columns="id", filters={"scrape_run_id": f"eq.{run_id}"}, limit=1)
        if not any_prog:
            print("[TATA LUX CHECKPOINT] Initializing product progress tracking from catalog in database...", flush=True)
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

    print(f"\n[TATA LUX RESUME] Catalog: {total_catalog_count} products. Already completed: {len(completed_product_ids)}. Pending: {len(pending_items)}.")
    if completed_product_ids:
        print(f"[TATA LUX RESUME] Resuming from product {len(completed_product_ids) + 1}/{total_catalog_count} (middle checkpoint)!", flush=True)

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
            print("[TATA LUX] All products already have completed variant checkpoints today! Nothing pending.", flush=True)
        else:
            concurrency = int(os.getenv("TATA_LUX_CONCURRENCY", "3"))
            print(f"[TATA LUX PHASE 2] Starting variant extraction in Python with CONCURRENCY={concurrency} (Browser: CLOSED, RAM: <30MB)...", flush=True)

            queue: asyncio.Queue = asyncio.Queue()
            for item in pending_items:
                queue.put_nowait(item)

            batch_buffer: List[Dict[str, Any]] = []
            buffer_lock = asyncio.Lock()

            async def flush_variant_batch():
                nonlocal total_variants_persisted, total_products_persisted, last_checkpoint_variants, total_prices_added
                async with buffer_lock:
                    if not batch_buffer:
                        return
                    chunk = list(batch_buffer)
                    batch_buffer.clear()

                now_iso = datetime.now(timezone.utc).isoformat()
                # 1. Update products table with variants and prices concurrently
                update_tasks = []
                for it in chunk:
                    up_data: Dict[str, Any] = {
                        "variants": [v.to_dict() for v in it["variants"]],
                        "updated_at": now_iso
                    }
                    if it.get("price") and it["price"] > 0:
                        up_data["current_price"] = it["price"]
                    if it.get("mrp") and it["mrp"] > 0:
                        up_data["current_mrp"] = it["mrp"]

                    update_tasks.append(
                        cli.update(
                            "products",
                            up_data,
                            filters={"id": f"eq.{it['product_id']}"}
                        )
                    )
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
                await export_canonical_backup("tata_lux", client=cli)

                # Milestone checkpoint every 200 variants
                if (total_variants_persisted - last_checkpoint_variants >= 200) or (last_checkpoint_variants == 0 and total_variants_persisted > 0):
                    last_checkpoint_variants = total_variants_persisted
                    print(f"[TATA LUX CHECKPOINT] Saved 200-variant milestone: {total_variants_persisted} total variants in DB ({total_products_persisted}/{total_catalog_count} products).", flush=True)
                else:
                    print(f"[TATA LUX BATCH] Persisted batch of {len(chunk)} products ({total_variants_persisted} total variants in DB).", flush=True)

                gc.collect()

            async def worker(worker_id: int):
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                }
                async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as http_client:
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

                        url = f"https://luxury.tatacliq.com/p-{src_id.lower()}"
                        variants: List[NormalizedVariant] = []
                        pdp_price = 0.0
                        pdp_mrp = 0.0

                        for attempt in range(1, 3):
                            try:
                                resp = await http_client.get(url)
                                if resp.status_code == 200 and resp.text:
                                    variants, pdp_price, pdp_mrp = _extract_tata_lux_pdp_variants_and_price(resp.text)
                                    break
                            except Exception as ex:
                                if attempt == 2:
                                    print(f"[TATA LUX] Worker {worker_id}: Variant fetch error for {src_id}: {ex}", flush=True)
                                await asyncio.sleep(0.4)

                        should_flush = False
                        async with buffer_lock:
                            batch_buffer.append({
                                "product_id": db_id,
                                "source_product_id": src_id,
                                "variants": variants,
                                "price": pdp_price,
                                "mrp": pdp_mrp
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
                        await asyncio.sleep(0.05)

            workers = [asyncio.create_task(worker(w_idx + 1)) for w_idx in range(concurrency)]
            await asyncio.gather(*workers)

            # Flush any remaining items in buffer
            await flush_variant_batch()

        dur = round(time.perf_counter() - t_start, 1)
        await update_run_stage(run_id, "finalizing", client=cli)
        export_path = await export_canonical_backup("tata_lux", client=cli)

        report = {
            "scraper": "tata_lux",
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
            },
            "error": None
        }
        await complete_run(run_id, report=report, client=cli)

        print("\n" + "=" * 60)
        print(f"TATA CLIQ LUXURY SCRAPING FINISHED: {total_products_persisted} products persisted")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print(f"Database Report Saved to scrape_runs (ID: {run_id})")
        print("=" * 60, flush=True)

        return {
            "source": "tata_lux",
            "status": "completed",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "report": report
        }

    except Exception as e:
        dur = round(time.perf_counter() - t_start, 1)
        fail_report = {
            "scraper": "tata_lux",
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
    finally:
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None


# =========================================================================
# Amazon Scraper (Playwright Single Browser + Supabase Persistence)
# =========================================================================

def normalize_amazon_product(raw_p: Dict[str, Any]) -> NormalizedProduct:
    """Converts extracted Amazon card item to NormalizedProduct."""
    asin = str(raw_p.get("asin") or "").strip()
    title = str(raw_p.get("title") or "").strip()
    p_num = raw_p.get("price_numeric")
    m_num = raw_p.get("mrp_numeric")
    image_url = raw_p.get("image") or None
    url = raw_p.get("href") or f"https://www.amazon.in/dp/{asin}"
    family = raw_p.get("family", [asin])

    variants = []
    for var_asin in family:
        variants.append(
            NormalizedVariant(
                size="",
                sku=var_asin,
                ean=None,
                available=True,
                price=p_num,
                mrp=m_num,
                url=f"https://www.amazon.in/dp/{var_asin}",
            )
        )

    return NormalizedProduct(
        source="amazon",
        source_product_id=asin,
        title=title,
        sku=asin,
        ean=None,
        price=p_num,
        mrp=m_num,
        available=bool(p_num or title),
        image_url=image_url,
        url=url,
        variants=variants,
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )


async def scrape_amazon(
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    client=None,
) -> Dict[str, Any]:
    """
    Scrapes Amazon products from configured sellers using a single Playwright browser,
    then normalizes and batch persists canonical products, variants, and price history into Supabase.
    """
    global _CURRENT_SCRAPER_RUN_ID, _CURRENT_SCRAPER_NAME
    cli = client or get_supabase_client()
    t_start = time.perf_counter()

    print("\n" + "=" * 60)
    print("STARTING AMAZON SCRAPER (SINGLE BROWSER, ULTRA-LOW RAM)")
    print("=" * 60, flush=True)

    run = await get_or_create_daily_run("amazon", client=cli)
    run_id = run["id"]
    _CURRENT_SCRAPER_RUN_ID = run_id
    _CURRENT_SCRAPER_NAME = "amazon"
    print(f"[RUN] Amazon Scrape Run ID: {run_id} (Date: {run['business_date']}, Status: {run['status']})")

    total_products_persisted = 0
    total_variants_persisted = 0
    total_prices_added = 0

    try:
        from amazon_scraper.amazon_scraper import run_amazon_scraper
        await update_run_stage(run_id, "products", client=cli)

        res = await run_amazon_scraper(
            limit=limit,
            progress_callback=progress_callback,
        )

        raw_products = res.get("products", [])
        norm_products = [normalize_amazon_product(p) for p in raw_products]
        if limit:
            norm_products = norm_products[:limit]

        # Batch persist into Supabase in chunks of 200
        batch_size = 200
        print(f"\n[PERSISTENCE] Persisting {len(norm_products)} Amazon products to Supabase (batches of {batch_size})...")

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
                    "mrp": prod.mrp,
                })
                progress_items.append({
                    "product_id": pid,
                    "source_product_id": prod.source_product_id,
                    "variant_count": len(prod.variants),
                })

        total_prices_added = await batch_record_prices_if_changed(
            price_entries, scrape_run_id=run_id, client=cli, batch_size=batch_size
        )

        await batch_record_product_progress(
            run_id, progress_items, status="completed", client=cli, batch_size=batch_size
        )

        total_products_persisted = len(progress_items)
        failed_count = len(norm_products) - total_products_persisted
        total_variants_persisted = sum(len(p.variants) for p in norm_products)

        await update_run_counts(run_id, completed_delta=total_products_persisted, failed_delta=failed_count, client=cli)
        await update_run_stage(run_id, "finalizing", client=cli)

        export_path = await export_canonical_backup("amazon", client=cli)
        dur = round(time.perf_counter() - t_start, 1)

        report = {
            "scraper": "amazon",
            "business_date": run["business_date"],
            "status": "completed",
            "stage": "completed",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "failed_products": failed_count,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "error": None,
        }
        await complete_run(run_id, report=report, client=cli)

        print("\n" + "=" * 60)
        print(f"AMAZON SCRAPING FINISHED: {total_products_persisted} products persisted")
        print(f"Total Variants Persisted: {total_variants_persisted}")
        print(f"Price Records Added: {total_prices_added}")
        print(f"Local Rolling Backup: {export_path.resolve()}")
        print(f"Database Report Saved to scrape_runs (ID: {run_id})")
        print("=" * 60, flush=True)

        return {
            "source": "amazon",
            "status": "completed",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "report": report,
        }

    except Exception as e:
        dur = round(time.perf_counter() - t_start, 1)
        fail_report = {
            "scraper": "amazon",
            "business_date": run["business_date"],
            "status": "failed",
            "stage": "products",
            "total_products": total_products_persisted,
            "completed_products": total_products_persisted,
            "total_variants": total_variants_persisted,
            "prices_recorded": total_prices_added,
            "duration_seconds": dur,
            "error": str(e),
        }
        await fail_run(run_id, error=str(e), report=fail_report, client=cli)
        raise
    finally:
        _CURRENT_SCRAPER_RUN_ID = None
        _CURRENT_SCRAPER_NAME = None


# =========================================================================
# Sequential Pipeline Coordinator (Columbia -> Adventuras -> Tata CLiQ -> Tata CLiQ Luxury -> Amazon)
# =========================================================================

ORDERED_SCRAPERS = ["columbia", "adv", "tata", "tata_lux", "amazon"]

SCRAPER_KEY_MAP = {
    "columbia": "columbia",
    "adv": "adv",
    "tata": "tatacliq",
    "tata_lux": "tata_lux",
    "lux": "tata_lux",
    "amazon": "amazon",
}

SCRAPER_FUNCS = {
    "columbia": scrape_columbia,
    "adv": scrape_adv,
    "tata": scrape_tata,
    "tata_lux": scrape_tata_lux,
    "amazon": scrape_amazon,
}


def normalize_scraper_names(scrapers: Optional[List[str]]) -> List[str]:
    """
    Normalizes scraper aliases and strictly enforces canonical sequential execution order:
    columbia -> adv -> tata -> tata_lux -> amazon.
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
        "tatacliq": "tata",
        "tata_lux": "tata_lux",
        "tatalux": "tata_lux",
        "tatacliq_luxury": "tata_lux",
        "lux": "tata_lux",
        "amazon": "amazon",
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
            s_status = res.get("status", "completed")
            s_error = res.get("error")
            await update_job(
                job_id,
                product_count=cumulative_products,
                variant_count=cumulative_variants,
                progress_percentage=min(100.0, completed_pct),
                scrapers={
                    s_key: {
                        "status": s_status,
                        "product_count": prods,
                        "variant_count": vars_cnt,
                        "duration_seconds": dur,
                        "error": s_error
                    }
                }
            )
            icon = "✅" if s_status == "completed" else "⚠️"
            print(f"[JOB {job_id}] {icon} {s_name.upper()} {s_status.upper()} ({prods} products, {vars_cnt} variants, {dur}s)", flush=True)

            # Reclaim browser and memory before next scraper
            try:
                await close_shared_browser()
            except Exception:
                pass
            import gc
            gc.collect()

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
    # Print final summary of all scrapers
    t_pipeline_total = round(time.perf_counter() - t_pipeline_start, 1)
    await _print_pipeline_summary(job_id, active_scrapers, t_pipeline_total, cumulative_products, cumulative_variants)


async def _print_pipeline_summary(
    job_id: str,
    active_scrapers: List[str],
    t_total: float,
    cumulative_products: int,
    cumulative_variants: int
):
    from jobs import get_job
    job_snapshot = await get_job(job_id)
    job_scrapers = job_snapshot.get("scrapers", {}) if job_snapshot else {}
    print("\n" + "=" * 80)
    print(f"               PIPELINE EXECUTION SUMMARY (Job: {job_id})")
    print(f"Total Duration: {t_total:.1f}s | Total Products: {cumulative_products:,} | Total Variants: {cumulative_variants:,}")
    print("-" * 80)
    print(f"{'Scraper':<16} {'Status':<12} {'Products':<10} {'Variants':<10} {'Duration':<12} {'Error'}")
    print("-" * 80)
    for s_name in active_scrapers:
        s_key = SCRAPER_KEY_MAP.get(s_name, s_name)
        s_data = job_scrapers.get(s_key, {})
        st = str(s_data.get("status", "unknown")).upper()
        p_c = f"{s_data.get('product_count', 0):,}"
        v_c = f"{s_data.get('variant_count', 0):,}"
        dur_val = s_data.get("duration_seconds", 0.0)
        d_s = f"{dur_val:.1f}s" if dur_val else "-"
        err = s_data.get("error") or "-"
        print(f"{s_name:<16} {st:<12} {p_c:<10} {v_c:<10} {d_s:<12} {err}")
    print("=" * 80 + "\n", flush=True)


main = scrape_columbia


async def _run_cli():
    parser = argparse.ArgumentParser(description="Unified Columbia Scrapers Pipeline")
    parser.add_argument("target", nargs="?", default=None, help="Target scraper: 'columbia', 'adv', 'tata', 'tata_lux', 'amazon', or 'pipeline'")
    parser.add_argument("--scraper", type=str, default=None, help="Scraper name: 'columbia', 'adv', 'tata', 'tata_lux', 'amazon', or 'pipeline'")
    parser.add_argument("--scrapers", type=str, default=None, help="Comma-separated scrapers e.g. 'columbia,adv,tata,tata_lux,amazon' or 'all'")
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
                selected = [s.strip() for s in scrapers_arg.split(",") if s.strip() and s.strip().lower() != "myntra"]
            from jobs import create_job
            job = await create_job(scrapers=selected, force=args.force)
            await run_sequential_pipeline(job["job_id"], selected_scrapers=selected, limit=args.limit, force=args.force)
        elif target_arg:
            target = target_arg.lower()
            if target in ("pipeline", "all"):
                from jobs import create_job
                job = await create_job(force=args.force)
                await run_sequential_pipeline(job["job_id"], limit=args.limit, force=args.force)
            elif target in ("tata_lux", "tatalux", "tatacliq_luxury", "lux"):
                await scrape_tata_lux(limit=args.limit)
            elif target in ("tata", "tatacliq"):
                await scrape_tata(limit=args.limit)
            elif target in ("adv", "adventuras"):
                await scrape_adv(limit=args.limit)
            elif target in ("amazon", "amz"):
                await scrape_amazon(limit=args.limit)
            elif target in ("myntra",):
                print("[RUNNER] ⚠️ Myntra scraper is disabled to preserve RAM. Skipping.", flush=True)
                return
            else:
                await scrape_columbia(limit=args.limit)
        else:
            await scrape_columbia(limit=args.limit)
    finally:
        await close_shared_browser()


if __name__ == "__main__":
    asyncio.run(_run_cli())
