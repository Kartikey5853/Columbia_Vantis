from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from persistence.supabase_client import get_supabase_client, SupabaseClient

KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))


def get_business_date() -> str:
    """Returns the current date in Asia/Kolkata timezone (YYYY-MM-DD)."""
    return datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")


def now_utc_iso() -> str:
    """Returns current UTC ISO-formatted timestamp."""
    return datetime.now(timezone.utc).isoformat()


_SCRAPER_IDS: Dict[Any, str] = {}


async def get_scraper_id(scraper_name: str, client: Optional[SupabaseClient] = None) -> str:
    """Resolves and caches the UUID of the scraper from the 'scrapers' table."""
    global _SCRAPER_IDS
    cli = client or get_supabase_client()
    norm_name = scraper_name.strip().lower()
    cache_key = (id(cli), norm_name)
    if cache_key in _SCRAPER_IDS:
        return _SCRAPER_IDS[cache_key]

    rows = await cli.select("scrapers", columns="id,name", filters={"name": f"eq.{norm_name}"})
    if rows and len(rows) > 0:
        s_id = rows[0]["id"]
        _SCRAPER_IDS[cache_key] = s_id
        return s_id

    # Create if missing
    source_map = {
        "tata": "tatacliq",
        "columbia": "columbia_sportswear_india",
        "adv": "adventuras",
        "myntra": "myntra"
    }
    new_rows = await cli.upsert(
        "scrapers",
        {"name": norm_name, "source": source_map.get(norm_name, norm_name), "enabled": True},
        on_conflict="name",
        return_representation=True
    )
    s_id = new_rows[0]["id"]
    _SCRAPER_IDS[cache_key] = s_id
    return s_id


async def get_or_create_daily_run(
    scraper_name: str,
    business_date: Optional[str] = None,
    client: Optional[SupabaseClient] = None
) -> Dict[str, Any]:
    """
    Finds today's incomplete run or creates a new execution record for this business date.
    Strictly prevents duplicate active runs for the same scraper and date.
    """
    cli = client or get_supabase_client()
    scraper_id = await get_scraper_id(scraper_name, cli)
    b_date = business_date or get_business_date()

    # 1. Check for existing active or incomplete run for this date
    existing_runs = await cli.select(
        "scrape_runs",
        filters={
            "scraper_id": f"eq.{scraper_id}",
            "business_date": f"eq.{b_date}",
        },
        order="started_at.desc",
        limit=5
    )

    if existing_runs:
        # If an active run exists (queued/running/paused), resume it
        for r in existing_runs:
            if r["status"] in ("queued", "running", "paused"):
                await cli.update(
                    "scrape_runs",
                    {"status": "running", "updated_at": now_utc_iso()},
                    filters={"id": f"eq.{r['id']}"}
                )
                r["status"] = "running"
                return r

        # If a failed run exists today, resume/retry it
        for r in existing_runs:
            if r["status"] == "failed":
                await cli.update(
                    "scrape_runs",
                    {"status": "running", "updated_at": now_utc_iso(), "last_error": None},
                    filters={"id": f"eq.{r['id']}"}
                )
                r["status"] = "running"
                return r

        # If all runs are completed, return the last completed run or create a new run if explicitly permitted
        if existing_runs[0]["status"] == "completed":
            return existing_runs[0]

    # 2. Create new run
    payload = {
        "scraper_id": scraper_id,
        "business_date": b_date,
        "status": "running",
        "stage": "listings",
        "total_products": 0,
        "completed_products": 0,
        "failed_products": 0,
        "started_at": now_utc_iso(),
        "updated_at": now_utc_iso()
    }
    created = await cli.insert("scrape_runs", payload, return_representation=True)
    return created[0]


async def update_run_stage(
    run_id: str,
    stage: str,
    total_products: Optional[int] = None,
    client: Optional[SupabaseClient] = None
) -> None:
    """Updates the execution stage ('listings', 'products', 'variants', 'finalizing')."""
    cli = client or get_supabase_client()
    data: Dict[str, Any] = {
        "stage": stage,
        "updated_at": now_utc_iso()
    }
    if total_products is not None:
        data["total_products"] = total_products
    await cli.update("scrape_runs", data, filters={"id": f"eq.{run_id}"})


async def update_run_counts(
    run_id: str,
    completed_delta: int = 0,
    failed_delta: int = 0,
    client: Optional[SupabaseClient] = None
) -> None:
    """Incrementally updates completed and failed product counts."""
    cli = client or get_supabase_client()
    # Fetch current
    runs = await cli.select("scrape_runs", columns="completed_products,failed_products", filters={"id": f"eq.{run_id}"})
    if runs:
        curr = runs[0]
        data = {
            "completed_products": curr.get("completed_products", 0) + completed_delta,
            "failed_products": curr.get("failed_products", 0) + failed_delta,
            "updated_at": now_utc_iso()
        }
        await cli.update("scrape_runs", data, filters={"id": f"eq.{run_id}"})


async def complete_run(
    run_id: str,
    client: Optional[SupabaseClient] = None
) -> Dict[str, Any]:
    """Marks a scrape run as successfully completed."""
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    res = await cli.update(
        "scrape_runs",
        {
            "status": "completed",
            "stage": "finalizing",
            "completed_at": now_iso,
            "updated_at": now_iso,
            "last_error": None
        },
        filters={"id": f"eq.{run_id}"},
        return_representation=True
    )
    return res[0] if res else {}


async def fail_run(
    run_id: str,
    error: str,
    client: Optional[SupabaseClient] = None
) -> Dict[str, Any]:
    """Marks a scrape run as failed with error context."""
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    res = await cli.update(
        "scrape_runs",
        {
            "status": "failed",
            "updated_at": now_iso,
            "last_error": str(error)[:1000]
        },
        filters={"id": f"eq.{run_id}"},
        return_representation=True
    )
    return res[0] if res else {}
