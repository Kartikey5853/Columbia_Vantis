from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from persistence.models import NormalizedProduct
from persistence.run_store import get_scraper_id
from persistence.supabase_client import get_supabase_client, SupabaseClient


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_canonical_product(
    product: NormalizedProduct,
    client: Optional[SupabaseClient] = None
) -> Dict[str, Any]:
    """
    Persists or updates a single canonical product record in Supabase.
    Enforces uniqueness on (scraper_id, source_product_id).
    Supports new columns (style, stock, offers) while falling back cleanly if pending DDL.
    """
    cli = client or get_supabase_client()
    scraper_id = await get_scraper_id(product.source, cli)
    row_data = product.to_db_row(scraper_id)

    try:
        res = await cli.upsert(
            "products",
            row_data,
            on_conflict="scraper_id,source_product_id",
            return_representation=True
        )
    except Exception as e:
        if any(col in str(e) for col in ("style", "stock", "offers")):
            print("[PERSISTENCE WARNING] Supabase products table missing style/stock/offers columns. Falling back without them. Run migration 003 in Supabase SQL editor.", flush=True)
            row_data.pop("style", None)
            row_data.pop("stock", None)
            row_data.pop("offers", None)
            res = await cli.upsert(
                "products",
                row_data,
                on_conflict="scraper_id,source_product_id",
                return_representation=True
            )
        else:
            raise

    if not res:
        rows = await cli.select(
            "products",
            filters={
                "scraper_id": f"eq.{scraper_id}",
                "source_product_id": f"eq.{row_data['source_product_id']}"
            }
        )
        return rows[0] if rows else {}
    return res[0]


async def upsert_canonical_products_batch(
    products: List[NormalizedProduct],
    client: Optional[SupabaseClient] = None,
    batch_size: int = 100
) -> List[Dict[str, Any]]:
    """
    Batches insertion/upsert of products into Supabase (default 500 items per HTTP call).
    Returns list of saved canonical product records with their UUID ids.
    Gracefully handles presence or absence of top-level style/stock/offers columns.
    """
    if not products:
        return []

    cli = client or get_supabase_client()
    scraper_name = products[0].source
    scraper_id = await get_scraper_id(scraper_name, cli)

    results = []
    total = len(products)

    for i in range(0, total, batch_size):
        chunk = products[i:i + batch_size]
        rows = [p.to_db_row(scraper_id) for p in chunk]
        try:
            res = await cli.upsert(
                "products",
                rows,
                on_conflict="scraper_id,source_product_id",
                return_representation=True
            )
        except Exception as e:
            if any(col in str(e) for col in ("style", "stock", "offers")):
                print("[PERSISTENCE WARNING] Supabase products table missing style/stock/offers columns. Falling back without them. Run migration 003 in Supabase SQL editor.", flush=True)
                for r in rows:
                    r.pop("style", None)
                    r.pop("stock", None)
                    r.pop("offers", None)
                res = await cli.upsert(
                    "products",
                    rows,
                    on_conflict="scraper_id,source_product_id",
                    return_representation=True
                )
            else:
                raise

        if res:
            results.extend(res)
        else:
            pids = [r["source_product_id"] for r in rows]
            fetched = await cli.select(
                "products",
                filters={
                    "scraper_id": f"eq.{scraper_id}",
                    "source_product_id": f"in.({','.join(pids)})"
                }
            )
            results.extend(fetched or [])

    return results


async def record_price_if_changed(
    product_id: str,
    price: Optional[float],
    mrp: Optional[float],
    scrape_run_id: Optional[str] = None,
    client: Optional[SupabaseClient] = None
) -> bool:
    """
    Records a historical price entry in 'price_history' ONLY IF:
    1. No prior price history exists for this product, OR
    2. The current price or MRP differs from the latest recorded price/MRP.
    """
    if price is None:
        return False

    cli = client or get_supabase_client()
    price_val = round(float(price), 2)
    mrp_val = round(float(mrp), 2) if mrp is not None else None

    latest_history = await cli.select(
        "price_history",
        columns="id,price,mrp,scrape_run_id",
        filters={"product_id": f"eq.{product_id}"},
        order="recorded_at.desc",
        limit=1
    )

    if latest_history:
        last = latest_history[0]
        if scrape_run_id and last.get("scrape_run_id") == scrape_run_id:
            return False

        last_price = round(float(last.get("price") or 0.0), 2)
        last_mrp = round(float(last.get("mrp") or 0.0), 2) if last.get("mrp") is not None else None

        if last_price == price_val and last_mrp == mrp_val:
            return False

    payload = {
        "product_id": product_id,
        "price": price_val,
        "mrp": mrp_val,
        "recorded_at": now_utc_iso(),
        "scrape_run_id": scrape_run_id
    }
    await cli.insert("price_history", payload, return_representation=False)
    return True


async def batch_record_prices_if_changed(
    product_entries: List[Dict[str, Any]],
    scrape_run_id: Optional[str] = None,
    client: Optional[SupabaseClient] = None,
    batch_size: int = 500
) -> int:
    """
    Batched historical price change recording (default 500 items per request).
    Checks latest price history and inserts only changed/new prices.
    Returns total price history records inserted.
    """
    if not product_entries:
        return 0

    cli = client or get_supabase_client()
    total_inserted = 0

    for i in range(0, len(product_entries), batch_size):
        chunk = product_entries[i:i + batch_size]
        chunk_pids = [item["product_id"] for item in chunk if item.get("product_id")]
        if not chunk_pids:
            continue

        existing_rows = await cli.select(
            "price_history",
            columns="product_id,price,mrp,scrape_run_id,recorded_at",
            filters={"product_id": f"in.({','.join(chunk_pids)})"},
            order="recorded_at.desc"
        )

        latest_by_pid: Dict[str, Dict[str, Any]] = {}
        for r in (existing_rows or []):
            pid = r["product_id"]
            if pid not in latest_by_pid:
                latest_by_pid[pid] = r

        new_history_rows = []
        now_iso = now_utc_iso()

        for item in chunk:
            pid = item.get("product_id")
            price = item.get("price")
            mrp = item.get("mrp")
            if not pid or price is None:
                continue

            price_val = round(float(price), 2)
            mrp_val = round(float(mrp), 2) if mrp is not None else None

            last = latest_by_pid.get(pid)
            if last:
                if scrape_run_id and last.get("scrape_run_id") == scrape_run_id:
                    continue
                last_price = round(float(last.get("price") or 0.0), 2)
                last_mrp = round(float(last.get("mrp") or 0.0), 2) if last.get("mrp") is not None else None
                if last_price == price_val and last_mrp == mrp_val:
                    continue

            new_history_rows.append({
                "product_id": pid,
                "price": price_val,
                "mrp": mrp_val,
                "recorded_at": now_iso,
                "scrape_run_id": scrape_run_id
            })

        if new_history_rows:
            await cli.insert("price_history", new_history_rows, return_representation=False)
            total_inserted += len(new_history_rows)

    return total_inserted


async def get_canonical_product_by_id(
    product_id: str,
    client: Optional[SupabaseClient] = None
) -> Optional[Dict[str, Any]]:
    """Fetches a single canonical product by UUID."""
    cli = client or get_supabase_client()
    rows = await cli.select("products", filters={"id": f"eq.{product_id}"})
    return rows[0] if rows else None


async def get_all_canonical_products(
    scraper_name: str,
    client: Optional[SupabaseClient] = None
) -> List[Dict[str, Any]]:
    """Fetches all canonical products for a given scraper from Supabase."""
    cli = client or get_supabase_client()
    scraper_id = await get_scraper_id(scraper_name, cli)

    all_products = []
    chunk_size = 1000

    while True:
        last_id = all_products[-1]["source_product_id"] if all_products else None
        filters = {"scraper_id": f"eq.{scraper_id}"}
        if last_id:
            filters["source_product_id"] = f"gt.{last_id}"

        rows = await cli.select(
            "products",
            filters=filters,
            order="source_product_id.asc",
            limit=chunk_size
        )
        if not rows:
            break
        all_products.extend(rows)
        if len(rows) < chunk_size:
            break

    return all_products
