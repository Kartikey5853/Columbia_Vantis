import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    ENV_DIR = Path(sys.executable).parent
else:
    ENV_DIR = Path(__file__).resolve().parent

if (ENV_DIR / ".env").exists():
    load_dotenv(ENV_DIR / ".env")
else:
    load_dotenv()

DEFAULT_SUPABASE_URL = "https://viflznbwqrunivhfoavq.supabase.co"
DEFAULT_SUPABASE_KEY = "sb_secret_wgDvOA3l28p2d2jzH5euRg_mgqeBpLF"

SUPABASE_URL = (os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or DEFAULT_SUPABASE_KEY
)

SCRAPER_IDS = {
    "myntra": "da9da872-910d-4b62-8966-253c4cae9bc3",
    "ajio": "597a2ed9-be23-442a-9360-9fb84a39b4ef",
}


def normalize_style_code(raw: str) -> Optional[str]:
    if not raw:
        return None
    cleaned = str(raw).strip()
    m = re.search(r"\b([A-Z0-9]{2}[0-9]{4})\b", cleaned, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    parts = cleaned.split("-")
    if parts and len(parts[0]) >= 4:
        return parts[0].strip().upper()
    return cleaned[:20].upper()


async def sync_products_to_supabase(
    products: List[Dict[str, Any]],
    source: str,
    log_func=print
) -> Dict[str, int]:
    """
    Direct asynchronous PostgREST upsert into Supabase products table.
    Enforces true size variants, stock counts, and promotional/bank offers.
    Deduplicates and merges variants by source_product_id to prevent Postgres 21000 ON CONFLICT error.
    """
    scraper_id = SCRAPER_IDS.get(source.lower(), SCRAPER_IDS["ajio"])
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
    }

    # Step 1: Aggregate and merge products by unique source_product_id
    grouped_products: Dict[str, Dict[str, Any]] = {}
    for p in products:
        pid = str(p.get("product_id") or p.get("source_product_id") or p.get("code") or p.get("id") or "").strip()
        if not pid:
            continue

        price = float(p.get("price") or 0.0)
        mrp = float(p.get("mrp") or price) if p.get("mrp") else price
        available = bool(p.get("available", True))
        title = str(p.get("title") or p.get("name") or "Columbia Product").strip()
        raw_sku = str(p.get("sku") or p.get("sellerSku") or p.get("variant_id") or pid).strip()
        style = p.get("style") or normalize_style_code(raw_sku) or normalize_style_code(title)

        if pid not in grouped_products:
            grouped_products[pid] = {
                "scraper_id": scraper_id,
                "source_product_id": pid,
                "title": title,
                "sku": raw_sku,
                "style": style,
                "ean": p.get("ean") or None,
                "url": p.get("url") or "",
                "image_url": p.get("image_url") or "",
                "available": available,
                "current_price": price,
                "current_mrp": mrp,
                "variants": [],
                "offers": list(p.get("offers") or []),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

        target = grouped_products[pid]

        # Extract variants from current item
        incoming_variants = p.get("variants") or []
        if not incoming_variants:
            size_val = p.get("size") or "One Size"
            qty = int(p.get("quantity") or p.get("stock") or (1 if available else 0))
            incoming_variants = [{
                "size": size_val if size_val != "Standard" else "One Size",
                "sku": str(p.get("variant_id") or raw_sku),
                "style": style,
                "available": available,
                "stock": qty,
                "quantity": qty,
                "price": price,
                "mrp": mrp
            }]

        # Append non-duplicate variants
        existing_sizes = {v.get("size") for v in target["variants"]}
        for v in incoming_variants:
            v_size = v.get("size") or "One Size"
            if v_size not in existing_sizes:
                target["variants"].append(v)
                existing_sizes.add(v_size)
            if v.get("available"):
                target["available"] = True

        # Merge offers
        existing_offers = {o.get("title") or o.get("code") for o in target["offers"]}
        for off in (p.get("offers") or []):
            off_key = off.get("title") or off.get("code")
            if off_key and off_key not in existing_offers:
                target["offers"].append(off)
                existing_offers.add(off_key)

    # Compute aggregate stock for each product
    clean_rows = []
    for pid, row in grouped_products.items():
        total_stock = sum(int(v.get("stock") or v.get("quantity") or 0) for v in row["variants"])
        if total_stock == 0 and row["available"]:
            total_stock = 1
        row["stock"] = total_stock
        clean_rows.append(row)

    upserted_count = 0
    price_history_count = 0

    async with httpx.AsyncClient(timeout=45.0) as client:
        batch_size = 100
        for i in range(0, len(clean_rows), batch_size):
            db_rows = clean_rows[i:i + batch_size]

            try:
                endpoint = f"{SUPABASE_URL}/rest/v1/products?on_conflict=scraper_id,source_product_id"
                resp = await client.post(endpoint, headers=headers, json=db_rows)
                if resp.status_code in (200, 201):
                    res_json = resp.json() or []
                    upserted_count += len(res_json)

                    # Historical price tracking
                    hist_rows = []
                    for row in res_json:
                        if row.get("id") and row.get("current_price") is not None:
                            hist_rows.append({
                                "product_id": row["id"],
                                "price": row["current_price"],
                                "mrp": row.get("current_mrp"),
                                "recorded_at": datetime.now(timezone.utc).isoformat()
                            })
                    if hist_rows:
                        resp_h = await client.post(f"{SUPABASE_URL}/rest/v1/price_history", headers=headers, json=hist_rows)
                        if resp_h.status_code in (200, 201):
                            price_history_count += len(hist_rows)
                else:
                    log_func(f"[Supabase] Warning ({resp.status_code}): {resp.text[:200]}")
            except Exception as exc:
                log_func(f"[Supabase] Sync error on batch: {exc}")

    log_func(f"[Supabase] Successfully upserted {upserted_count} products and recorded {price_history_count} prices for {source.upper()}.")
    return {"upserted": upserted_count, "price_history": price_history_count}


async def record_scrape_run(source: str, product_count: int, duration_seconds: float, status: str = "completed"):
    """Records scrape run status into scrape_runs table with schema-compliant payload."""
    scraper_id = SCRAPER_IDS.get(source.lower())
    if not scraper_id:
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "scraper_id": scraper_id,
        "business_date": today,
        "status": status,
        "stage": "finalizing",
        "total_products": product_count,
        "completed_products": product_count,
        "failed_products": 0,
        "report": {
            "scraper": source.lower(),
            "duration_seconds": round(duration_seconds, 1),
            "completed_products": product_count
        },
        "started_at": now_iso,
        "updated_at": now_iso,
        "completed_at": now_iso
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/scrape_runs", headers=headers, json=payload)
            if resp.status_code in (200, 201):
                print(f"[Supabase] Recorded scrape run for {source.upper()} in scrape_runs (status: {status}).")
            else:
                print(f"[Supabase] Warning recording scrape_runs ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[Supabase] Note: scrape_runs record error: {e}")
