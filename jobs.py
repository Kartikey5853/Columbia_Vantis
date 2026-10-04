import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# In-memory job repository (bounded to keep RAM < 1MB)
_JOBS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_JOB_ID: Optional[str] = None
_JOB_LOCK = asyncio.Lock()
MAX_STORED_JOBS = 20


def generate_job_id() -> str:
    """Generate a clean timestamped unique job ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"job_{timestamp}_{uid}"


async def get_active_job() -> Optional[Dict[str, Any]]:
    """Return the currently running or queued job, if any."""
    global _ACTIVE_JOB_ID
    if _ACTIVE_JOB_ID and _ACTIVE_JOB_ID in _JOBS:
        job = _JOBS[_ACTIVE_JOB_ID]
        if job.get("status") in ("queued", "running"):
            return dict(job)
        _ACTIVE_JOB_ID = None
    return None


async def create_job() -> Dict[str, Any]:
    """Create a new scrape job if no job is currently running."""
    global _ACTIVE_JOB_ID, _JOBS
    async with _JOB_LOCK:
        active = await get_active_job()
        if active:
            raise RuntimeError(f"A scrape job is already active: {active['job_id']}")

        job_id = generate_job_id()
        now_iso = datetime.now(timezone.utc).isoformat()

        job_record = {
            "job_id": job_id,
            "status": "queued",  # queued | running | completed | failed
            "current_scraper": None,  # columbia | tatacliq | None
            "progress_percentage": 0.0,
            "product_count": 0,
            "variant_count": 0,
            "started_at": now_iso,
            "completed_at": None,
            "elapsed_seconds": 0.0,
            "error": None,
            "scrapers": {
                "columbia": {
                    "status": "queued",
                    "product_count": 0,
                    "duration_seconds": 0.0,
                    "error": None
                },
                "tatacliq": {
                    "status": "queued",
                    "product_count": 0,
                    "variant_count": 0,
                    "duration_seconds": 0.0,
                    "error": None
                }
            }
        }

        # Keep memory minimal: evict oldest completed/failed job if limit reached
        if len(_JOBS) >= MAX_STORED_JOBS:
            completed_keys = [k for k, v in _JOBS.items() if v.get("status") in ("completed", "failed")]
            if completed_keys:
                del _JOBS[completed_keys[0]]

        _JOBS[job_id] = job_record
        _ACTIVE_JOB_ID = job_id
        return dict(job_record)


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve job details by job_id with real-time elapsed seconds."""
    job = _JOBS.get(job_id)
    if job:
        copy_job = dict(job)
        if copy_job.get("status") in ("queued", "running"):
            try:
                start_dt = datetime.fromisoformat(copy_job["started_at"])
                copy_job["elapsed_seconds"] = round((datetime.now(timezone.utc) - start_dt).total_seconds(), 1)
            except Exception:
                pass
        return copy_job
    return None


async def update_job(job_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Thread-safe update of job status and progress metrics."""
    global _ACTIVE_JOB_ID
    async with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None

        for k, v in kwargs.items():
            if k == "scrapers" and isinstance(v, dict):
                for s_name, s_val in v.items():
                    if s_name in job["scrapers"]:
                        job["scrapers"][s_name].update(s_val)
                    else:
                        job["scrapers"][s_name] = s_val
            else:
                job[k] = v

        if kwargs.get("status") in ("completed", "failed"):
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = None

        return dict(job)
