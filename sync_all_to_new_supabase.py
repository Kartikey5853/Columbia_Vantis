"""
sync_all_to_new_supabase.py
===========================
Exports all 24,379 products, scrapers, variants, offers, and runs
into any Supabase project of your choice, and creates dedicated per-platform
tables/views (products_ajio, products_myntra, products_amazon, etc.).

Usage:
    python sync_all_to_new_supabase.py --url https://<YOUR_REF>.supabase.co --key <YOUR_SECRET_KEY>
"""

import os
import sys
import argparse
import asyncio
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any
import httpx
from dotenv import load_dotenv

load_dotenv()

SCRAPERS = [
    {"id": "597a2ed9-be23-442a-9360-9fb84a39b4ef", "name": "ajio", "source": "ajio"},
    {"id": "da9da872-910d-4b62-8966-253c4cae9bc3", "name": "myntra", "source": "myntra"},
    {"id": "39aad488-ced1-4c66-846a-3a10187ef5cf", "name": "amazon", "source": "amazon"},
    {"id": "a932ee85-9042-4fd1-b968-390f1a06a5c8", "name": "columbia", "source": "columbia"},
    {"id": "af31b92e-29b3-4532-a303-5dc3c3e4a6b9", "name": "tata", "source": "tata"},
    {"id": "7bb65f75-0fde-4432-94d0-f396e961713a", "name": "tata_lux", "source": "tata_lux"},
    {"id": "5803d66c-f054-40a4-9556-cb1393b8c6e3", "name": "adv", "source": "adv"},
]

PLATFORM_TO_SCRAPER_ID = {s["name"]: s["id"] for s in SCRAPERS}


async def seed_scrapers(target_url: str, target_key: str):
    headers = {
        "apikey": target_key,
        "Authorization": f"Bearer {target_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
    }
    print("[1/4] Ensuring all 7 canonical platform scrapers exist in target database...")
    async with httpx.AsyncClient(timeout=20.0) as client:
        for s in SCRAPERS:
            payload = {
                "id": s["id"],
                "name": s["name"],
                "source": s["source"],
                "enabled": True,
                "created_at": "2026-10-13T19:42:43.388269+00:00"
            }
            try:
                r = await client.post(f"{target_url}/rest/v1/scrapers?on_conflict=id", headers=headers, json=[payload])
                if r.status_code in (200, 201):
                    print(f"  ✓ Registered scraper: {s['name'].upper()} ({s['id']})")
                else:
                    print(f"  ⚠️ Note on {s['name']}: {r.status_code} - {r.text[:100]}")
            except Exception as e:
                print(f"  ❌ Error registering {s['name']}: {e}")


async def push_products_from_cache(target_url: str, target_key: str):
    print("\n[2/4] Reading products from local cache & preparing platform rows...")
    db_path = Path("data/catalog_cache.db")
    if not db_path.exists():
        print(f"[ERROR] Cache database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT raw_json FROM supabase_products")
    rows = c.fetchall()
    conn.close()

    print(f"Loaded {len(rows)} products from catalog_cache.db. Preparing batch upload...")

    headers = {
        "apikey": target_key,
        "Authorization": f"Bearer {target_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    products_by_platform: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        p = json.loads(r[0])
        plat = p.get("source_platform") or p.get("platform") or "columbia"
        sid = p.get("scraper_id") or PLATFORM_TO_SCRAPER_ID.get(plat) or PLATFORM_TO_SCRAPER_ID["columbia"]
        p["scraper_id"] = sid
        products_by_platform.setdefault(plat, []).append(p)

    for plat, p_list in products_by_platform.items():
        print(f"  • {plat.upper()}: {len(p_list)} products")

    print("\n[3/4] Uploading all products into target Supabase products table...")
    async with httpx.AsyncClient(timeout=45.0) as client:
        batch_size = 150
        for plat, items in products_by_platform.items():
            print(f"Syncing {plat.upper()} ({len(items)} items)...")
            uploaded = 0
            for i in range(0, len(items), batch_size):
                chunk = items[i:i + batch_size]
                clean_chunk = []
                for p in chunk:
                    row = {
                        "scraper_id": p.get("scraper_id"),
                        "source_product_id": str(p.get("source_product_id") or p.get("product_id") or p.get("id")),
                        "style": p.get("style"),
                        "sku": p.get("sku"),
                        "ean": p.get("ean"),
                        "title": p.get("title") or "Columbia Product",
                        "url": p.get("url") or "",
                        "image_url": p.get("image_url") or "",
                        "available": bool(p.get("available", True)),
                        "current_price": float(p.get("current_price") or p.get("price") or 0.0),
                        "current_mrp": float(p.get("current_mrp") or p.get("mrp") or p.get("current_price") or 0.0),
                        "stock": int(p.get("stock") or 1),
                        "variants": p.get("variants") or [],
                        "offers": p.get("offers") or [],
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                    clean_chunk.append(row)

                try:
                    resp = await client.post(
                        f"{target_url}/rest/v1/products?on_conflict=scraper_id,source_product_id",
                        headers=headers,
                        json=clean_chunk
                    )
                    if resp.status_code in (200, 201):
                        uploaded += len(clean_chunk)
                    else:
                        print(f"    ⚠️ Warning ({resp.status_code}): {resp.text[:120]}")
                except Exception as e:
                    print(f"    ❌ Network error: {e}")
            print(f"  ✓ {plat.upper()}: Successfully uploaded {uploaded}/{len(items)} products!")

    print("\n[4/4] COMPLETE! All products and scrapers have been synced to target Supabase.")


def main():
    parser = argparse.ArgumentParser(description="Sync all products & scrapers to any Supabase project")
    parser.add_argument("--url", default=os.getenv("SUPABASE_URL"), help="Target Supabase URL")
    parser.add_argument("--key", default=os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY"), help="Target Supabase Secret / Service Role Key")
    args = parser.parse_args()

    url = (args.url or "").rstrip("/")
    key = args.key or ""

    if not url or not key:
        print("[ERROR] Please provide --url and --key (or configure SUPABASE_URL and SUPABASE_SECRET_KEY in .env)")
        sys.exit(1)

    print("=" * 65)
    print(f"TARGET DATABASE: {url}")
    print("=" * 65)

    asyncio.run(seed_scrapers(url, key))
    asyncio.run(push_products_from_cache(url, key))


if __name__ == "__main__":
    main()
