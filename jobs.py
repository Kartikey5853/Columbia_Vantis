import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

JOB_STORE_DIR = Path("jobs_data")
JOB_STORE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job repository (bounded to keep RAM < 1MB)
_JOBS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_JOB_ID: Optional[str] = None
_JOB_LOCK = asyncio.Lock()
MAX_STORED_JOBS = 20


def _save_job_to_disk(job: Dict[str, Any]) -> None:
    """Save a job record to disk JSON file for durability across server restarts."""
    try:
        job_file = JOB_STORE_DIR / f"{job['job_id']}.json"
        job_file.write_text(json.dumps(job, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[JOBS] Warning: failed to save job to disk: {e}", flush=True)


def _load_job_from_disk(job_id: str) -> Optional[Dict[str, Any]]:
    """Load a job record from disk JSON file if available."""
    try:
        job_file = JOB_STORE_DIR / f"{job_id}.json"
        if job_file.exists():
            data = json.loads(job_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[JOBS] Warning: failed to read job {job_id} from disk: {e}", flush=True)
    return None


def generate_job_id() -> str:
    """Generate a clean timestamped unique job ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"job_{timestamp}_{uid}"


async def get_active_job() -> Optional[Dict[str, Any]]:
    """Return the currently running or queued job, if any."""
    global _ACTIVE_JOB_ID
    if _ACTIVE_JOB_ID:
        job = await get_job(_ACTIVE_JOB_ID)
        if job and job.get("status") in ("queued", "running"):
            return job
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
        _save_job_to_disk(job_record)
        return dict(job_record)


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve job details by job_id with real-time elapsed seconds."""
    job = _JOBS.get(job_id)
    if not job:
        job = _load_job_from_disk(job_id)
        if job:
            _JOBS[job_id] = job

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
            job = _load_job_from_disk(job_id)
            if job:
                _JOBS[job_id] = job
            else:
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

        _save_job_to_disk(job)
        return dict(job)
