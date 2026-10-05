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

from jobs import create_job, get_job, get_active_job
from runner import scrape_columbia, scrape_tata, run_sequential_pipeline, close_shared_browser
from persistence import get_all_canonical_products, get_database_storage_stats


app = FastAPI(
    title="Product Scraper API",
    description="Unified asynchronous web scraper API for Columbia Sportswear India and Tata CLiQ with Supabase persistence.",
    version="3.0.0"
)


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
async def trigger_scrape_job(limit: int = Query(None, description="Optional product limit for testing")):
    """
    Triggers the sequential scraping pipeline (Columbia -> Tata CLiQ) in the background.
    Immediately returns HTTP 202 Accepted with a unique job_id.
    """
    active = await get_active_job()
    if active:
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "message": "A scrape job is already currently running",
                "active_job": active,
                "status_url": f"/scrape/status/{active['job_id']}"
            }
        )

    job = await create_job()
    job_id = job["job_id"]

    # Dispatch pipeline in background task
    asyncio.create_task(run_sequential_pipeline(job_id, limit=limit))

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
            return {"source": "columbia", "total_products": len(prods), "products": prods}
    except Exception:
        pass

    backup_file = Path("data/columbia/columbia_data.json")
    if backup_file.exists():
        try:
            return json.loads(backup_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Legacy fallback
    legacy_file = Path("columbia_products.json")
    if legacy_file.exists():
        try:
            return json.loads(legacy_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {"source": "columbia", "total_products": 0, "products": []}


@app.get("/scrape/tata")
async def get_tata_data():
    """
    Returns canonical Tata CLiQ products from Supabase, or from rolling backup.
    """
    try:
        prods = await get_all_canonical_products("tata")
        if prods:
            return {"source": "tata", "total_products": len(prods), "products": prods}
    except Exception:
        pass

    backup_file = Path("data/tata/tata_data.json")
    if backup_file.exists():
        try:
            return json.loads(backup_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    legacy_file = Path("tatacliq_columbia_products.json")
    if legacy_file.exists():
        try:
            return json.loads(legacy_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {"source": "tata", "total_products": 0, "products": []}


@app.get("/db/diagnostics")
async def get_db_diagnostics():
    """Returns real storage measurements and row counts from Supabase."""
    return await get_database_storage_stats()
