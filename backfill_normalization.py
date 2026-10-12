import asyncio
import sys
import time
from datetime import datetime, timezone
from persistence.supabase_client import get_supabase_client
from persistence.normalizer import normalize_sku_and_style, normalize_size, normalize_offer
from persistence.exporter import export_canonical_backup

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def run_backfill(batch_size: int = 200):
    print("=" * 60)
    print("STARTING SUPABASE CATALOG NORMALIZATION BACKFILL")
    print("=" * 60, flush=True)

    cli = get_supabase_client()
    t_start = time.perf_counter()

    # Test if top-level style, stock, offers columns exist
    has_new_cols = False
    try:
        test_col = await cli.select("products", columns="id,style,stock,offers", limit=1)
        has_new_cols = True
        print("[SCHEMA] Dedicated columns (style, stock, offers) DETECTED in Supabase products table!")
    except Exception as e:
        print("[SCHEMA NOTE] Top-level style/stock/offers columns not yet added to PostgreSQL table.")
        print("              Updating sku and variants JSONB with full normalized fields.")

    offset = 0
    total_processed = 0

    while True:
        rows = await cli.select("products", offset=offset, limit=batch_size, order="id.asc")
        if not rows:
            break

        chunk_len = len(rows)
        for r in rows:
            raw_sku = r.get("sku")
            title = r.get("title") or ""
            pid = str(r.get("source_product_id") or "")
            style_code, norm_sku = normalize_sku_and_style(raw_sku, title, pid)

            r["sku"] = norm_sku or style_code or raw_sku

            # Clean and normalize all variants
            raw_vars = r.get("variants") or []
            cleaned_vars = []
            total_stock = 0

            for v in raw_vars:
                v_dict = dict(v) if isinstance(v, dict) else {}
                v_raw_sku = v_dict.get("sku")
                v_st, v_sku = normalize_sku_and_style(v_raw_sku, title, pid)
                v_size = normalize_size(v_dict.get("size"))
                v_stock = int(v_dict.get("stock") or 0)
                total_stock += v_stock

                v_dict["sku"] = v_sku or norm_sku or v_raw_sku
                v_dict["style"] = v_st or style_code
                v_dict["size"] = v_size
                cleaned_vars.append(v_dict)

            r["variants"] = cleaned_vars
            r["updated_at"] = datetime.now(timezone.utc).isoformat()

            if has_new_cols:
                r["style"] = style_code
                r["stock"] = total_stock
                # preserve or set offers
                if "offers" not in r or not r.get("offers"):
                    # check if variants have offers
                    first_offers = next((v.get("offers") for v in cleaned_vars if v.get("offers")), [])
                    r["offers"] = first_offers
            else:
                r.pop("style", None)
                r.pop("stock", None)
                r.pop("offers", None)

        try:
            await cli.upsert("products", rows, on_conflict="scraper_id,source_product_id")
        except Exception as upsert_err:
            if "style" in str(upsert_err) or "stock" in str(upsert_err) or "offers" in str(upsert_err):
                for r in rows:
                    r.pop("style", None)
                    r.pop("stock", None)
                    r.pop("offers", None)
                await cli.upsert("products", rows, on_conflict="scraper_id,source_product_id")
            else:
                raise upsert_err

        total_processed += chunk_len
        offset += chunk_len
        print(f"[BACKFILL] Normalized & updated {total_processed} products...", flush=True)

    dur = round(time.perf_counter() - t_start, 2)
    print("=" * 60)
    print(f"BACKFILL COMPLETED: {total_processed} products normalized in {dur}s")
    print("=" * 60, flush=True)

    # Export canonical backup for columbia
    print("[EXPORT] Updating canonical local backup for Columbia...")
    try:
        await export_canonical_backup("columbia", client=cli)
        print("[EXPORT] Local backup updated successfully!")
    except Exception as e:
        print(f"[EXPORT NOTE] {e}")

    await cli.close()


if __name__ == "__main__":
    asyncio.run(run_backfill())
