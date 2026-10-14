import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List
from persistence.supabase_client import get_supabase_client
from persistence.normalizer import normalize_offer

async def backfill_offers():
    cli = get_supabase_client()
    scrapers = await cli.select("scrapers", columns="id,name")
    s_map = {s["name"]: s["id"] for s in scrapers}
    
    tata_id = s_map.get("tata")
    lux_id = s_map.get("tata_lux")
    
    # 1. Load Tata offers
    tata_path = Path("new_data/tatacliq_with_offers.json")
    tata_offers_map: Dict[str, List[Dict[str, Any]]] = {}
    if tata_path.exists():
        tdata = json.loads(tata_path.read_text(encoding="utf-8"))
        tprods = tdata.get("products", []) if isinstance(tdata, dict) else tdata
        for p in tprods:
            pid = str(p.get("product_id") or p.get("productId") or "").strip().lower()
            offs = p.get("offers") or []
            if pid and offs:
                tata_offers_map[pid] = [normalize_offer(o, platform="tatacliq") for o in offs]
                
    # 2. Load Tata Lux offers
    lux_path = Path("new_data/tatacliq_luxury_columbia_products_with_offers (1)_1.json")
    lux_offers_map: Dict[str, List[Dict[str, Any]]] = {}
    if lux_path.exists():
        ldata = json.loads(lux_path.read_text(encoding="utf-8"))
        lprods = ldata.get("products", []) if isinstance(ldata, dict) else ldata
        for p in lprods:
            pid = str(p.get("product_id") or p.get("productId") or "").strip().lower()
            offs = p.get("offers") or []
            if pid and offs:
                lux_offers_map[pid] = [normalize_offer(o, platform="tata_lux") for o in offs]
                
    print(f"Loaded offer maps: Tata={len(tata_offers_map)} products, Tata Lux={len(lux_offers_map)} products")
    
    # Backfill Tata products in Supabase
    if tata_id and tata_offers_map:
        tata_db_prods = await cli.select("products", columns="id,source_product_id,offers", filters={"scraper_id": f"eq.{tata_id}"}, limit=2500)
        print(f"Fetched {len(tata_db_prods)} Tata products from Supabase")
        updated_tata = 0
        for p in tata_db_prods:
            src_id = str(p.get("source_product_id") or "").strip().lower()
            offs = tata_offers_map.get(src_id)
            if offs:
                try:
                    await cli.update("products", {"offers": offs}, filters={"id": f"eq.{p['id']}"})
                    updated_tata += 1
                except Exception as ex:
                    print(f"Error updating Tata product {p['id']}: {ex}")
        print(f"✅ Successfully backfilled offers for {updated_tata} Tata products in Supabase.")
        
    # Backfill Tata Lux products in Supabase
    if lux_id and lux_offers_map:
        lux_db_prods = await cli.select("products", columns="id,source_product_id,offers", filters={"scraper_id": f"eq.{lux_id}"}, limit=2500)
        print(f"Fetched {len(lux_db_prods)} Tata Lux products from Supabase")
        updated_lux = 0
        for p in lux_db_prods:
            src_id = str(p.get("source_product_id") or "").strip().lower()
            offs = lux_offers_map.get(src_id)
            if offs:
                try:
                    await cli.update("products", {"offers": offs}, filters={"id": f"eq.{p['id']}"})
                    updated_lux += 1
                except Exception as ex:
                    print(f"Error updating Tata Lux product {p['id']}: {ex}")
        print(f"✅ Successfully backfilled offers for {updated_lux} Tata Lux products in Supabase.")

if __name__ == "__main__":
    asyncio.run(backfill_offers())
