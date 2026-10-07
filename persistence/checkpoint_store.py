from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from persistence.supabase_client import get_supabase_client, SupabaseClient


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =========================================================================
# Listing Page Checkpoints
# =========================================================================

async def get_completed_listing_pages(
    run_id: str,
    client: Optional[SupabaseClient] = None
) -> Set[int]:
    """Returns the set of page numbers already successfully completed for this run."""
    cli = client or get_supabase_client()
    rows = await cli.select(
        "scrape_listing_pages",
        columns="page_number",
        filters={
            "scrape_run_id": f"eq.{run_id}",
            "status": "eq.completed"
        }
    )
    return {int(r["page_number"]) for r in (rows or [])}


async def record_listing_page_started(
    run_id: str,
    page_number: int,
    client: Optional[SupabaseClient] = None
) -> None:
    """Records that scraping of a listing page has commenced."""
    cli = client or get_supabase_client()
    # Check if existing page record exists
    existing = await cli.select(
        "scrape_listing_pages",
        filters={"scrape_run_id": f"eq.{run_id}", "page_number": f"eq.{page_number}"}
    )
    if existing:
        attempts = existing[0].get("attempts", 0) + 1
        await cli.update(
            "scrape_listing_pages",
            {"status": "in_progress", "attempts": attempts, "updated_at": now_utc_iso()},
            filters={"id": f"eq.{existing[0]['id']}"}
        )
    else:
        await cli.insert(
            "scrape_listing_pages",
            {
                "scrape_run_id": run_id,
                "page_number": page_number,
                "status": "in_progress",
                "attempts": 1,
                "product_count": 0,
                "updated_at": now_utc_iso()
            }
        )


async def record_listing_page_completed(
    run_id: str,
    page_number: int,
    product_count: int,
    client: Optional[SupabaseClient] = None
) -> None:
    """
    Marks a listing page as completed.
    Must ONLY be called after its products have been successfully persisted.
    """
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    await cli.upsert(
        "scrape_listing_pages",
        {
            "scrape_run_id": run_id,
            "page_number": page_number,
            "status": "completed",
            "product_count": product_count,
            "error": None,
            "completed_at": now_iso,
            "updated_at": now_iso
        },
        on_conflict="scrape_run_id,page_number"
    )


async def record_listing_page_failed(
    run_id: str,
    page_number: int,
    error: str,
    client: Optional[SupabaseClient] = None
) -> None:
    """Marks a listing page as failed."""
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    await cli.upsert(
        "scrape_listing_pages",
        {
            "scrape_run_id": run_id,
            "page_number": page_number,
            "status": "failed",
            "error": str(error)[:1000],
            "updated_at": now_iso
        },
        on_conflict="scrape_run_id,page_number"
    )


# =========================================================================
# Product-Level Checkpoints
# =========================================================================

async def init_product_progress(
    run_id: str,
    product_id: str,
    source_product_id: str,
    client: Optional[SupabaseClient] = None
) -> None:
    """Initializes product tracking in 'pending' status if not already present."""
    cli = client or get_supabase_client()
    await cli.upsert(
        "scrape_product_progress",
        {
            "scrape_run_id": run_id,
            "product_id": product_id,
            "source_product_id": source_product_id,
            "status": "pending",
            "attempts": 0,
            "variant_count": 0,
            "started_at": now_utc_iso(),
            "updated_at": now_utc_iso()
        },
        on_conflict="scrape_run_id,product_id"
    )


async def get_incomplete_products(
    run_id: str,
    client: Optional[SupabaseClient] = None
) -> List[Dict[str, Any]]:
    """
    Returns all product progress items for this run that are NOT completed.
    Paginates using offset to support arbitrarily large product catalogs (> 1000 items).
    """
    cli = client or get_supabase_client()
    all_incomplete = []
    chunk_size = 1000
    offset = 0

    while True:
        rows = await cli.select(
            "scrape_product_progress",
            columns="id,scrape_run_id,product_id,source_product_id,status,attempts,last_error,variant_count",
            filters={
                "scrape_run_id": f"eq.{run_id}",
                "status": "neq.completed"
            },
            order="id.asc",
            limit=chunk_size,
            offset=offset
        )
        if not rows:
            break
        all_incomplete.extend(rows)
        if len(rows) < chunk_size:
            break
        offset += len(rows)

    return all_incomplete


async def get_completed_product_ids(
    run_id: str,
    client: Optional[SupabaseClient] = None
) -> Set[str]:
    """
    Returns the set of source_product_ids already successfully completed for this run.
    Paginates to support catalogs > 1000 items.
    """
    cli = client or get_supabase_client()
    completed: Set[str] = set()
    offset = 0
    chunk_size = 1000

    while True:
        rows = await cli.select(
            "scrape_product_progress",
            columns="source_product_id",
            filters={
                "scrape_run_id": f"eq.{run_id}",
                "status": "eq.completed"
            },
            limit=chunk_size,
            offset=offset
        )
        if not rows:
            break
        for r in rows:
            if "source_product_id" in r and r["source_product_id"]:
                completed.add(str(r["source_product_id"]).strip())
        if len(rows) < chunk_size:
            break
        offset += len(rows)

    return completed


async def mark_product_in_progress(
    run_id: str,
    product_id: str,
    client: Optional[SupabaseClient] = None
) -> None:
    """Marks a product as currently undergoing processing (e.g. variant fetch)."""
    cli = client or get_supabase_client()
    rows = await cli.select(
        "scrape_product_progress",
        filters={"scrape_run_id": f"eq.{run_id}", "product_id": f"eq.{product_id}"}
    )
    attempts = (rows[0].get("attempts", 0) + 1) if rows else 1
    await cli.update(
        "scrape_product_progress",
        {"status": "in_progress", "attempts": attempts, "updated_at": now_utc_iso()},
        filters={"scrape_run_id": f"eq.{run_id}", "product_id": f"eq.{product_id}"}
    )


async def mark_product_completed(
    run_id: str,
    product_id: str,
    variant_count: int = 0,
    client: Optional[SupabaseClient] = None
) -> None:
    """
    Marks a product as completed.
    Must ONLY be called after product state and price changes are successfully persisted to Supabase.
    """
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    await cli.update(
        "scrape_product_progress",
        {
            "status": "completed",
            "variant_count": variant_count,
            "last_error": None,
            "completed_at": now_iso,
            "updated_at": now_iso
        },
        filters={"scrape_run_id": f"eq.{run_id}", "product_id": f"eq.{product_id}"}
    )


async def mark_product_failed(
    run_id: str,
    product_id: str,
    error: str,
    client: Optional[SupabaseClient] = None
) -> None:
    """Marks a product as failed with error context for retry on resume."""
    cli = client or get_supabase_client()
    now_iso = now_utc_iso()
    await cli.update(
        "scrape_product_progress",
        {
            "status": "failed",
            "last_error": str(error)[:1000],
            "updated_at": now_iso
        },
        filters={"scrape_run_id": f"eq.{run_id}", "product_id": f"eq.{product_id}"}
    )


async def batch_record_product_progress(
    run_id: str,
    progress_items: List[Dict[str, Any]],
    status: str = "completed",
    client: Optional[SupabaseClient] = None,
    batch_size: int = 500
) -> None:
    """
    Batches product progress tracking (default 500 items per request).
    """
    if not progress_items:
        return

    cli = client or get_supabase_client()
    now_iso = now_utc_iso()

    for i in range(0, len(progress_items), batch_size):
        chunk = progress_items[i:i + batch_size]
        rows = []
        for item in chunk:
            rows.append({
                "scrape_run_id": run_id,
                "product_id": item["product_id"],
                "source_product_id": item["source_product_id"],
                "status": status,
                "attempts": 1,
                "variant_count": item.get("variant_count", 0),
                "started_at": now_iso,
                "completed_at": now_iso if status == "completed" else None,
                "updated_at": now_iso
            })
        await cli.upsert(
            "scrape_product_progress",
            rows,
            on_conflict="scrape_run_id,product_id",
            return_representation=False
        )
