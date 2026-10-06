import asyncio
import json
import os
import sys
from pathlib import Path
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

from jobs import create_job, get_job, get_active_job, is_pipeline_running, set_pipeline_task, find_orphaned_job
from runner import scrape_columbia, scrape_tata, run_sequential_pipeline, close_shared_browser
from persistence import get_all_canonical_products, get_database_storage_stats


app = FastAPI(
    title="Product Scraper API",
    description="Unified asynchronous web scraper API for Columbia Sportswear India and Tata CLiQ with Supabase persistence.",
    version="3.1.0"
)


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


from persistence.run_store import get_daily_scrapers_summary, is_scraper_completed_today, get_business_date
from persistence.exporter import export_canonical_backup


@app.on_event("startup")
async def on_startup():
    """
    On server boot:
    1. Checks today's date in database (Asia/Kolkata timezone).
    2. Inspects status of all scrapers (columbia, adv, myntra, tata).
    3. If all scrapers are completed with valid data -> NO SCRAPING.
    4. If any scraper failed, was interrupted, or has not run -> automatically resumes only those incomplete scrapers.
    5. Ensures local rolling backup files exist (exports missing ones from Supabase).
    """
    b_date = get_business_date()
    print(f"\n[STARTUP] 🔍 Checking database scraper status for business date: {b_date}...", flush=True)

    try:
        summary = await get_daily_scrapers_summary(business_date=b_date)
    except Exception as e:
        print(f"[STARTUP] Warning: Failed to query daily scrapers summary: {e}", flush=True)
        summary = {}

    canonical_order = ["columbia", "adv", "myntra", "tata"]
    pending_scrapers = []
    completed_scrapers = []

    for name in canonical_order:
        s_data = summary.get(name, {})
        status = s_data.get("status")
        prods = s_data.get("completed_products", 0)

        backup_path = Path(f"data/{name}/{name}_data.json")
        if status == "completed" and prods > 0:
            completed_scrapers.append(name)
            if not backup_path.exists():
                try:
                    await export_canonical_backup(name)
                except Exception:
                    pass
        else:
            pending_scrapers.append(name)

    print(f"[STARTUP] Daily status: Completed: {completed_scrapers} | Pending/Incomplete: {pending_scrapers}", flush=True)

    if not pending_scrapers:
        print(f"[STARTUP] ✅ All {len(canonical_order)} scrapers for today ({b_date}) are already completed. No scraping needed.\n", flush=True)
        return

    # Check if there is an existing orphaned job
    orphaned = find_orphaned_job()
    job_id = orphaned["job_id"] if orphaned else None

    if not job_id:
        from jobs import create_job
        job = await create_job(scrapers=pending_scrapers, force=True)
        job_id = job["job_id"]

    print(f"[STARTUP] 🔄 Auto-resuming incomplete scrapers for today ({b_date}): {pending_scrapers} (Job: {job_id}). Dispatching in background...\n", flush=True)
    task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=pending_scrapers))
    set_pipeline_task(task)


@app.on_event("shutdown")
async def on_shutdown():
    await close_shared_browser()


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
            "trigger_job": "POST /scrape?scrapers=columbia,adv,myntra,tata",
            "check_status": "GET /scrape/status/{job_id}",
            "active_status": "GET /scrape/status",
            "columbia_products": "GET /scrape (or GET /scrape/columbia)",
            "adv_products": "GET /scrape/adv",
            "myntra_products": "GET /scrape/myntra",
            "tata_products": "GET /scrape/tata",
            "db_diagnostics": "GET /db/diagnostics"
        }
    }


@app.post("/scrape", status_code=202)
async def trigger_scrape_job(
    scrapers: str = Query("columbia,adv,myntra,tata", description="Comma-separated list of scrapers to run (columbia, adv, myntra, tata)"),
    limit: int = Query(None, description="Optional product limit for testing"),
    force: bool = Query(False, description="Force start a new job even if an interrupted job exists or if scrapers already completed today")
):
    """
    Triggers the sequential scraping pipeline in the background.
    Supports selective execution (e.g., scrapers=columbia,adv or scrapers=tata).
    Executes scrapers in strictly sequential order: Columbia -> Adventuras -> Myntra -> Tata CLiQ.
    If force=False and scrapers are already completed today, skips them.
    Automatically resumes interrupted jobs across server restarts unless force=true.
    Immediately returns HTTP 202 Accepted with a unique job_id.
    """
    selected = [s.strip() for s in (scrapers or "").split(",") if s.strip()]
    if not selected:
        selected = ["columbia", "adv", "myntra", "tata"]

    alias_map = {"columbiasportswear": "columbia", "adventuras": "adv", "tatacliq": "tata"}
    selected = [alias_map.get(s.lower(), s.lower()) for s in selected]
    canonical_order = ["columbia", "adv", "myntra", "tata"]
    ordered_selected = [s for s in canonical_order if s in selected] or canonical_order

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
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "message": "A scrape job is already currently running",
                "active_job": active,
                "status_url": f"/scrape/status/{active['job_id']}" if active else None
            }
        )

    # Check for orphaned job from prior server shutdown/crash
    orphaned = find_orphaned_job()
    if orphaned and not force:
        job_id = orphaned["job_id"]
        print(f"[API] 🔄 Resuming interrupted job {job_id} in background...", flush=True)
        task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=ordered_selected, limit=limit, force=force))
        set_pipeline_task(task)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "resumed",
                "scrapers": ordered_selected,
                "limit": limit,
                "message": f"Resumed interrupted scrape job {job_id} in background",
                "status_url": f"/scrape/status/{job_id}"
            }
        )

    job = await create_job(scrapers=ordered_selected, force=force)
    job_id = job["job_id"]

    # Dispatch pipeline in background task
    task = asyncio.create_task(run_sequential_pipeline(job_id, selected_scrapers=ordered_selected, limit=limit, force=force))
    set_pipeline_task(task)

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


@app.get("/scrape/myntra")
async def get_myntra_data():
    """
    Returns canonical Myntra products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("myntra")
        if prods:
            return _format_product_payload("myntra", prods)
    except Exception:
        pass

    backup_file = Path("data/myntra/myntra_data.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            return _format_product_payload("myntra", data.get("products", []))
        except Exception:
            pass

    return _format_product_payload("myntra", [])


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


@app.get("/db/diagnostics")
async def get_db_diagnostics():
    """Returns real storage measurements and row counts from Supabase."""
    return await get_database_storage_stats()
