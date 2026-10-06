import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
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

    page = await browser.new_page()
    _ACTIVE_PAGE = page

    page.on("console", log_console)
    page.on("pageerror", lambda exc: print(f"[PAGE ERROR] {exc}", flush=True))

    async def block_unnecessary_resources(route):
        req = route.request
        res_type = req.resource_type
        url_lower = req.url.lower()

        if res_type in ("image", "media", "font", "stylesheet"):
            await route.abort()
            return

        tracker_keywords = (
            "google-analytics", "googletagmanager", "facebook", "doubleclick",
            "clarity.ms", "criteo", "hotjar", "omtrdc", "demdex", "tiqcdn",
            "branch.io", "scorecardresearch", "adroll", "datadog", "newrelic",
            "sentry", "shopifyanalytics"
        )
        if any(kw in url_lower for kw in tracker_keywords):
            await route.abort()
            return

        await route.continue_()

    await page.route("**/*", block_unnecessary_resources)

    print(f"[BROWSER] Navigating single tab to {url} (images/styles blocked)...", flush=True)
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
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

    scraper_path = Path("columbia_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    raw_products = []
    async with _SCRAPER_LOCK:
        browser = await get_shared_browser()
        page = None
        try:
            print("Opening lean tab for Columbia scraper...", flush=True)
            page = await _create_lean_tab(browser, "https://www.columbiasportswear.co.in/")

            print("Injecting and starting Columbia scraper...", flush=True)
            await page.evaluate(
                """([code, token]) => {
                    window.__SHOPIFY_TOKEN__ = token;
                    window.__IS_PLAYWRIGHT__ = true;
                    window.eval(code);
                }""",
                [scraper_code, TOKEN]
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

            raw_products = await page.evaluate("() => window.output || []")

        finally:
            if page:
                print("[BROWSER] Closing Columbia tab to reclaim RAM...", flush=True)
                try:
                    await page.close()
                except Exception:
                    pass
                global _ACTIVE_PAGE
                _ACTIVE_PAGE = None
                print("[BROWSER] Columbia tab destroyed. Memory reclaimed.", flush=True)

    # 2. Normalize raw products into canonical product structures
    await update_run_stage(run_id, "products", client=cli)
    norm_products = group_columbia_products(raw_products)
    if limit:
        norm_products = norm_products[:limit]

    # 2. Batch Persist into Supabase in chunks of 500
    batch_size = 500
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
    scraper_path = Path("tata_scraper.js")
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
            if page:
                print("[BROWSER] Closing Tata CLiQ tab to reclaim RAM...", flush=True)
                try:
                    await page.close()
                except Exception:
                    pass
                _ACTIVE_PAGE = None
                print("[BROWSER] Tata CLiQ tab destroyed. Memory reclaimed.", flush=True)

    # 2. Batch Persist into Supabase in chunks of 500
    await update_run_stage(run_id, "variants", client=cli)
    if limit:
        raw_items = raw_items[:limit]

    norm_products = [normalize_tata_js_product(item) for item in raw_items]
    batch_size = 500
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
# Sequential Pipeline Coordinator (Columbia -> Tata CLiQ)
# =========================================================================

async def run_sequential_pipeline(job_id: str, limit: Optional[int] = None):
    """
    Coordinates sequential execution of Columbia -> Tata CLiQ with live job status updates
    and unified Supabase persistence.
    """
    from jobs import update_job

    await update_job(
        job_id,
        status="running",
        current_scraper="columbia",
        scrapers={"columbia": {"status": "running"}},
    )

    # Progress callback for Columbia
    async def columbia_progress_cb(prog: dict):
        curr = prog.get("current", 0)
        tot = prog.get("total", 1)
        pct = round((curr / tot) * 100, 1) if tot > 0 else 0.0
        overall_pct = round(pct * 0.15, 1)
        await update_job(
            job_id,
            progress_percentage=overall_pct,
            scrapers={
                "columbia": {
                    "stage": prog.get("stage", "Running"),
                    "current": curr,
                    "total": tot
                }
            }
        )

    # Progress callback for Tata CLiQ
    async def tata_progress_cb(prog: dict):
        stage = prog.get("stage", "")
        curr = prog.get("current", 0)
        tot = prog.get("total", 1)
        var_count = prog.get("variant_count", 0)
        pct = (curr / tot) if tot > 0 else 0.0

        if "Listing" in stage or "Collecting Products" in stage:
            overall_pct = round(15.0 + (pct * 15.0), 1)
        else:
            overall_pct = round(30.0 + (pct * 70.0), 1)

        tata_metrics = {
            "stage": stage,
            "current": curr,
            "total": tot,
        }
        kwargs = {
            "progress_percentage": min(99.0, overall_pct),
        }
        if var_count > 0:
            tata_metrics["variant_count"] = var_count
            kwargs["variant_count"] = var_count

        kwargs["scrapers"] = {"tatacliq": tata_metrics}
        await update_job(job_id, **kwargs)

    t_pipeline_start = time.perf_counter()
    col_products = 0

    # Check if Columbia scraper already completed in this job (e.g. on auto-resume after server restart)
    from jobs import get_job
    existing_job = await get_job(job_id)
    col_already_completed = (
        existing_job
        and existing_job.get("scrapers", {}).get("columbia", {}).get("status") == "completed"
    )

    if col_already_completed:
        col_products = existing_job.get("scrapers", {}).get("columbia", {}).get("product_count", 0)
        print(f"[JOB {job_id}] ⏩ Columbia scraper already completed ({col_products} products). Resuming straight to Tata CLiQ...", flush=True)
    else:
        # Step 1: Columbia Scraper
        try:
            t0 = time.perf_counter()
            columbia_res = await scrape_columbia(limit=limit, progress_callback=columbia_progress_cb)
            col_dur = round(time.perf_counter() - t0, 1)
            col_products = columbia_res.get("completed_products", len(columbia_res.get("products", [])))

            await update_job(
                job_id,
                product_count=col_products,
                progress_percentage=15.0,
                scrapers={
                    "columbia": {
                        "status": "completed",
                        "product_count": col_products,
                        "duration_seconds": col_dur,
                        "error": None
                    }
                }
            )
        except Exception as e:
            col_dur = round(time.perf_counter() - t_pipeline_start, 1)
            err_msg = f"Columbia scraper failed: {e}"
            print(f"[JOB {job_id}] ❌ {err_msg}", flush=True)
            await update_job(
                job_id,
                status="failed",
                current_scraper="columbia",
                error=err_msg,
                scrapers={
                    "columbia": {
                        "status": "failed",
                        "duration_seconds": col_dur,
                        "error": str(e)
                    },
                    "tatacliq": {
                        "status": "skipped",
                        "error": "Skipped due to Columbia failure (fail-fast)"
                    }
                }
            )
            return

    # Step 2: Tata CLiQ Scraper (Only executed if Columbia passed)
    await update_job(
        job_id,
        current_scraper="tatacliq",
        scrapers={"tatacliq": {"status": "running"}},
    )

    try:
        t0 = time.perf_counter()
        tata_res = await scrape_tata(limit=limit, progress_callback=tata_progress_cb)
        tata_dur = round(time.perf_counter() - t0, 1)
        tata_products = tata_res.get("completed_products", 0)
        tata_variants = tata_res.get("total_variants", 0)

        total_prods = col_products + tata_products
        await update_job(
            job_id,
            status="completed",
            current_scraper=None,
            progress_percentage=100.0,
            product_count=total_prods,
            variant_count=tata_variants,
            error=None,
            scrapers={
                "tatacliq": {
                    "status": "completed",
                    "product_count": tata_products,
                    "variant_count": tata_variants,
                    "duration_seconds": tata_dur,
                    "error": None
                }
            }
        )
        print(f"[JOB {job_id}] ✅ ALL SCRAPERS COMPLETED SUCCESSFULLY ({total_prods} products, {tata_variants} variants)", flush=True)

    except Exception as e:
        tata_dur = round(time.perf_counter() - t0, 1)
        err_msg = f"Tata CLiQ scraper failed: {e}"
        print(f"[JOB {job_id}] ❌ {err_msg}", flush=True)
        await update_job(
            job_id,
            status="failed",
            current_scraper="tatacliq",
            error=err_msg,
            scrapers={
                "tatacliq": {
                    "status": "failed",
                    "duration_seconds": tata_dur,
                    "error": str(e)
                }
            }
        )


main = scrape_columbia


async def _run_cli():
    parser = argparse.ArgumentParser(description="Unified Columbia & Tata Scraper Pipeline")
    parser.add_argument("target", nargs="?", default="columbia", help="Target scraper: 'columbia', 'tata', or 'pipeline'")
    parser.add_argument("--scraper", type=str, default=None, help="Scraper name: 'columbia', 'tata', or 'pipeline'")
    parser.add_argument("--limit", type=int, default=None, help="Product limit for test mode (applies to Tata)")
    args = parser.parse_args()

    target = (args.scraper or args.target).lower()

    try:
        if target in ("tata", "tatacliq"):
            await scrape_tata(limit=args.limit)
        elif target in ("pipeline", "all"):
            from jobs import create_job
            job = await create_job()
            await run_sequential_pipeline(job["job_id"], limit=args.limit)
        else:
            await scrape_columbia()
    finally:
        await close_shared_browser()


if __name__ == "__main__":
    asyncio.run(_run_cli())
