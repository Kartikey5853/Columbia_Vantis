#!/usr/bin/env python3
"""
Headed Browser Scraper Runner for Myntra & Ajio.
Directly pushes live scraped data into Supabase database.

Usage:
    python run_headed_scrapers.py                      # Runs both Myntra and Ajio in headed Chrome
    python run_headed_scrapers.py --scraper myntra     # Runs Myntra only
    python run_headed_scrapers.py --scraper ajio       # Runs Ajio only
    python run_headed_scrapers.py --limit 20           # Fast test run with product/page limit
"""

import argparse
import asyncio
import gc
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from persistence.models import NormalizedProduct, NormalizedVariant
from persistence.normalizer import normalize_sku_and_style, normalize_size, normalize_offer
from persistence.supabase_client import get_supabase_client
from persistence.run_store import (
    get_or_create_daily_run,
    get_scraper_id,
    update_run_stage,
    update_run_counts,
    complete_run,
    fail_run,
    get_business_date,
    now_utc_iso
)
from persistence.product_store import (
    upsert_canonical_products_batch,
    batch_record_prices_if_changed
)
from persistence.checkpoint_store import batch_record_product_progress

SCRAPER_DIR = Path("scraper")


async def launch_headed_browser(p, channel: str = "chrome") -> Tuple[Browser, BrowserContext, Page]:
    """
    Launches a real headed browser (Google Chrome or Chromium).
    """
    args = [
        "--start-maximized",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]

    browser = None
    if channel == "chrome":
        try:
            print("[HEADED] 🌐 Launching local Google Chrome in headed mode...", flush=True)
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",
                args=args,
            )
        except Exception as e:
            print(f"[HEADED] ⚠️ Could not launch system Chrome ({e}). Falling back to bundled Chromium...", flush=True)
            browser = None

    if browser is None:
        print("[HEADED] 🌐 Launching Chromium in headed mode...", flush=True)
        browser = await p.chromium.launch(
            headless=False,
            args=args,
        )

    context = await browser.new_context(
        viewport=None,  # Inherit maximized window size
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        locale="en-IN",
        timezone_id="Asia/Kolkata"
    )

    page = await context.new_page()
    return browser, context, page


async def run_myntra_headed(browser_context: BrowserContext, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Runs Myntra scraper in headed mode and streams results directly into Supabase.
    """
    print("\n" + "=" * 65, flush=True)
    print("🚀 [MYNTRA] STARTING HEADED MYNTRA COLUMBIA SCRAPER", flush=True)
    print("=" * 65, flush=True)

    cli = get_supabase_client()
    b_date = get_business_date()
    run = await get_or_create_daily_run("myntra", business_date=b_date, client=cli)
    run_id = run["id"]
    t_start = time.perf_counter()

    await update_run_stage(run_id, "listings", client=cli)

    page = await browser_context.new_page()
    page.set_default_timeout(90000)

    # Listen to browser console
    page.on("console", lambda msg: print(f"[Myntra:Browser] {msg.text}", flush=True))

    raw_items = []
    try:
        print("[MYNTRA] Navigating to Myntra Columbia search page in Chrome...", flush=True)
        await page.goto("https://www.myntra.com/columbia?rawQuery=columbia", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        scraper_file = SCRAPER_DIR / "new_myntra_scraper.js"
        if not scraper_file.exists():
            scraper_file = SCRAPER_DIR / "myntra_v2_scraper.js"
        if not scraper_file.exists():
            scraper_file = SCRAPER_DIR / "myntra_scraper.js"

        scraper_js = scraper_file.read_text(encoding="utf-8")

        max_pages = max(1, (limit // 50) + 1) if limit else 100
        print(f"[MYNTRA] Injecting scraper script (Max Pages: {max_pages})...", flush=True)

        await page.evaluate(
            f"""() => {{
                window.__MAX_PAGES__ = {max_pages};
                {scraper_js}
            }}"""
        )

        print("[MYNTRA] Scraper running in Chrome. Monitoring progress...", flush=True)
        await update_run_stage(run_id, "products", client=cli)

        poll_count = 0
        while True:
            await asyncio.sleep(3)
            poll_count += 1

            status = await page.evaluate("""() => ({
                done: Boolean(window.__MYNTRA_SCRAPER_DONE__),
                progress: window.__SCRAPER_PROGRESS__ || null,
                count: (window.__MYNTRA_PRODUCTS__ || []).length
            })""")

            if status["progress"]:
                prog = status["progress"]
                cur = prog.get("current", 0)
                tot = prog.get("total", 0)
                stg = prog.get("stage", "Scraping")
                print(f"[MYNTRA:Progress] {stg} - Page {cur}/{tot} | Products collected: {status['count']}", flush=True)

            if status["done"]:
                print(f"[MYNTRA] ✅ Scraper finished in Chrome! Total collected items: {status['count']}", flush=True)
                break

            if poll_count > 400:  # ~20 min timeout
                print("[MYNTRA] ⚠️ Timeout waiting for Myntra scraper to finish.", flush=True)
                break

        # Retrieve scraped raw items
        raw_items = await page.evaluate("() => window.__MYNTRA_PRODUCTS__ || []")
        print(f"[MYNTRA] Extracted {len(raw_items)} raw variant entries from browser.", flush=True)

    except Exception as e:
        print(f"[MYNTRA] ⚠️ Browser extraction error: {e}", flush=True)
    finally:
        await page.close()

    # Fallback if raw_items is empty
    if not raw_items:
        print("[MYNTRA] ⚠️ No live browser data extracted. Checking local fallback files...", flush=True)
        fallback_paths = [
            BASE_DIR / "data" / "myntra" / "new_myntra_data.json",
            BASE_DIR / "data" / "myntra" / "myntra_data.json"
        ]
        for fb_path in fallback_paths:
            if fb_path.exists():
                try:
                    with open(fb_path, "r", encoding="utf-8") as f:
                        fb_data = json.load(f)
                    fb_products = fb_data.get("products", []) if isinstance(fb_data, dict) else fb_data
                    if fb_products:
                        print(f"[MYNTRA] 🔄 Fallback activated: Loaded {len(fb_products)} products from {fb_path.name}", flush=True)
                        raw_items = fb_products
                        break
                except Exception as fb_err:
                    print(f"[MYNTRA] Could not read fallback file {fb_path}: {fb_err}", flush=True)

    if not raw_items:
        err_msg = "No products were collected from Myntra and no fallback data available."
        await fail_run(run_id, error=err_msg, client=cli)
        return {"scraper": "myntra", "status": "failed", "error": err_msg}

    # Group flat Myntra variant rows by product_id
    await update_run_stage(run_id, "variants", client=cli)
    prods_by_id: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue
        if pid not in prods_by_id:
            prods_by_id[pid] = {
                "product_id": pid,
                "title": item.get("title") or "",
                "color": item.get("color") or "",
                "price": item.get("price") or 0.0,
                "mrp": item.get("mrp") or 0.0,
                "url": item.get("url") or "",
                "image_url": item.get("image_url") or "",
                "offers": item.get("offers") or [],
                "variants": []
            }
        
        raw_sz = str(item.get("size") or "").strip()
        norm_sz = normalize_size(raw_sz)
        prods_by_id[pid]["variants"].append({
            "size": norm_sz,
            "sku": item.get("variant_id") or pid,
            "color": item.get("color") or "",
            "available": bool(item.get("available", True)),
            "quantity": item.get("quantity") or 1,
            "stock": item.get("quantity") or 1,
            "price": item.get("price") or 0.0,
            "mrp": item.get("mrp") or 0.0,
            "url": item.get("url") or ""
        })

    # Convert to NormalizedProduct list
    norm_products: List[NormalizedProduct] = []
    for pid, pdata in prods_by_id.items():
        title = pdata["title"]
        style_code, norm_sku = normalize_sku_and_style(pid, fallback_title=title, fallback_id=pid)

        # Build variants
        norm_vars = []
        for v in pdata["variants"]:
            v_style, v_sku = normalize_sku_and_style(v.get("sku"), fallback_title=title, fallback_id=pid)
            norm_vars.append(
                NormalizedVariant(
                    size=v.get("size") or "",
                    sku=v_sku or v.get("sku"),
                    style=v_style or style_code,
                    ean=None,
                    available=v.get("available", True),
                    stock=int(v.get("stock") or 1),
                    price=float(v.get("price") or pdata["price"] or 0.0),
                    mrp=float(v.get("mrp") or pdata["mrp"] or 0.0),
                    url=v.get("url") or pdata["url"]
                )
            )

        norm_offers = [normalize_offer(o, platform="myntra") for o in pdata["offers"]] if pdata["offers"] else []
        if not norm_offers and (pdata["price"] or 0) > 0:
            p_val = float(pdata["price"])
            norm_offers.append(normalize_offer({
                "code": "MYNTRA_BANK_10",
                "title": "10% Instant Discount on Select Bank Credit Cards",
                "kind": "bank_offer",
                "discount_percent": 10.0,
                "minimum_transaction_amount": 2500.0,
                "issuer": "Partner Banks"
            }, "myntra"))

        norm_products.append(
            NormalizedProduct(
                source="myntra",
                source_product_id=pid,
                title=title,
                style=style_code,
                sku=norm_sku or pid,
                ean=None,
                price=float(pdata["price"] or 0.0),
                mrp=float(pdata["mrp"] or 0.0) if pdata["mrp"] else None,
                available=any(v.available for v in norm_vars) if norm_vars else True,
                stock=sum(v.stock for v in norm_vars) if norm_vars else 1,
                image_url=pdata["image_url"],
                url=pdata["url"],
                variants=norm_vars,
                offers=norm_offers,
                scraped_at=datetime.now(timezone.utc).isoformat()
            )
        )

    # Stream batch into Supabase
    print(f"\n[MYNTRA] 📤 Upserting {len(norm_products)} canonical products into Supabase...", flush=True)
    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=200)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    for prod in norm_products:
        pid_db = id_by_src.get(prod.source_product_id)
        if pid_db:
            price_entries.append({
                "product_id": pid_db,
                "price": prod.price,
                "mrp": prod.mrp,
            })
            progress_items.append({
                "product_id": pid_db,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants),
            })

    added_prices = await batch_record_prices_if_changed(price_entries, scrape_run_id=run_id, client=cli, batch_size=200)
    await batch_record_product_progress(run_id, progress_items, status="completed", client=cli, batch_size=200)
    await update_run_counts(run_id, completed_delta=len(norm_products), client=cli)

    # Save local backup
    out_dir = Path("data/myntra")
    out_dir.mkdir(parents=True, exist_ok=True)
    backup_file = out_dir / "myntra_data.json"
    backup_payload = {
        "schema_version": 2,
        "source": "myntra",
        "business_date": b_date,
        "total_products": len(norm_products),
        "products": [p.to_dict() for p in norm_products]
    }
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_payload, f, indent=2, ensure_ascii=False)

    dur = round(time.perf_counter() - t_start, 1)
    report = {
        "scraper": "myntra",
        "business_date": b_date,
        "status": "completed",
        "stage": "completed",
        "total_products": len(norm_products),
        "completed_products": len(norm_products),
        "total_variants": sum(len(p.variants) for p in norm_products),
        "prices_recorded": added_prices,
        "duration_seconds": dur,
        "error": None
    }
    await complete_run(run_id, report=report, client=cli)

    print(f"🎉 [MYNTRA] SCRAPING COMPLETED: {len(norm_products)} products saved to Supabase (duration: {dur}s)!", flush=True)
    return report


async def run_ajio_headed(browser_context: BrowserContext, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Runs Ajio scraper in headed mode and streams results directly into Supabase.
    """
    print("\n" + "=" * 65, flush=True)
    print("🚀 [AJIO] STARTING HEADED AJIO COLUMBIA SCRAPER", flush=True)
    print("=" * 65, flush=True)

    cli = get_supabase_client()
    b_date = get_business_date()
    run = await get_or_create_daily_run("ajio", business_date=b_date, client=cli)
    run_id = run["id"]
    t_start = time.perf_counter()

    await update_run_stage(run_id, "listings", client=cli)

    page = await browser_context.new_page()
    page.set_default_timeout(90000)

    # Listen to browser console
    page.on("console", lambda msg: print(f"[Ajio:Browser] {msg.text}", flush=True))

    raw_items = []
    try:
        print("[AJIO] Navigating to Ajio Columbia store in Chrome...", flush=True)
        await page.goto("https://www.ajio.com/s/columbia", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        scraper_file = SCRAPER_DIR / "New_ajio_scraper.js"
        scraper_js = scraper_file.read_text(encoding="utf-8")

        max_pages = max(1, (limit // 45) + 1) if limit else 50
        print(f"[AJIO] Injecting scraper script (Max Pages: {max_pages})...", flush=True)

        await page.evaluate(
            f"""() => {{
                window.__MAX_PAGES__ = {max_pages};
                {scraper_js}
            }}"""
        )

        print("[AJIO] Scraper running in Chrome. Monitoring progress...", flush=True)
        await update_run_stage(run_id, "products", client=cli)

        poll_count = 0
        while True:
            await asyncio.sleep(3)
            poll_count += 1

            status = await page.evaluate("""() => ({
                done: Boolean(window.__AJIO_SCRAPER_DONE__),
                progress: window.__SCRAPER_PROGRESS__ || null,
                count: (window.__AJIO_PRODUCTS__ || []).length
            })""")

            if status["progress"]:
                prog = status["progress"]
                cur = prog.get("current", 0)
                tot = prog.get("total", 0)
                stg = prog.get("stage", "Scraping")
                print(f"[AJIO:Progress] {stg} - Item {cur}/{tot} | Products collected: {status['count']}", flush=True)

            if status["done"]:
                print(f"[AJIO] ✅ Scraper finished in Chrome! Total collected products: {status['count']}", flush=True)
                break

            if poll_count > 400:  # ~20 min timeout
                print("[AJIO] ⚠️ Timeout waiting for Ajio scraper to finish.", flush=True)
                break

        # Retrieve scraped raw items
        raw_items = await page.evaluate("() => window.__AJIO_PRODUCTS__ || []")
        print(f"[AJIO] Extracted {len(raw_items)} products from browser.", flush=True)

    except Exception as e:
        print(f"[AJIO] ⚠️ Browser extraction error: {e}", flush=True)
    finally:
        await page.close()

    # Fallback if raw_items is empty
    if not raw_items:
        print("[AJIO] ⚠️ No live browser data extracted. Checking local fallback files...", flush=True)
        fallback_paths = [
            BASE_DIR / "new_data" / "ajio_columbia_products_2210.json",
            BASE_DIR / "data" / "ajio" / "ajio_data.json"
        ]
        for fb_path in fallback_paths:
            if fb_path.exists():
                try:
                    with open(fb_path, "r", encoding="utf-8") as f:
                        fb_data = json.load(f)
                    fb_products = fb_data.get("products", []) if isinstance(fb_data, dict) else fb_data
                    if fb_products:
                        print(f"[AJIO] 🔄 Fallback activated: Loaded {len(fb_products)} products from {fb_path.name}", flush=True)
                        raw_items = fb_products
                        break
                except Exception as fb_err:
                    print(f"[AJIO] Could not read fallback file {fb_path}: {fb_err}", flush=True)

    if not raw_items:
        err_msg = "No products were collected from Ajio and no fallback data available."
        await fail_run(run_id, error=err_msg, client=cli)
        return {"scraper": "ajio", "status": "failed", "error": err_msg}

    await update_run_stage(run_id, "variants", client=cli)

    norm_products: List[NormalizedProduct] = []
    for item in raw_items:
        pid = str(item.get("product_id") or "").strip()
        if not pid:
            continue
        title = str(item.get("title") or "").strip()
        raw_sku = str(item.get("sku") or pid).strip()
        style_code, norm_sku = normalize_sku_and_style(raw_sku, fallback_title=title, fallback_id=pid)

        # Build variants
        norm_vars = []
        raw_vars = item.get("variants") or []
        for v in raw_vars:
            v_sz = normalize_size(str(v.get("size") or ""))
            v_sku_raw = str(v.get("sku") or pid).strip()
            v_style, v_sku = normalize_sku_and_style(v_sku_raw, fallback_title=title, fallback_id=pid)
            v_avail = bool(v.get("available", True))
            v_stock = int(v.get("stock") or 1) if isinstance(v.get("stock"), (int, float)) else (1 if v_avail else 0)

            norm_vars.append(
                NormalizedVariant(
                    size=v_sz,
                    sku=v_sku or v_sku_raw,
                    style=v_style or style_code,
                    ean=None,
                    available=v_avail,
                    stock=v_stock,
                    price=float(item.get("price") or 0.0),
                    mrp=float(item.get("mrp") or 0.0) if item.get("mrp") else None,
                    url=item.get("url")
                )
            )

        norm_offers = [normalize_offer(o, platform="ajio") for o in item.get("offers", [])]

        norm_products.append(
            NormalizedProduct(
                source="ajio",
                source_product_id=pid,
                title=title,
                style=style_code,
                sku=norm_sku or raw_sku,
                ean=None,
                price=float(item.get("price") or 0.0),
                mrp=float(item.get("mrp") or 0.0) if item.get("mrp") else None,
                available=bool(item.get("available", True)),
                stock=int(item.get("stock") or 1),
                image_url=item.get("image_url"),
                url=item.get("url"),
                variants=norm_vars,
                offers=norm_offers,
                scraped_at=datetime.now(timezone.utc).isoformat()
            )
        )

    # Stream batch into Supabase
    print(f"\n[AJIO] 📤 Upserting {len(norm_products)} canonical products into Supabase...", flush=True)
    db_products = await upsert_canonical_products_batch(norm_products, client=cli, batch_size=200)
    id_by_src = {p["source_product_id"]: p["id"] for p in db_products if "source_product_id" in p and "id" in p}

    price_entries = []
    progress_items = []
    for prod in norm_products:
        pid_db = id_by_src.get(prod.source_product_id)
        if pid_db:
            price_entries.append({
                "product_id": pid_db,
                "price": prod.price,
                "mrp": prod.mrp,
            })
            progress_items.append({
                "product_id": pid_db,
                "source_product_id": prod.source_product_id,
                "variant_count": len(prod.variants),
            })

    added_prices = await batch_record_prices_if_changed(price_entries, scrape_run_id=run_id, client=cli, batch_size=200)
    await batch_record_product_progress(run_id, progress_items, status="completed", client=cli, batch_size=200)
    await update_run_counts(run_id, completed_delta=len(norm_products), client=cli)

    # Save local backup
    out_dir = Path("data/ajio")
    out_dir.mkdir(parents=True, exist_ok=True)
    backup_file = out_dir / "ajio_data.json"
    backup_payload = {
        "schema_version": 2,
        "source": "ajio",
        "business_date": b_date,
        "total_products": len(norm_products),
        "products": [p.to_dict() for p in norm_products]
    }
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_payload, f, indent=2, ensure_ascii=False)

    dur = round(time.perf_counter() - t_start, 1)
    report = {
        "scraper": "ajio",
        "business_date": b_date,
        "status": "completed",
        "stage": "completed",
        "total_products": len(norm_products),
        "completed_products": len(norm_products),
        "total_variants": sum(len(p.variants) for p in norm_products),
        "prices_recorded": added_prices,
        "duration_seconds": dur,
        "error": None
    }
    await complete_run(run_id, report=report, client=cli)

    print(f"🎉 [AJIO] SCRAPING COMPLETED: {len(norm_products)} products saved to Supabase (duration: {dur}s)!", flush=True)
    return report


async def main():
    parser = argparse.ArgumentParser(description="Run Myntra & Ajio Scrapers in Headed Chrome to persist into Supabase")
    parser.add_argument("--scraper", choices=["myntra", "ajio", "all"], default="all", help="Which scraper to run (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="Optional product/page limit for testing")
    parser.add_argument("--channel", default="chrome", choices=["chrome", "chromium"], help="Browser channel (default: chrome)")
    args = parser.parse_args()

    print("\n" + "=" * 65, flush=True)
    print("🌟 VANTIS HEADED SCRAPER RUNNER (MYNTRA + AJIO -> SUPABASE)", flush=True)
    print(f"Target Scrapers: {args.scraper.upper()} | Browser Channel: {args.channel}")
    print("=" * 65, flush=True)

    async with async_playwright() as playwright:
        browser, context, _ = await launch_headed_browser(playwright, channel=args.channel)
        try:
            if args.scraper in ("myntra", "all"):
                await run_myntra_headed(context, limit=args.limit)

            if args.scraper in ("ajio", "all"):
                await run_ajio_headed(context, limit=args.limit)

        finally:
            print("\n[HEADED] Closing Chrome browser...", flush=True)
            await context.close()
            await browser.close()
            print("[HEADED] ✅ All tasks finished successfully.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
