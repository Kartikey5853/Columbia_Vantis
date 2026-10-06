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

# Active background asyncio task tracking
_PIPELINE_TASK: Optional[asyncio.Task] = None


def set_pipeline_task(task: Optional[asyncio.Task]) -> None:
    global _PIPELINE_TASK
    _PIPELINE_TASK = task


def get_pipeline_task() -> Optional[asyncio.Task]:
    global _PIPELINE_TASK
    if _PIPELINE_TASK and _PIPELINE_TASK.done():
        _PIPELINE_TASK = None
    return _PIPELINE_TASK


def is_pipeline_running() -> bool:
    task = get_pipeline_task()
    return task is not None and not task.done()


def find_orphaned_job() -> Optional[Dict[str, Any]]:
    """Finds the most recent job on disk that was left in running/queued state without an active in-process task."""
    if is_pipeline_running():
        return None
    try:
        json_files = sorted(JOB_STORE_DIR.glob("job_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("status") in ("queued", "running"):
                    return data
            except Exception:
                pass
    except Exception:
        pass
    return None


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
            if not is_pipeline_running():
                job["is_orphaned"] = True
            return job
        _ACTIVE_JOB_ID = None

    orphaned = find_orphaned_job()
    if orphaned:
        orphaned["is_orphaned"] = True
        return orphaned

    return None


SCRAPER_KEY_MAP = {
    "columbia": "columbia",
    "columbiasportswear": "columbia",
    "adv": "adv",
    "adventuras": "adv",
    "myntra": "myntra",
    "tata": "tatacliq",
    "tatacliq": "tatacliq",
}


async def _reconstruct_job_from_supabase(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Fallback recovery for ephemeral container restarts:
    Checks Supabase scrape_runs for today's date and reconstructs the job status.
    """
    try:
        from persistence.run_store import get_daily_scrapers_summary
        summary = await get_daily_scrapers_summary()
        if not summary:
            return None

        scrapers_dict = {}
        total_prods = 0
        all_done = True
        has_any_run = False
        earliest_start = None
        latest_complete = None

        canonical_key_map = {
            "columbia": "columbia",
            "adv": "adv",
            "myntra": "myntra",
            "tata": "tatacliq",
        }

        for s_name, data in summary.items():
            k = canonical_key_map.get(s_name, s_name)
            s_status = data.get("status", "pending")
            p_cnt = data.get("completed_products", 0)
            if data.get("run_id"):
                has_any_run = True
            if s_status != "completed":
                all_done = False
            total_prods += p_cnt
            if data.get("started_at") and (not earliest_start or data["started_at"] < earliest_start):
                earliest_start = data["started_at"]
            if data.get("completed_at") and (not latest_complete or data["completed_at"] > latest_complete):
                latest_complete = data["completed_at"]

            scrapers_dict[k] = {
                "status": s_status,
                "product_count": p_cnt,
                "variant_count": p_cnt if s_name in ("tata", "adv", "myntra") else 0,
                "duration_seconds": data.get("duration_seconds", 0.0),
                "error": data.get("error")
            }

        if not has_any_run:
            return None

        rec_status = "completed" if all_done else "running"
        reconstructed = {
            "job_id": job_id,
            "status": rec_status,
            "current_scraper": None if all_done else list(scrapers_dict.keys())[-1],
            "progress_percentage": 100.0 if all_done else 75.0,
            "product_count": total_prods,
            "variant_count": total_prods,
            "started_at": earliest_start or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": latest_complete if all_done else None,
            "elapsed_seconds": 0.0,
            "error": None,
            "scrapers": scrapers_dict,
            "recovered_from_supabase": True
        }
        _save_job_to_disk(reconstructed)
        return reconstructed
    except Exception as e:
        print(f"[JOBS] Notice: Supabase job reconstruction failed: {e}", flush=True)
        return None


async def create_job(scrapers: Optional[list] = None, force: bool = False) -> Dict[str, Any]:
    """Create a new scrape job with dynamic scraper configuration if no job is currently running."""
    global _ACTIVE_JOB_ID, _JOBS
    async with _JOB_LOCK:
        active = await get_active_job()
        if active:
            if active.get("is_orphaned") or force:
                # Mark orphaned or superseded job as failed
                old_id = active["job_id"]
                print(f"[JOBS] Overwriting orphaned/interrupted job {old_id} with new scrape job.", flush=True)
                if old_id in _JOBS:
                    _JOBS[old_id]["status"] = "failed"
                    _JOBS[old_id]["error"] = "Interrupted by server restart and superseded by new scrape request"
                    _save_job_to_disk(_JOBS[old_id])
                _ACTIVE_JOB_ID = None
            else:
                raise RuntimeError(f"A scrape job is already active: {active['job_id']}")

        job_id = generate_job_id()
        now_iso = datetime.now(timezone.utc).isoformat()

        if scrapers:
            keys = [SCRAPER_KEY_MAP.get(str(s).strip().lower(), str(s).strip().lower()) for s in scrapers if s]
        else:
            keys = ["columbia", "adv", "myntra", "tatacliq"]

        scrapers_dict = {
            k: {
                "status": "queued",
                "product_count": 0,
                "variant_count": 0,
                "duration_seconds": 0.0,
                "error": None
            }
            for k in keys
        }

        job_record = {
            "job_id": job_id,
            "status": "queued",  # queued | running | completed | failed
            "current_scraper": None,
            "progress_percentage": 0.0,
            "product_count": 0,
            "variant_count": 0,
            "started_at": now_iso,
            "updated_at": now_iso,
            "completed_at": None,
            "elapsed_seconds": 0.0,
            "error": None,
            "scrapers": scrapers_dict
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
    """Retrieve job details by job_id with real-time elapsed seconds and Supabase fallback."""
    job = _JOBS.get(job_id)
    if not job:
        job = _load_job_from_disk(job_id)
        if job:
            _JOBS[job_id] = job
        else:
            job = await _reconstruct_job_from_supabase(job_id)
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

        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if kwargs.get("status") in ("completed", "failed"):
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = None
            set_pipeline_task(None)

        _save_job_to_disk(job)
        return dict(job)
