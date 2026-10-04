import asyncio
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from jobs import create_job, get_job, get_active_job
from runner import scrape_columbia, scrape_tata, run_sequential_pipeline, close_shared_browser


app = FastAPI(
    title="Product Scraper API",
    description="Asynchronous and sequential web scraper API for Columbia Sportswear India and Tata CLiQ.",
    version="2.0.0"
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
        "architecture": "asynchronous_background_jobs",
        "active_job": active["job_id"] if active else None,
        "endpoints": {
            "trigger_job": "POST /scrape",
            "check_status": "GET /scrape/status/{job_id}",
            "active_status": "GET /scrape/status",
            "legacy_columbia": "GET /scrape",
            "legacy_tata": "GET /scrape/tata"
        }
    }


@app.post("/scrape", status_code=202)
async def trigger_scrape_job():
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
    asyncio.create_task(run_sequential_pipeline(job_id))

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "message": "Scraper job started in background (Columbia -> Tata CLiQ sequentially)",
            "status_url": f"/scrape/status/{job_id}"
        }
    )


@app.get("/scrape/status/{job_id}")
async def get_scrape_status(job_id: str):
    """
    Returns live progress for a specific scrape job.
    Includes overall status, current scraper, percentage, product and variant counts, and elapsed time.
    """
    job = await get_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found"}
        )
    return job


@app.get("/scrape/status")
async def get_latest_scrape_status():
    """Returns the currently active job status, or message if idle."""
    active = await get_active_job()
    if active:
        return active
    return {"status": "idle", "message": "No scrape job is currently running"}


@app.get("/scrape")
async def get_columbia_data():
    """
    Backwards-compatible endpoint for Columbia products.
    Returns latest saved JSON, or current progress if a job is in flight.
    """
    active = await get_active_job()
    file_path = Path("columbia_products.json")

    if file_path.exists():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if active and active.get("current_scraper") == "columbia":
        return JSONResponse(
            status_code=202,
            content={
                "message": "Columbia scrape is currently running in the background",
                "status_url": f"/scrape/status/{active['job_id']}"
            }
        )

    # Fallback to synchronous run if no saved file exists
    return await scrape_columbia()


@app.get("/scrape/tata")
async def get_tata_data():
    """
    Backwards-compatible endpoint for Tata CLiQ products.
    Returns latest saved JSON, or current progress if a job is in flight.
    """
    active = await get_active_job()
    file_path = Path("tatacliq_columbia_products.json")

    if file_path.exists():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if active and active.get("current_scraper") == "tatacliq":
        return JSONResponse(
            status_code=202,
            content={
                "message": "Tata CLiQ scrape is currently running in the background",
                "status_url": f"/scrape/status/{active['job_id']}"
            }
        )

    # Fallback to synchronous run if no saved file exists
    return await scrape_tata()
