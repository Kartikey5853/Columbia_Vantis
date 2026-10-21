import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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


def extract_columbia_size_from_sku(sku: Optional[str]) -> str:
    """Extracts genuine garment or footwear size from standard Columbia SKU."""
    if not sku:
        return ""
    parts = str(sku).strip().split("-")
    if len(parts) >= 3:
        cand = parts[-1].strip().upper()
        if cand == "N" and len(parts) >= 4:
            cand = parts[-2].strip().upper()
        if cand.endswith("N") and (cand[:-1] in ("XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL") or cand[:-1].replace(".", "").isdigit()):
            cand = cand[:-1]
        if cand in ("OS", "O/S", "ONESIZE", "ONE SIZE", "ALL"):
            return "One Size"
        if cand and cand not in ("STANDARD", "DEFAULT", "NA", "N/A", "NONE"):
            return cand
    return ""


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


_MASTER_CATALOG_CACHE = None


def get_master_catalog_lookups():
    global _MASTER_CATALOG_CACHE
    if _MASTER_CATALOG_CACHE is not None:
        return _MASTER_CATALOG_CACHE

    records = []
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "data" / "master_catalog_mappings.json",
        ENV_DIR / "data" / "master_catalog_mappings.json",
        ENV_DIR.parent / "data" / "master_catalog_mappings.json",
        Path("data/master_catalog_mappings.json"),
    ]
    for c in candidates:
        if c.exists():
            try:
                import json
                with open(c, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    records = d.get("records") or []
                    if records:
                        break
            except Exception:
                pass

    pid_to_rec = {}
    by_style = {}
    by_sc = {}

    for r in records:
        st = str(r.get("style") or "").strip().upper()
        sc = str(r.get("style_code") or "").strip().upper()
        if st:
            by_style.setdefault(st, []).append(r)
        if sc:
            by_sc.setdefault(sc, []).append(r)

        pids = r.get("platform_ids") or {}
        for pk, pval in pids.items():
            if pval and str(pval).upper() not in ("NONE", "ERROR", "NAN"):
                pval_str = str(pval).strip().lower()
                pid_to_rec[f"{pk}:{pval_str}"] = r
                pid_to_rec[pval_str] = r
                if len(pval_str) >= 9:
                    pid_to_rec.setdefault(f"{pk}:{pval_str[:9]}", r)
                    pid_to_rec.setdefault(pval_str[:9], r)

    _MASTER_CATALOG_CACHE = (pid_to_rec, by_style, by_sc)
    return _MASTER_CATALOG_CACHE


def enrich_variants_from_master(
    pid: str,
    raw_sku: str,
    title: str,
    price: float,
    mrp: float,
    available: bool,
    source: str,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    pid_to_rec, by_style, by_sc = get_master_catalog_lookups()
    if not pid_to_rec and not by_style:
        return [], None, None

    pid_clean = str(pid or "").strip().lower()
    base_pid = pid_clean.split("_")[0]
    raw_sku_upper = str(raw_sku or "").strip().upper()
    source_clean = str(source or "").strip().lower()

    m_rec = (
        pid_to_rec.get(f"{source_clean}:{pid_clean}")
        or pid_to_rec.get(pid_clean)
        or pid_to_rec.get(f"{source_clean}:{base_pid}")
        or pid_to_rec.get(base_pid)
        or (pid_to_rec.get(f"{source_clean}:{base_pid[:9]}") if len(base_pid) >= 9 else None)
        or (pid_to_rec.get(base_pid[:9]) if len(base_pid) >= 9 else None)
    )

    matched_style = None
    matched_sc = None
    if m_rec:
        matched_style = m_rec.get("style")
        matched_sc = m_rec.get("style_code")
    else:
        sc_cand = "-".join(raw_sku_upper.split("-")[:2]) if "-" in raw_sku_upper else raw_sku_upper
        st_cand = raw_sku_upper.split("-")[0] if "-" in raw_sku_upper else raw_sku_upper
        if sc_cand in by_sc:
            matched_sc = sc_cand
            matched_style = st_cand
        elif st_cand in by_style:
            matched_style = st_cand
        else:
            m = re.search(r"\b([A-Z0-9]{2}[0-9]{4})\b", f"{title} {raw_sku_upper}", re.IGNORECASE)
            if m and m.group(1).upper() in by_style:
                matched_style = m.group(1).upper()

    siblings = []
    if matched_sc and matched_sc in by_sc:
        siblings = by_sc[matched_sc]
    elif matched_style and matched_style in by_style:
        siblings = by_style[matched_style]

    if not siblings:
        return [], matched_style, None

    matched_ean = siblings[0].get("ean") or None
    variants = []
    seen_sizes = set()

    for sib in siblings:
        sib_sku = sib.get("sku") or ""
        sz = extract_columbia_size_from_sku(sib_sku) or "One Size"
        if sz not in seen_sizes:
            seen_sizes.add(sz)
            qty = int(sib.get("soh") or (1 if available else 0))
            variants.append({
                "size": sz,
                "sku": sib_sku,
                "ean": sib.get("ean"),
                "style": matched_style,
                "available": available,
                "stock": qty,
                "quantity": qty,
                "price": price,
                "mrp": mrp,
            })

    return variants, matched_style, matched_ean


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
        sku_extracted_size = extract_columbia_size_from_sku(raw_sku)

        if not incoming_variants:
            size_val = (p.get("size") or "").strip()
            if not size_val or size_val.lower() in ("standard", "default", "na", "none", "one size"):
                size_val = sku_extracted_size or "One Size"

            qty = int(p.get("quantity") or p.get("stock") or (1 if available else 0))
            incoming_variants = [{
                "size": size_val,
                "sku": str(p.get("variant_id") or raw_sku),
                "style": style,
                "available": available,
                "stock": qty,
                "quantity": qty,
                "price": price,
                "mrp": mrp
            }]

        # Master Catalog enrichment for single/missing variant items
        if len(incoming_variants) <= 1:
            m_vars, m_style, m_ean = enrich_variants_from_master(
                pid=pid,
                raw_sku=raw_sku,
                title=title,
                price=price,
                mrp=mrp,
                available=available,
                source=source,
            )
            if m_vars:
                incoming_variants = m_vars
            if m_style:
                target["style"] = m_style
            if m_ean and not target.get("ean"):
                target["ean"] = m_ean

        # Append non-duplicate variants
        existing_sizes = {v.get("size") for v in target["variants"]}
        for v in incoming_variants:
            v_size = (v.get("size") or "").strip()
            v_sku = str(v.get("sku") or raw_sku)
            if not v_size or v_size.lower() in ("standard", "default", "na", "none"):
                cand_from_vsku = extract_columbia_size_from_sku(v_sku)
                v_size = cand_from_vsku or sku_extracted_size or "One Size"
            v["size"] = v_size

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
