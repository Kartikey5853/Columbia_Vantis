import asyncio
import os
import sys
from typing import Any, Dict, List, Optional
from persistence.supabase_client import get_supabase_client, SupabaseClient

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def get_database_storage_stats(
    client: Optional[SupabaseClient] = None
) -> Dict[str, Any]:
    """
    Fetches real PostgreSQL storage measurements and row counts from Supabase.
    Calls 'get_database_size_stats' RPC function, with fallback to PostgREST count queries.
    """
    cli = client or get_supabase_client()
    stats: Dict[str, Dict[str, Any]] = {}
    total_db_bytes: int = 0
    total_db_pretty: str = "N/A"

    try:
        # 1. Try calling the PostgreSQL stored procedure
        rpc_rows = await cli.rpc("get_database_size_stats")
        if isinstance(rpc_rows, list) and rpc_rows:
            for r in rpc_rows:
                t_name = r.get("table_name")
                if t_name == "__total_database__":
                    total_db_bytes = int(r.get("total_size_bytes") or 0)
                    total_db_pretty = r.get("total_size_pretty") or f"{total_db_bytes / (1024 * 1024):.2f} MB"
                else:
                    stats[t_name] = {
                        "row_count": int(r.get("row_count") or 0),
                        "size_bytes": int(r.get("total_size_bytes") or 0),
                        "size_pretty": r.get("total_size_pretty") or f"{int(r.get('total_size_bytes') or 0) / (1024 * 1024):.2f} MB"
                    }
            return {
                "source": "postgresql_rpc",
                "total_db_size_pretty": total_db_pretty,
                "total_db_bytes": total_db_bytes,
                "tables": stats
            }
    except Exception as e:
        # Fallback if RPC function is not yet created
        pass

    # 2. Fallback: Query exact row counts via PostgREST headers
    tables = [
        "products",
        "price_history",
        "scrape_runs",
        "scrape_listing_pages",
        "scrape_product_progress",
        "scrapers"
    ]
    raw_client = await cli.get_client()
    for t in tables:
        try:
            res = await raw_client.get(
                f"{cli.rest_url}/{t}",
                headers={"Prefer": "count=exact", "Range": "0-0"}
            )
            count = 0
            content_range = res.headers.get("content-range", "")
            if "/" in content_range:
                parts = content_range.split("/")
                if parts[1].isdigit():
                    count = int(parts[1])
            stats[t] = {
                "row_count": count,
                "size_bytes": 0,
                "size_pretty": "Available via RPC"
            }
        except Exception:
            stats[t] = {"row_count": 0, "size_bytes": 0, "size_pretty": "N/A"}

    return {
        "source": "postgrest_count",
        "total_db_size_pretty": "Available via RPC",
        "total_db_bytes": 0,
        "tables": stats
    }


def format_storage_report(stats: Dict[str, Any]) -> str:
    """Formats storage statistics in the requested standard format."""
    total = stats.get("total_db_size_pretty", "N/A")
    tables = stats.get("tables", {})

    lines = [
        "--------------------------------",
        "Supabase Database",
        "--------------------------------",
        f"Total DB size: {total}",
        ""
    ]

    table_keys = [
        "products",
        "price_history",
        "scrape_runs",
        "scrape_listing_pages",
        "scrape_product_progress"
    ]

    for k in table_keys:
        t_data = tables.get(k, {"row_count": 0, "size_pretty": "0 MB"})
        cnt = t_data.get("row_count", 0)
        sz = t_data.get("size_pretty", "0 MB")
        lines.append(f"{k}:")
        lines.append(f"rows = {cnt}")
        lines.append(f"size = {sz}")
        lines.append("")

    lines.append("--------------------------------")
    return "\n".join(lines)


async def main():
    stats = await get_database_storage_stats()
    print(format_storage_report(stats))


if __name__ == "__main__":
    asyncio.run(main())
