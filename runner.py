import asyncio
import json
import os
import sys
import time
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
    (images, fonts, stylesheets, media, tracking scripts are aborted)
    to minimize memory usage on constrained servers.
    """
    global _ACTIVE_PAGE
    # Ensure any lingering previous page is closed first
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

    # Abort heavy assets that are completely unnecessary for API data scraping
    async def block_unnecessary_resources(route):
        req = route.request
        res_type = req.resource_type
        url_lower = req.url.lower()

        # 1. Block heavy binary & styling assets (images, fonts, media, css)
        if res_type in ("image", "media", "font", "stylesheet"):
            await route.abort()
            return

        # 2. Block heavy advertising, analytics, and telemetry trackers
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
    callback = None
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
# Columbia Sportswear Scraper
# =========================================================================

async def scrape_columbia(progress_callback=None) -> dict:
    """Scrapes Columbia Sportswear India product data using the shared browser."""
    if not TOKEN:
        raise RuntimeError("SHOPIFY_TOKEN is missing from .env or environment")

    scraper_path = Path("columbia_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

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
            return output_payload

        finally:
            if page:
                print("[BROWSER] Closing Columbia tab to reclaim RAM...", flush=True)
                try:
                    await page.close()
                except Exception:
                    pass
                global _ACTIVE_PAGE
                _ACTIVE_PAGE = None
                print("[BROWSER] Columbia tab destroyed. Browser ready for next scraper.", flush=True)


# =========================================================================
# Tata CLiQ Scraper
# =========================================================================

async def scrape_tata(progress_callback=None) -> dict:
    """Scrapes Tata CLiQ for Columbia products on the same shared browser (concurrency=2)."""
    scraper_path = Path("tata_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    # Timeout for full Tata scrape (default 3600s / 60 mins)
    timeout_ms = int(os.getenv("TATA_SCRAPE_TIMEOUT_SECONDS", "3600")) * 1000

    async with _SCRAPER_LOCK:
        browser = await get_shared_browser()
        page = None
        try:
            print("Opening lean tab for Tata CLiQ scraper (on shared browser)...", flush=True)
            page = await _create_lean_tab(browser, "https://www.tatacliq.com/")

            print("Injecting and starting Tata CLiQ scraper (CONCURRENCY=2)...", flush=True)
            await page.evaluate(
                """([code]) => {
                    window.__IS_PLAYWRIGHT__ = true;
                    window.__CONCURRENCY__ = 2;
                    window.eval(code);
                }""",
                [scraper_code]
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

            if not result or not isinstance(result, dict):
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
            return result

        finally:
            if page:
                print("[BROWSER] Closing Tata CLiQ tab to reclaim RAM...", flush=True)
                try:
                    await page.close()
                except Exception:
                    pass
                _ACTIVE_PAGE = None
                print("[BROWSER] Tata CLiQ tab destroyed. Memory reclaimed.", flush=True)


# =========================================================================
# Sequential Pipeline Coordinator (Columbia -> Tata CLiQ)
# =========================================================================

async def run_sequential_pipeline(job_id: str):
    """
    Coordinates sequential execution of Columbia -> Tata CLiQ with live job status updates.
    Guarantees strict tab lifecycle and memory reclamation.
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
        overall_pct = round(pct * 0.15, 1)  # Columbia represents first 15% of pipeline
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
        pct = (curr / tot) if tot > 0 else 0.0

        if "Listing" in stage or "Collecting Products" in stage:
            overall_pct = round(15.0 + (pct * 15.0), 1)  # 15% - 30%
        else:
            overall_pct = round(30.0 + (pct * 70.0), 1)  # 30% - 100%

        await update_job(
            job_id,
            progress_percentage=min(99.0, overall_pct),
            scrapers={
                "tatacliq": {
                    "stage": stage,
                    "current": curr,
                    "total": tot,
                }
            }
        )

    t_pipeline_start = time.perf_counter()
    col_products = 0

    # Step 1: Columbia Scraper
    try:
        t0 = time.perf_counter()
        columbia_res = await scrape_columbia(progress_callback=columbia_progress_cb)
        col_dur = round(time.perf_counter() - t0, 1)
        col_products = len(columbia_res.get("products", []))

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
        tata_res = await scrape_tata(progress_callback=tata_progress_cb)
        tata_dur = round(time.perf_counter() - t0, 1)
        tata_products = tata_res.get("total_products", len(tata_res.get("products", [])))
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


# Backwards compatibility
main = scrape_columbia


async def _run_cli(target: str):
    try:
        if target.lower() in ("tata", "tatacliq"):
            await scrape_tata()
        elif target.lower() in ("pipeline", "all"):
            from jobs import create_job
            job = await create_job()
            await run_sequential_pipeline(job["job_id"])
        else:
            await scrape_columbia()
    finally:
        await close_shared_browser()


if __name__ == "__main__":
    target_arg = sys.argv[1] if len(sys.argv) > 1 else "columbia"
    asyncio.run(_run_cli(target_arg))
