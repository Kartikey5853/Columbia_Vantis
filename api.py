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


@app.on_event("startup")
async def on_startup():
    """Auto-resume any scrape job interrupted by a previous server restart/crash."""
    orphaned = find_orphaned_job()
    if orphaned:
        job_id = orphaned["job_id"]
        print(f"[STARTUP] 🔄 Interrupted scrape job detected: {job_id} (stage: {orphaned.get('current_scraper')}, progress: {orphaned.get('progress_percentage')}%). Auto-resuming pipeline in background...", flush=True)
        task = asyncio.create_task(run_sequential_pipeline(job_id))
        set_pipeline_task(task)


@app.on_event("shutdown")
async def on_shutdown():
    await close_shared_browser()


@app.get("/")
async def root():
    active = await get_active_job()
    return {
        "status": "online",
        "service": "Product Scraper API",
        "architecture": "unified_supabase_persistence",
        "active_job": active["job_id"] if active else None,
        "pipeline_running": is_pipeline_running(),
        "endpoints": {
            "trigger_job": "POST /scrape",
            "check_status": "GET /scrape/status/{job_id}",
            "active_status": "GET /scrape/status",
            "columbia_products": "GET /scrape",
            "tata_products": "GET /scrape/tata",
            "db_diagnostics": "GET /db/diagnostics"
        }
    }


@app.post("/scrape", status_code=202)
async def trigger_scrape_job(
    limit: int = Query(None, description="Optional product limit for testing"),
    force: bool = Query(False, description="Force start a new job even if an interrupted job exists")
):
    """
    Triggers the sequential scraping pipeline (Columbia -> Tata CLiQ) in the background.
    Automatically resumes interrupted jobs across server restarts unless force=true.
    Immediately returns HTTP 202 Accepted with a unique job_id.
    """
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
        task = asyncio.create_task(run_sequential_pipeline(job_id, limit=limit))
        set_pipeline_task(task)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "resumed",
                "limit": limit,
                "message": f"Resumed interrupted scrape job {job_id} in background",
                "status_url": f"/scrape/status/{job_id}"
            }
        )

    job = await create_job(force=force)
    job_id = job["job_id"]

    # Dispatch pipeline in background task
    task = asyncio.create_task(run_sequential_pipeline(job_id, limit=limit))
    set_pipeline_task(task)

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "limit": limit,
            "message": "Scraper job started in background (Columbia -> Tata CLiQ sequentially)",
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
    return {"status": "idle", "message": "No scrape job is currently running"}


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
