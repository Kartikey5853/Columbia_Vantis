import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

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

from jobs import (
    create_job,
    get_job,
    get_active_job,
    is_pipeline_running,
    set_pipeline_task,
    find_orphaned_job,
    request_stop,
    clear_stop_flag,
    is_stop_requested,
    get_stop_reason,
    stop_active_pipeline,
    track_boot_trigger,
    reset_boot_tracker
)
from runner import (
    scrape_columbia,
    scrape_adv,
    scrape_tata,
    run_sequential_pipeline,
    close_shared_browser,
    stop_current_scraper
)
from persistence import (
    get_all_canonical_products,
    get_database_storage_stats,
)


app = FastAPI(
    title="Product Scraper API",
    description="Unified asynchronous web scraper API for Columbia Sportswear India and Tata CLiQ with Supabase persistence.",
    version="3.1.0"
)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.auth import router as auth_router
from app.api.products import router as products_router
from app.api.analytics import router as analytics_router
from app.api.master_data import router as master_data_router
from app.api.system import router as system_router
from app.services.catalog_service import catalog_service

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(analytics_router)
app.include_router(master_data_router)
app.include_router(system_router)

@app.get("/healthz")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Columbia VANTIS Intelligence API",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected"
    }


def _format_product_payload(source: str, raw_products: list) -> dict:
    """Ensure consistent schema_version and dual field compatibility (product_id + price)."""
    normalized = []
    for p in raw_products:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("product_id") or p.get("source_product_id") or "").strip()
        price = p.get("price") if p.get("price") is not None else p.get("current_price")
        mrp = p.get("mrp") if p.get("mrp") is not None else p.get("current_mrp")
        item = dict(p)
        item["product_id"] = pid
        item["price"] = price
        item["mrp"] = mrp
        normalized.append(item)

    return {
        "schema_version": 1,
        "source": source,
        "total_products": len(normalized),
        "products": normalized
    }


from persistence.run_store import (
    get_daily_scrapers_summary,
    is_scraper_completed_today,
    get_business_date,
    get_daily_run_report,
    get_all_daily_reports,
    reset_daily_scrapers
)
from persistence.exporter import export_canonical_backup


async def check_and_trigger_scrapers(force: bool = False, wait_seconds: int = 0) -> Dict[str, Any]:
    """
    Core auto-trigger logic:
    1. Checks today's date in database (Asia/Kolkata timezone).
    2. Inspects status of all scrapers (columbia, adv, tata, tata_lux, amazon).
    3. If all scrapers are completed with valid data and not force -> returns already_completed.
    4. If pipeline is already running -> returns already_running with active job.
    5. If any scraper failed, was interrupted, or has not run -> starts sequential queue scraper in background.
    6. If wait_seconds > 0, waits up to wait_seconds before returning current status.
    """
    b_date = get_business_date()
    print(f"\n[DEPLOY/STARTUP TRIGGER] 🔍 Checking database scraper status for business date: {b_date}...", flush=True)

    try:
        summary = await get_daily_scrapers_summary(business_date=b_date)
    except Exception as e:
        print(f"[DEPLOY/STARTUP TRIGGER] Warning: Failed to query daily scrapers summary: {e}", flush=True)
        summary = {}

    canonical_order = ["columbia", "adv", "tata", "tata_lux", "amazon"]
    pending_scrapers = []
    completed_scrapers = []

    if force:
        clear_stop_flag()
        reset_boot_tracker()
    else:
        if is_stop_requested():
            reason = get_stop_reason()
            msg = f"Startup auto-trigger suppressed because scraper was manually stopped today ({reason}). Use POST /scrape or /deploy-trigger?force=true to restart."
            print(f"[DEPLOY/STARTUP TRIGGER] 🛑 {msg}\n", flush=True)
            return {
                "status": "stopped_by_user",
                "business_date": b_date,
                "message": msg,
                "completed_scrapers": [],
                "pending_scrapers": canonical_order,
            }

        if not track_boot_trigger(max_retries=3):
            msg = "Crash loop guard: Server auto-triggered 3 times today without finishing. Auto-trigger paused to prevent crash loops. Trigger manually via Swagger /scrape to resume."
            print(f"[DEPLOY/STARTUP TRIGGER] ⚠️ {msg}\n", flush=True)
            return {
                "status": "crash_guard_paused",
                "business_date": b_date,
                "message": msg,
                "completed_scrapers": [],
                "pending_scrapers": canonical_order,
            }

    for name in canonical_order:
        s_data = summary.get(name, {})
        status = s_data.get("status")
        prods = s_data.get("completed_products", 0)

        backup_path = Path(f"data/{name}/{name}_data.json")
        if not force and status == "completed" and prods > 0:
            if name in ("tata", "tata_lux") and (s_data.get("total_variants", 0) or 0) < 100:
                pending_scrapers.append(name)
            else:
                completed_scrapers.append(name)
                if not backup_path.exists():
                    try:
                        await export_canonical_backup(name)
                    except Exception:
                        pass
        else:
            pending_scrapers.append(name)

    print(f"[DEPLOY/STARTUP TRIGGER] Daily status: Completed: {completed_scrapers} | Pending/Incomplete: {pending_scrapers}", flush=True)

    if not pending_scrapers:
        msg = f"All {len(canonical_order)} scrapers for today ({b_date}) are already completed. No scraping needed."
        print(f"[DEPLOY/STARTUP TRIGGER] ✅ {msg}\n", flush=True)
        return {
            "status": "already_completed",
            "business_date": b_date,
            "message": msg,
            "completed_scrapers": completed_scrapers,
            "summary": summary
        }

    if is_pipeline_running():
        active = await get_active_job()
        job_id = active["job_id"] if active else None
        if wait_seconds > 0 and job_id:
            wait_task = get_pipeline_task()
            if wait_task:
                try:
                    await asyncio.wait_for(asyncio.shield(wait_task), timeout=wait_seconds)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass
            job_status = await get_job(job_id)
            if job_status:
                return job_status
        msg = f"Scraper pipeline is already running (Job: {job_id if job_id else 'unknown'})."
        print(f"[DEPLOY/STARTUP TRIGGER] ⚠️ {msg}\n", flush=True)
        return {
            "status": "already_running",
            "business_date": b_date,
            "message": msg,
            "active_job": active
        }

    orphaned = find_orphaned_job()
    job_id = orphaned["job_id"] if (orphaned and not force) else None

    if not job_id:
        from jobs import create_job
        job = await create_job(scrapers=pending_scrapers, force=force)
        job_id = job["job_id"]

    print(f"[DEPLOY/STARTUP TRIGGER] 🔄 Auto-triggering incomplete scrapers for today ({b_date}): {pending_scrapers} (Job: {job_id}). Dispatching in background...\n", flush=True)
    task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=pending_scrapers, force=force))
    set_pipeline_task(task)

    if wait_seconds > 0:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    current_job_data = await get_job(job_id)
    if current_job_data:
        return current_job_data

    return {
        "status": "triggered",
        "job_id": job_id,
        "business_date": b_date,
        "message": f"Started background queue scraper for: {', '.join(pending_scrapers)}",
        "pending_scrapers": pending_scrapers,
        "completed_scrapers": completed_scrapers,
        "status_url": f"/scrape/status/{job_id}"
    }


import httpx

keepalive_task: Optional[asyncio.Task] = None


async def _render_keepalive_loop():
    """
    Background keepalive loop for Render free tier.
    Pings the public service URL every 3 minutes (180s) ONLY when a scraper pipeline is active.
    This generates incoming HTTP requests to Render's routing layer, preventing inactivity spin-down.
    """
    keepalive_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SERVER_URL")
    if keepalive_url:
        keepalive_url = keepalive_url.rstrip("/")
        if not keepalive_url.startswith("http"):
            keepalive_url = f"https://{keepalive_url}"
        target_endpoint = f"{keepalive_url}/health"
    else:
        target_endpoint = None

    if not target_endpoint:
        print("[KEEPALIVE] Note: Neither RENDER_EXTERNAL_URL nor SERVER_URL is set. Self-ping will be skipped until set.", flush=True)
    else:
        print(f"[KEEPALIVE] Initialized keepalive self-ping targeting: {target_endpoint} (interval: 180s when pipeline running)", flush=True)

    while True:
        try:
            await asyncio.sleep(180)  # Ping every 3 minutes
            if is_pipeline_running():
                current_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SERVER_URL")
                if current_url:
                    current_url = current_url.rstrip("/")
                    if not current_url.startswith("http"):
                        current_url = f"https://{current_url}"
                    ping_target = f"{current_url}/health"
                    try:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            resp = await client.get(ping_target)
                            print(f"[KEEPALIVE] 🏓 Pinged {ping_target} -> Status {resp.status_code} (pipeline active)", flush=True)
                    except Exception as ping_err:
                        print(f"[KEEPALIVE] ⚠️ Ping attempt to {ping_target} failed: {ping_err}", flush=True)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[KEEPALIVE] Error in keepalive loop: {e}", flush=True)


@app.on_event("startup")
async def on_startup():
    """
    Server startup hook.
    Automatic background scraping on boot is disabled to prevent unwanted scrapes/OOM.
    Starts background keepalive loop to keep Render awake during active jobs.
    """
    global keepalive_task
    print("[STARTUP] Server started. Automatic startup scraping is disabled.", flush=True)
    asyncio.create_task(asyncio.to_thread(catalog_service.load_catalog))
    if keepalive_task is None or keepalive_task.done():
        keepalive_task = asyncio.create_task(_render_keepalive_loop())


@app.on_event("shutdown")
async def on_shutdown():
    global keepalive_task
    if keepalive_task and not keepalive_task.done():
        keepalive_task.cancel()
    await close_shared_browser()


@app.get("/health")
async def health_check():
    """
    Immediate liveness and health check endpoint.
    Returns 200 OK immediately without triggering any scraping operations.
    """
    return {
        "status": "healthy",
        "service": "Product Scraper API",
        "pipeline_running": is_pipeline_running()
    }


@app.get("/")
async def root():
    active = await get_active_job()
    b_date = get_business_date()
    return {
        "status": "online",
        "service": "Product Scraper API",
        "business_date": b_date,
        "architecture": "unified_supabase_persistence",
        "active_job": active["job_id"] if active else None,
        "pipeline_running": is_pipeline_running(),
        "endpoints": {
            "health": "GET /health",
            "deploy_trigger": "POST /deploy-trigger (or GET /deploy-trigger)",
            "stop_pipeline": "POST /scrape/stop (or GET /scrape/stop)",
            "reset_scrapers": "POST /scrape/reset (or GET /scrape/reset, /scrape/reset/{scraper}, /scrape/{scraper}/reset)",
            "trigger_job": "POST /scrape?scrapers=columbia,adv,tata,tata_lux,amazon",
            "check_status": "GET /scrape/status/{job_id}",
            "active_status": "GET /scrape/status",
            "daily_reports": "GET /scrape/report",
            "columbia_products": "GET /scrape (or GET /scrape/columbia)",
            "adv_products": "GET /scrape/adv",
            "tata_products": "GET /scrape/tata",
            "tata_lux_products": "GET /scrape/tata_lux",
            "amazon_products": "GET /scrape/amazon",
            "variants": "GET /scrape/{scraper}/variants (e.g. /scrape/amazon/variants)",
            "db_diagnostics": "GET /db/diagnostics"
        }
    }


@app.post("/scrape/stop", tags=["Scraper Pipeline"])
@app.get("/scrape/stop", tags=["Scraper Pipeline"])
async def stop_pipeline_endpoint(
    reason: str = Query("Stopped by user request via API / Swagger", description="Reason for stopping the active scraper")
):
    """
    🛑 EMERGENCY STOP SWITCH:
    Immediately halts the currently executing scraper pipeline.
    Cancels background execution tasks, aborts active browser pages,
    marks active jobs and Supabase runs as stopped,
    and suppresses automatic startup restart loops.
    """
    await stop_current_scraper(reason=reason)
    res = await stop_active_pipeline(reason=reason)
    return JSONResponse(status_code=200, content=res)


@app.post("/scrape/reset", tags=["Scraper Pipeline"])
@app.get("/scrape/reset", tags=["Scraper Pipeline"])
async def reset_scrapers_endpoint(
    scrapers: str = Query("all", description="Comma-separated scrapers to reset e.g. 'all', 'amazon', or 'columbia,adv,tata,tata_lux,amazon'"),
    business_date: Optional[str] = Query(None, description="Business date to reset (YYYY-MM-DD), defaults to today")
):
    """
    🔄 DAILY RESET SWITCH:
    Resets all or selected scrapers for the specified business date.
    Clears page checkpoints in scrape_listing_pages and progress in scrape_product_progress,
    resets scrape_runs to queued, clears stop flags and crash guards,
    allowing a completely fresh scrape from page 1.
    """
    b_date = business_date or get_business_date()
    target_list = [s.strip() for s in (scrapers or "all").split(",") if s.strip()]

    # Clear stop flags and reboot guards
    clear_stop_flag()
    reset_boot_tracker()

    res = await reset_daily_scrapers(scrapers=target_list, business_date=b_date)
    return JSONResponse(
        status_code=200,
        content={
            "status": "reset_completed",
            "business_date": b_date,
            "message": f"Successfully reset scrapers for {b_date}. All checkpoints cleared. Ready to scrape again from page 1.",
            "details": res
        }
    )


@app.post("/scrape/reset/{scraper}", tags=["Scraper Pipeline"])
@app.get("/scrape/reset/{scraper}", tags=["Scraper Pipeline"])
@app.post("/scrape/{scraper}/reset", tags=["Scraper Pipeline"])
@app.get("/scrape/{scraper}/reset", tags=["Scraper Pipeline"])
async def reset_single_scraper_endpoint(
    scraper: str,
    business_date: Optional[str] = Query(None, description="Business date to reset (YYYY-MM-DD), defaults to today")
):
    """
    🔄 RESET SINGLE SCRAPER:
    Convenience endpoint variant to reset a single scraper directly (e.g. /scrape/reset/amazon or /scrape/amazon/reset).
    """
    return await reset_scrapers_endpoint(scrapers=scraper, business_date=business_date)



@app.post("/deploy-trigger")
@app.post("/trigger")
@app.post("/scrape/trigger")
async def deploy_trigger_endpoint_post(
    force: bool = Query(True, description="Force run even if already completed today"),
    wait_seconds: int = Query(0, ge=0, description="Optional seconds to wait before returning status")
):
    """
    Trigger pipeline explicitly via POST request (defaults to force=True).
    Executes sequential queue scraper in background and returns HTTP 202.
    """
    res = await check_and_trigger_scrapers(force=force, wait_seconds=wait_seconds)
    status_code = 200 if res.get("status") in ("already_completed", "already_running") else 202
    return JSONResponse(status_code=status_code, content=res)


@app.get("/deploy-trigger")
@app.get("/trigger")
async def deploy_trigger_endpoint_get(
    force: bool = Query(False, description="Force run even if already completed today"),
    wait_seconds: int = Query(0, ge=0, description="Optional seconds to wait before returning status")
):
    """
    GET probe endpoint for deployment or wakeup status check.
    Pass ?force=true to trigger scraping via GET.
    """
    if not force:
        b_date = get_business_date()
        summary = await get_daily_scrapers_summary(business_date=b_date)
        return JSONResponse(
            status_code=200,
            content={
                "status": "idle",
                "business_date": b_date,
                "message": "Deployment trigger status probe. Send POST /deploy-trigger or pass ?force=true to trigger pipeline.",
                "summary": summary,
            }
        )
    res = await check_and_trigger_scrapers(force=force, wait_seconds=wait_seconds)
    status_code = 200 if res.get("status") in ("already_completed", "already_running") else 202
    return JSONResponse(status_code=status_code, content=res)


@app.get("/scrape/report")
async def get_daily_reports_endpoint():
    """Returns today's comprehensive scrape run reports from Supabase database."""
    b_date = get_business_date()
    reports = await get_all_daily_reports(business_date=b_date)
    return reports


@app.get("/scrape/report/{scraper}")
async def get_scraper_report_endpoint(scraper: str):
    """Returns the latest JSON report for a specific scraper from Supabase scrape_runs."""
    alias_map = {
        "columbiasportswear": "columbia",
        "adventuras": "adv",
        "tatacliq": "tata",
        "tatalux": "tata_lux",
        "tatacliq_luxury": "tata_lux",
        "lux": "tata_lux",
        "amazon": "amazon",
    }
    norm_name = alias_map.get(scraper.lower(), scraper.lower())
    rep = await get_daily_run_report(norm_name)
    if not rep:
        return JSONResponse(
            status_code=404,
            content={"error": f"No report found for scraper '{scraper}'"}
        )
    return rep


@app.post("/scrape", status_code=202)
async def trigger_scrape_job(
    scrapers: str = Query("columbia,adv,tata,tata_lux,amazon", description="Comma-separated list of scrapers to run (columbia, adv, tata, tata_lux, amazon)"),
    limit: int = Query(None, description="Optional product limit for testing"),
    force: bool = Query(False, description="Force start a new job even if an interrupted job exists or if scrapers already completed today"),
    wait_seconds: int = Query(0, ge=0, description="Optional seconds to wait before returning status (default 0 returns immediately with 202 and job_id)")
):
    """
    Triggers the sequential scraping pipeline in the background.
    Supports selective execution (e.g., scrapers=amazon or scrapers=columbia,adv).
    Executes scrapers in strictly sequential order: Columbia -> Adventuras -> Tata CLiQ -> Tata CLiQ Luxury -> Amazon.
    If force=False and scrapers are already completed today, skips them.
    Automatically resumes interrupted jobs across server restarts unless force=true.
    Immediately returns HTTP 202 Accepted with a unique job_id (or waits if wait_seconds > 0).
    """
    selected = [s.strip() for s in (scrapers or "").split(",") if s.strip()]
    if not selected:
        selected = ["columbia", "adv", "tata", "tata_lux", "amazon"]

    alias_map = {
        "columbiasportswear": "columbia",
        "adventuras": "adv",
        "tatacliq": "tata",
        "tatalux": "tata_lux",
        "tatacliq_luxury": "tata_lux",
        "lux": "tata_lux",
        "amazon": "amazon",
    }
    selected = [alias_map.get(s.lower(), s.lower()) for s in selected]
    canonical_order = ["columbia", "adv", "tata", "tata_lux", "amazon"]
    ordered_selected = [s for s in canonical_order if s in selected] or canonical_order

    clear_stop_flag()
    if force:
        reset_boot_tracker()

    # If force=False, filter out scrapers that are already completed today
    if not force:
        b_date = get_business_date()
        daily_summary = await get_daily_scrapers_summary(business_date=b_date)
        needed_scrapers = []
        already_done = []
        for s in ordered_selected:
            s_info = daily_summary.get(s, {})
            if s_info.get("status") == "completed" and (s_info.get("completed_products", 0) > 0 or limit):
                already_done.append(s)
            else:
                needed_scrapers.append(s)

        if not needed_scrapers:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "already_completed",
                    "business_date": b_date,
                    "message": f"All requested scrapers ({', '.join(already_done)}) are already completed for today ({b_date}). No scraping needed.",
                    "scrapers": already_done,
                    "summary": daily_summary,
                }
            )
        ordered_selected = needed_scrapers

    if is_pipeline_running():
        active = await get_active_job()
        job_id = active["job_id"] if active else None
        if wait_seconds > 0 and job_id:
            wait_task = get_pipeline_task()
            if wait_task:
                try:
                    await asyncio.wait_for(asyncio.shield(wait_task), timeout=wait_seconds)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass
            job_status = await get_job(job_id)
            status_code = 200 if job_status and job_status.get("status") in ("completed", "failed") else 202
            return JSONResponse(
                status_code=status_code,
                content=job_status or {
                    "status": "conflict",
                    "message": "A scrape job is already currently running",
                    "active_job": active,
                    "status_url": f"/scrape/status/{job_id}"
                }
            )
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "message": "A scrape job is already currently running",
                "active_job": active,
                "status_url": f"/scrape/status/{job_id}" if job_id else None
            }
        )

    # Check for orphaned job from prior server shutdown/crash
    orphaned = find_orphaned_job()
    if orphaned and not force:
        job_id = orphaned["job_id"]
        print(f"[API] 🔄 Resuming interrupted job {job_id} in background...", flush=True)
        task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=ordered_selected, limit=limit, force=force))
        set_pipeline_task(task)
    else:
        job = await create_job(scrapers=ordered_selected, force=force)
        job_id = job["job_id"]
        # Dispatch pipeline in background task
        task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=ordered_selected, limit=limit, force=force))
        set_pipeline_task(task)

    # If wait_seconds > 0, wait up to wait_seconds before returning so incoming caller stays connected / server stays alive
    if wait_seconds > 0:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    current_job_data = await get_job(job_id)
    if current_job_data:
        status_code = 200 if current_job_data.get("status") in ("completed", "failed") else 202
        return JSONResponse(
            status_code=status_code,
            content=current_job_data
        )

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "scrapers": ordered_selected,
            "limit": limit,
            "message": f"Scraper job started in background (Sequence: {' -> '.join(ordered_selected)})",
            "status_url": f"/scrape/status/{job_id}"
        }
    )


@app.get("/scrape/status/{job_id}")
async def get_scrape_status(job_id: str):
    job = await get_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found"}
        )
    return job


@app.get("/scrape/status")
async def get_latest_scrape_status():
    active = await get_active_job()
    if active:
        return active

    b_date = get_business_date()
    daily_summary = await get_daily_scrapers_summary(business_date=b_date)
    all_completed = all(v.get("status") == "completed" for v in daily_summary.values())
    total_prods = sum(v.get("completed_products", 0) for v in daily_summary.values())

    return {
        "status": "completed" if all_completed else "idle",
        "business_date": b_date,
        "product_count": total_prods,
        "pipeline_running": is_pipeline_running(),
        "scrapers": daily_summary,
        "message": "Today's scraping completed" if all_completed else "No active scrape job currently running"
    }


@app.get("/scrape")
async def get_columbia_data():
    """
    Returns canonical Columbia products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("columbia")
        if prods:
            return _format_product_payload("columbia", prods)
    except Exception:
        pass

    backup_file = Path("data/columbia/columbia_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("columbia", data.get("products", []))
        except Exception:
            pass

    # Legacy fallback
    legacy_file = Path("columbia_products.json")
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            prods = data.get("products", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return _format_product_payload("columbia", prods)
        except Exception:
            pass

    return _format_product_payload("columbia", [])


@app.get("/scrape/columbia")
async def get_columbia_data_alias():
    """Alias for /scrape returning canonical Columbia products."""
    return await get_columbia_data()


@app.get("/scrape/adv")
async def get_adv_data():
    """
    Returns canonical Adventuras products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("adv")
        if prods:
            return _format_product_payload("adv", prods)
    except Exception:
        pass

    backup_file = Path("data/adv/adv_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("adv", data.get("products", []))
        except Exception:
            pass

    return _format_product_payload("adv", [])





@app.get("/scrape/tata")
async def get_tata_data():
    """
    Returns canonical Tata CLiQ products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("tata")
        if prods:
            return _format_product_payload("tata", prods)
    except Exception:
        pass

    backup_file = Path("data/tata/tata_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("tata", data.get("products", []))
        except Exception:
            pass

    legacy_file = Path("tatacliq_columbia_products.json")
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            prods = data.get("products", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return _format_product_payload("tata", prods)
        except Exception:
            pass

    return _format_product_payload("tata", [])


@app.get("/scrape/tata_lux")
@app.get("/scrape/tatalux")
@app.get("/scrape/lux")
async def get_tata_lux_data():
    """
    Returns canonical Tata CLiQ Luxury products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("tata_lux")
        if prods:
            return _format_product_payload("tata_lux", prods)
    except Exception:
        pass

    backup_file = Path("data/tata_lux/tata_lux_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("tata_lux", data.get("products", []))
        except Exception:
            pass

    legacy_file = Path("tata_lux_columbia_products.json")
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            prods = data.get("products", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return _format_product_payload("tata_lux", prods)
        except Exception:
            pass

    return _format_product_payload("tata_lux", [])


@app.get("/scrape/amazon")
async def get_amazon_data():
    """
    Returns canonical Amazon products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("amazon")
        if prods:
            return _format_product_payload("amazon", prods)
    except Exception:
        pass

    backup_file = Path("data/amazon/amazon_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("amazon", data.get("products", []))
        except Exception:
            pass

    b_date = get_business_date()
    dated_file = Path(f"data/amazon/{b_date}.json")
    if dated_file.exists():
        try:
            data = json.loads(dated_file.read_text(encoding="utf-8"))
            return _format_product_payload("amazon", data.get("products", []))
        except Exception:
            pass

    legacy_file = Path("amazon_products.json")
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            prods = data.get("products", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return _format_product_payload("amazon", prods)
        except Exception:
            pass

    return _format_product_payload("amazon", [])


@app.get("/scrape/{scraper}/variants")
async def get_scraper_variants(scraper: str):
    """
    Returns all product variants for a given scraper (e.g. columbia, adv, tata, tata_lux, amazon).
    Flattens variants with their associated parent product details, SKU, size, price, and availability.
    """
    alias_map = {
        "columbiasportswear": "columbia",
        "adventuras": "adv",
        "tatacliq": "tata",
        "tatalux": "tata_lux",
        "tatacliq_luxury": "tata_lux",
        "lux": "tata_lux",
        "amazon": "amazon",
    }
    norm_name = alias_map.get(scraper.lower(), scraper.lower())

    # Dispatch to specific product retriever
    if norm_name == "columbia":
        prod_resp = await get_columbia_data()
    elif norm_name == "adv":
        prod_resp = await get_adv_data()
    elif norm_name == "tata":
        prod_resp = await get_tata_data()
    elif norm_name == "tata_lux":
        prod_resp = await get_tata_lux_data()
    elif norm_name == "amazon":
        prod_resp = await get_amazon_data()
    else:
        return JSONResponse(status_code=404, content={"error": f"Unknown scraper '{scraper}'"})

    prods = prod_resp.get("products", []) if isinstance(prod_resp, dict) else []
    flattened_variants = []

    for p in prods:
        pid = p.get("product_id") or p.get("source_product_id") or ""
        p_title = p.get("title") or ""
        p_price = p.get("price") if p.get("price") is not None else p.get("current_price")
        p_mrp = p.get("mrp") if p.get("mrp") is not None else p.get("current_mrp")
        p_url = p.get("url") or ""

        raw_variants = p.get("variants") or []
        if isinstance(raw_variants, list) and raw_variants:
            for v in raw_variants:
                if not isinstance(v, dict):
                    continue
                v_price = v.get("price") if v.get("price") is not None else p_price
                v_mrp = v.get("mrp") if v.get("mrp") is not None else p_mrp
                flattened_variants.append({
                    "scraper": norm_name,
                    "product_id": pid,
                    "title": p_title,
                    "sku": v.get("sku") or pid,
                    "size": v.get("size") or "",
                    "ean": v.get("ean"),
                    "price": v_price,
                    "mrp": v_mrp,
                    "available": v.get("available", True),
                    "url": v.get("url") or p_url,
                })
        else:
            # Standalone single-variant fallback
            flattened_variants.append({
                "scraper": norm_name,
                "product_id": pid,
                "title": p_title,
                "sku": p.get("sku") or pid,
                "size": "",
                "ean": p.get("ean"),
                "price": p_price,
                "mrp": p_mrp,
                "available": p.get("available", True),
                "url": p_url,
            })

    return {
        "schema_version": 1,
        "source": norm_name,
        "total_products": len(prods),
        "total_variants": len(flattened_variants),
        "variants": flattened_variants
    }



@app.get("/db/diagnostics")
async def get_db_diagnostics():
    """Returns real storage measurements and row counts from Supabase."""
    return await get_database_storage_stats()
