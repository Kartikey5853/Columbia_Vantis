#!/usr/bin/env python3
"""
Columbia Scraper Desktop Application
Built with PySide6 & Playwright.
Executes new_myntra_scraper.js and New_ajio_scraper.js in a persistent browser session.
Extracts all real variant sizes, special offers, and syncs directly to Supabase via duplicate-safe upserts.
"""

import sys
import os
import json
import time
import re
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv
load_dotenv()

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QIcon, QTextCursor, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit, QFrame,
    QGridLayout, QGroupBox, QMessageBox
)

import httpx

# =========================================================================
# PATHS & CONFIGURATION
# =========================================================================
LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
APP_DATA_DIR = Path(LOCAL_APP_DATA) / "ProductScraper"
BROWSER_PROFILE_DIR = APP_DATA_DIR / "BrowserProfile"
BACKUP_DATA_DIR = APP_DATA_DIR / "Data"

APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DATA_DIR.mkdir(parents=True, exist_ok=True)

SCRAPER_DIR = Path(__file__).resolve().parent / "scrapers"
if not SCRAPER_DIR.exists():
    SCRAPER_DIR = Path(__file__).resolve().parent.parent / "scraper"

# Supabase Credentials (from environment or defaults)
SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or "https://viflznbwqrunivhfoavq.supabase.co").rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or "sb_secret_wgDvOA3l28p2d2jzH5euRg_mgqeBpLF"
)

SCRAPER_IDS = {
    "ajio": "597a2ed9-be23-442a-9360-9fb84a39b4ef",
    "myntra": "da9da872-910d-4b62-8966-253c4cae9bc3"
}


# =========================================================================
# DATA NORMALIZATION HELPERS
# =========================================================================
def extract_ajio_size(seller_sku: str, title: str = "") -> str:
    """Extracts true size from Ajio SKU (e.g. BM6388-010-9 -> 9, WE5258-429-M -> M)."""
    if seller_sku:
        parts = seller_sku.strip().split("-")
        if len(parts) >= 3:
            cand = parts[2].strip()
            # Clean trailing batch indicators (e.g. LN -> L, MN -> M, 32N -> 32)
            cleaned = re.sub(r"[Nn]+$", "", cand).strip() or cand
            if cleaned.upper() == "OS":
                return "One Size"
            if cleaned:
                return cleaned

    if title:
        m = re.search(r"\b(?:Size|UK|US)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?|[SMLX|XXL|XXXL|XS]+)\b", title, re.IGNORECASE)
        if m:
            return m.group(1).upper()

    return "One Size"


def normalize_offers(raw_offers: List[Any], platform: str) -> List[Dict[str, Any]]:
    """Normalizes coupon and promotional offers."""
    norm = []
    seen = set()
    for o in raw_offers:
        if not isinstance(o, dict):
            continue
        title = o.get("title") or o.get("description") or o.get("code") or "Special Offer"
        code = o.get("code") or ""
        key = (code, title[:60])
        if key in seen:
            continue
        seen.add(key)

        kind = o.get("type") or o.get("kind") or ("coupon" if code else "discount")
        norm.append({
            "code": code or None,
            "title": title,
            "kind": str(kind).lower(),
            "description": o.get("description") or title,
            "discount_amount": o.get("discount") or o.get("discount_amount"),
            "discount_percent": o.get("discount_percent"),
            "minimum_transaction_amount": o.get("min_purchase") or o.get("minimum_transaction_amount"),
            "maximum_discount": o.get("max_discount") or o.get("maximum_discount"),
            "issuer": o.get("bank") or o.get("issuer"),
            "offer_price": o.get("offer_price")
        })
    return norm


# =========================================================================
# SUPABASE SYNC WORKER
# =========================================================================
async def sync_products_to_supabase(
    products: List[Dict[str, Any]],
    source: str,
    log_func=print
) -> Dict[str, int]:
    """
    Duplicate-safe upsert of products into Supabase using source_product_id + scraper_id.
    """
    scraper_id = SCRAPER_IDS.get(source, SCRAPER_IDS["ajio"])
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
    }

    upserted_count = 0
    price_history_count = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Batch into chunks of 100
        for i in range(0, len(products), 100):
            chunk = products[i:i + 100]
            db_rows = []
            for p in chunk:
                pid = str(p.get("product_id") or p.get("source_product_id") or "").strip()
                if not pid:
                    continue

                price = float(p.get("price") or 0.0)
                mrp = float(p.get("mrp") or price) if p.get("mrp") else price
                available = bool(p.get("available", True))

                db_rows.append({
                    "scraper_id": scraper_id,
                    "source_product_id": pid,
                    "title": p.get("title") or "Columbia Product",
                    "sku": p.get("sku") or pid,
                    "style": p.get("style") or (p.get("sku") or pid).split("-")[0],
                    "ean": p.get("ean") or None,
                    "url": p.get("url") or "",
                    "image_url": p.get("image_url") or "",
                    "available": available,
                    "current_price": price,
                    "current_mrp": mrp,
                    "stock": int(p.get("stock") or (1 if available else 0)),
                    "variants": p.get("variants") or [],
                    "offers": p.get("offers") or [],
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })

            if not db_rows:
                continue

            try:
                r = await client.post(
                    f"{SUPABASE_URL}/rest/v1/products?on_conflict=scraper_id,source_product_id",
                    headers=headers,
                    json=db_rows
                )
                if r.status_code in (200, 201):
                    res_json = r.json() or []
                    upserted_count += len(res_json)

                    # Also record price_history
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
                        r_h = await client.post(
                            f"{SUPABASE_URL}/rest/v1/price_history",
                            headers=headers,
                            json=hist_rows
                        )
                        if r_h.status_code in (200, 201):
                            price_history_count += len(hist_rows)

                else:
                    log_func(f"[Supabase] ⚠️ Upsert error ({r.status_code}): {r.text[:200]}")
            except Exception as e:
                log_func(f"[Supabase] ⚠️ Network error during sync: {e}")

    return {"upserted": upserted_count, "price_history": price_history_count}


# =========================================================================
# BACKGROUND SCRAPER THREAD
# =========================================================================
class ScraperWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int, int, str)
    stats_signal = Signal(int, int, int, int)  # products, variants, offers, synced
    finished_signal = Signal(bool, str)

    def __init__(self, target: str):
        super().__init__()
        self.target = target  # "myntra", "ajio", or "both"
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def run(self):
        asyncio.run(self._execute())

    async def _execute(self):
        from playwright.async_api import async_playwright

        self.log_signal.emit(f"🚀 Starting Scraper Task for [{self.target.upper()}]...")
        self.log_signal.emit(f"📁 Browser profile: {BROWSER_PROFILE_DIR}")

        targets = ["myntra", "ajio"] if self.target == "both" else [self.target]

        async with async_playwright() as p:
            try:
                self.log_signal.emit("🌐 Launching Persistent Browser Profile...")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR),
                    headless=False,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox"
                    ],
                    viewport=None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    locale="en-IN",
                    timezone_id="Asia/Kolkata"
                )
            except Exception as e:
                self.log_signal.emit(f"❌ Failed to launch browser: {e}")
                self.finished_signal.emit(False, str(e))
                return

            try:
                for target_name in targets:
                    if self._is_stopped:
                        self.log_signal.emit("⏹️ Scraping interrupted by user.")
                        break

                    if target_name == "ajio":
                        await self._scrape_ajio(context)
                    elif target_name == "myntra":
                        await self._scrape_myntra(context)

                self.log_signal.emit("🎉 Scraping and Synchronization Finished Successfully!")
                self.finished_signal.emit(True, "All operations completed.")
            except Exception as e:
                self.log_signal.emit(f"❌ Scraping error: {e}")
                self.finished_signal.emit(False, str(e))
            finally:
                await context.close()

    async def _scrape_ajio(self, context):
        self.log_signal.emit("\n==========================================")
        self.log_signal.emit("▶️ STARTING AJIO SCRAPING")
        self.log_signal.emit("==========================================")

        page = await context.new_page()
        page.on("console", lambda msg: self.log_signal.emit(f"[Ajio Console] {msg.text}"))

        try:
            self.log_signal.emit("🔍 Navigating to Ajio Columbia Store...")
            await page.goto("https://www.ajio.com/search/?text=columbia", wait_until="domcontentloaded", timeout=45000)

            js_file = SCRAPER_DIR / "New_ajio_scraper.js"
            if not js_file.exists():
                raise FileNotFoundError(f"Scraper script not found: {js_file}")

            with open(js_file, "r", encoding="utf-8") as f:
                script_content = f.read()

            self.log_signal.emit("💉 Injecting New_ajio_scraper.js into active tab...")
            await page.evaluate(f"() => {{ {script_content} }}")

            # Monitor progress
            poll_count = 0
            while not self._is_stopped:
                await asyncio.sleep(2)
                poll_count += 1

                status = await page.evaluate("""() => ({
                    done: Boolean(window.__AJIO_SCRAPER_DONE__),
                    progress: window.__SCRAPER_PROGRESS__ || null,
                    count: (window.__AJIO_PRODUCTS__ || []).length
                })""")

                if status.get("progress"):
                    prog = status["progress"]
                    cur = prog.get("current", 0)
                    tot = prog.get("total", 1)
                    stg = prog.get("stage", "Scraping")
                    self.progress_signal.emit(cur, tot, f"Ajio: {stg} ({cur}/{tot})")
                    self.log_signal.emit(f"[Ajio Progress] {stg}: Page {cur}/{tot} | Products collected: {status['count']}")

                if status.get("done") or poll_count > 450:
                    break

            raw_items = await page.evaluate("() => window.__AJIO_PRODUCTS__ || []")
            self.log_signal.emit(f"📦 Extracted {len(raw_items)} raw items from Ajio browser.")

        finally:
            await page.close()

        # Fallback to local file if empty
        if not raw_items:
            fallback = Path("new_data") / "ajio_columbia_products_2210.json"
            if fallback.exists():
                self.log_signal.emit(f"🔄 Activating local fallback file: {fallback}")
                with open(fallback, "r", encoding="utf-8") as f:
                    fb_data = json.load(f)
                raw_items = fb_data.get("products", []) if isinstance(fb_data, dict) else fb_data

        # Process and enrich variants & offers
        processed_products = []
        total_variants = 0
        total_offers = 0

        # Group by base style-color to combine all sizes
        grouped = {}
        for item in raw_items:
            pid = str(item.get("product_id") or "").strip()
            if not pid:
                continue

            sku = str(item.get("sku") or pid).strip()
            title = str(item.get("title") or "").strip()
            price = float(item.get("price") or 0.0)
            mrp = float(item.get("mrp") or price) if item.get("mrp") else price

            # Extract true size from SKU
            true_size = extract_ajio_size(sku, title)
            offers = normalize_offers(item.get("offers") or [], platform="ajio")

            base_key = sku.split("-")[0] if "-" in sku else pid
            if base_key not in grouped:
                grouped[base_key] = {
                    "source": "ajio",
                    "product_id": pid,
                    "sku": sku,
                    "style": base_key,
                    "title": title,
                    "price": price,
                    "mrp": mrp,
                    "available": bool(item.get("available", True)),
                    "url": item.get("url") or "",
                    "image_url": item.get("image_url") or "",
                    "offers": offers,
                    "variants": []
                }

            grouped[base_key]["variants"].append({
                "size": true_size,
                "sku": sku,
                "price": price,
                "mrp": mrp,
                "available": bool(item.get("available", True)),
                "quantity": int(item.get("stock") or 1),
                "stock": int(item.get("stock") or 1)
            })

            total_variants += 1
            total_offers += len(offers)

        processed_products = list(grouped.values())
        self.log_signal.emit(f"✨ Consolidated into {len(processed_products)} unique product families with {total_variants} variant sizes and {total_offers} offers.")

        # Local JSON backup
        backup_file = BACKUP_DATA_DIR / f"ajio_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        latest_file = BACKUP_DATA_DIR / "ajio_data.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump({"products": processed_products}, f, indent=2)
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump({"products": processed_products}, f, indent=2)
        self.log_signal.emit(f"💾 Saved local JSON backup to {backup_file.name}")

        # Supabase sync
        self.log_signal.emit("☁️ Syncing canonical products to Supabase...")
        sync_res = await sync_products_to_supabase(processed_products, "ajio", log_func=self.log_signal.emit)
        self.log_signal.emit(f"✅ Supabase Sync Completed: {sync_res['upserted']} products upserted, {sync_res['price_history']} price history records created.")
        self.stats_signal.emit(len(processed_products), total_variants, total_offers, sync_res["upserted"])

    async def _scrape_myntra(self, context):
        self.log_signal.emit("\n==========================================")
        self.log_signal.emit("▶️ STARTING MYNTRA SCRAPING")
        self.log_signal.emit("==========================================")

        page = await context.new_page()
        page.on("console", lambda msg: self.log_signal.emit(f"[Myntra Console] {msg.text}"))

        try:
            self.log_signal.emit("🔍 Navigating to Myntra Columbia Store...")
            await page.goto("https://www.myntra.com/columbia", wait_until="domcontentloaded", timeout=45000)

            js_file = SCRAPER_DIR / "new_myntra_scraper.js"
            if not js_file.exists():
                raise FileNotFoundError(f"Scraper script not found: {js_file}")

            with open(js_file, "r", encoding="utf-8") as f:
                script_content = f.read()

            self.log_signal.emit("💉 Injecting new_myntra_scraper.js into active tab...")
            await page.evaluate(f"() => {{ {script_content} }}")

            poll_count = 0
            while not self._is_stopped:
                await asyncio.sleep(2)
                poll_count += 1

                status = await page.evaluate("""() => ({
                    done: Boolean(window.__MYNTRA_SCRAPER_DONE__),
                    progress: window.__SCRAPER_PROGRESS__ || null,
                    count: (window.__MYNTRA_PRODUCTS__ || []).length
                })""")

                if status.get("progress"):
                    prog = status["progress"]
                    cur = prog.get("current", 0)
                    tot = prog.get("total", 1)
                    stg = prog.get("stage", "Scraping")
                    self.progress_signal.emit(cur, tot, f"Myntra: {stg} ({cur}/{tot})")
                    self.log_signal.emit(f"[Myntra Progress] {stg}: Item {cur}/{tot} | Variants: {status['count']}")

                if status.get("done") or poll_count > 450:
                    break

            raw_items = await page.evaluate("() => window.__MYNTRA_PRODUCTS__ || []")
            self.log_signal.emit(f"📦 Extracted {len(raw_items)} variant records from Myntra browser.")

        finally:
            await page.close()

        # Group flat variants into canonical products
        prods_by_id = {}
        total_variants = 0
        total_offers = 0

        for item in raw_items:
            pid = str(item.get("product_id") or "").strip()
            if not pid:
                continue

            title = item.get("title") or ""
            price = float(item.get("price") or 0.0)
            mrp = float(item.get("mrp") or price) if item.get("mrp") else price
            offers = normalize_offers(item.get("offers") or [], platform="myntra")

            if pid not in prods_by_id:
                prods_by_id[pid] = {
                    "source": "myntra",
                    "product_id": pid,
                    "title": title,
                    "sku": item.get("variant_id") or pid,
                    "style": pid,
                    "price": price,
                    "mrp": mrp,
                    "available": bool(item.get("available", True)),
                    "url": item.get("url") or "",
                    "image_url": item.get("image_url") or "",
                    "offers": offers,
                    "variants": []
                }
                total_offers += len(offers)

            sz = str(item.get("size") or "Onesize").strip()
            prods_by_id[pid]["variants"].append({
                "size": sz,
                "sku": item.get("variant_id") or pid,
                "color": item.get("color") or "",
                "available": bool(item.get("available", True)),
                "quantity": int(item.get("quantity") or 1),
                "stock": int(item.get("quantity") or 1),
                "price": price,
                "mrp": mrp
            })
            total_variants += 1

        processed_products = list(prods_by_id.values())
        self.log_signal.emit(f"✨ Consolidated {len(raw_items)} variant entries into {len(processed_products)} products with full size variants and {total_offers} offers.")

        # Local JSON backup
        backup_file = BACKUP_DATA_DIR / f"myntra_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        latest_file = BACKUP_DATA_DIR / "myntra_data.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump({"products": processed_products}, f, indent=2)
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump({"products": processed_products}, f, indent=2)
        self.log_signal.emit(f"💾 Saved local JSON backup to {backup_file.name}")

        # Supabase sync
        self.log_signal.emit("☁️ Syncing canonical products to Supabase...")
        sync_res = await sync_products_to_supabase(processed_products, "myntra", log_func=self.log_signal.emit)
        self.log_signal.emit(f"✅ Supabase Sync Completed: {sync_res['upserted']} products upserted, {sync_res['price_history']} price history records created.")
        self.stats_signal.emit(len(processed_products), total_variants, total_offers, sync_res["upserted"])


# =========================================================================
# MAIN GUI WINDOW
# =========================================================================
class ProductScraperMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Columbia E-Commerce Scraper • Desktop Studio")
        self.resize(1000, 720)
        self.setMinimumSize(850, 600)

        self.worker: Optional[ScraperWorker] = None
        self._init_ui()

    def _init_ui(self):
        # Dark modern styling with clean slate/sky palette
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f172a;
            }
            QWidget {
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                font-size: 13px;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #475569;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: 600;
                font-size: 13px;
                color: #f1f5f9;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38bdf8;
            }
            QPushButton:pressed {
                background-color: #0284c7;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                border-color: #334155;
                color: #64748b;
            }
            QPushButton#primaryBtn {
                background-color: #0284c7;
                border-color: #38bdf8;
                color: #ffffff;
            }
            QPushButton#primaryBtn:hover {
                background-color: #0369a1;
            }
            QPushButton#dangerBtn {
                background-color: #991b1b;
                border-color: #f87171;
                color: #ffffff;
            }
            QPushButton#dangerBtn:hover {
                background-color: #7f1d1d;
            }
            QProgressBar {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                text-align: center;
                height: 22px;
                font-size: 11px;
                font-weight: bold;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 7px;
            }
            QTextEdit {
                background-color: #090d16;
                border: 1px solid #1e293b;
                border-radius: 8px;
                color: #94a3b8;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
                padding: 8px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 1. Header Bar
        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_label = QLabel("Columbia Scraper Studio")
        title_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #38bdf8;")
        subtitle_label = QLabel("Persistent Headed Chromium • Ajio & Myntra Live Sync to Supabase")
        subtitle_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        # Profile location badge
        badge_box = QVBoxLayout()
        badge_box.setAlignment(Qt.AlignRight)
        profile_lbl = QLabel(f"Profile: %LOCALAPPDATA%\\ProductScraper\\BrowserProfile")
        profile_lbl.setStyleSheet("font-size: 11px; color: #64748b; font-family: monospace;")
        db_lbl = QLabel(f"Supabase: Connected ({SUPABASE_URL.split('//')[-1].split('.')[0]})")
        db_lbl.setStyleSheet("font-size: 11px; color: #10b981; font-weight: bold;")
        badge_box.addWidget(profile_lbl)
        badge_box.addWidget(db_lbl)
        header_layout.addLayout(badge_box)

        main_layout.addLayout(header_layout)

        # 2. Control Actions Group
        controls_group = QGroupBox("Desktop Operations & Scraping Controls")
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(12)
        controls_layout.setContentsMargins(15, 20, 15, 15)

        self.btn_browser = QPushButton("🌐 Open Browser")
        self.btn_browser.setToolTip("Opens visible browser to sign in, solve CAPTCHAs & persist cookies")
        self.btn_browser.clicked.connect(self.open_browser)

        self.btn_scrape_myntra = QPushButton("Scrape Myntra")
        self.btn_scrape_myntra.setObjectName("primaryBtn")
        self.btn_scrape_myntra.clicked.connect(lambda: self.start_scraping("myntra"))

        self.btn_scrape_ajio = QPushButton("Scrape AJIO")
        self.btn_scrape_ajio.setObjectName("primaryBtn")
        self.btn_scrape_ajio.clicked.connect(lambda: self.start_scraping("ajio"))

        self.btn_scrape_both = QPushButton("Scrape Both (Full Sync)")
        self.btn_scrape_both.setObjectName("primaryBtn")
        self.btn_scrape_both.clicked.connect(lambda: self.start_scraping("both"))

        self.btn_stop = QPushButton("⏹️ Stop Scraping")
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scraping)

        controls_layout.addWidget(self.btn_browser)
        controls_layout.addWidget(self.btn_scrape_myntra)
        controls_layout.addWidget(self.btn_scrape_ajio)
        controls_layout.addWidget(self.btn_scrape_both)
        controls_layout.addWidget(self.btn_stop)

        main_layout.addWidget(controls_group)

        # 3. Stats Dashboard Cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)

        self.card_products = self._create_stat_card("Products Collected", "0", "#38bdf8")
        self.card_variants = self._create_stat_card("Variant Sizes", "0", "#a855f7")
        self.card_offers = self._create_stat_card("Special Offers", "0", "#f59e0b")
        self.card_synced = self._create_stat_card("Supabase Upserts", "0", "#10b981")

        stats_layout.addWidget(self.card_products)
        stats_layout.addWidget(self.card_variants)
        stats_layout.addWidget(self.card_offers)
        stats_layout.addWidget(self.card_synced)

        main_layout.addLayout(stats_layout)

        # 4. Progress Bar & Stage Status
        progress_box = QVBoxLayout()
        self.status_label = QLabel("Ready • Click 'Open Browser' to inspect session, or start a scraping job.")
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        progress_box.addWidget(self.status_label)
        progress_box.addWidget(self.progress_bar)
        main_layout.addLayout(progress_box)

        # 5. Live Activity Log Terminal
        log_group = QGroupBox("Live Activity Terminal")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 15, 10, 10)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(log_group, stretch=1)

        self.append_log("✨ Columbia Scraper Desktop Application Initialized.")
        self.append_log(f"📁 Local persistent session directory: {BROWSER_PROFILE_DIR}")
        self.append_log(f"💾 Local data backup directory: {BACKUP_DATA_DIR}")
        self.append_log(f"🔗 Target Supabase URL: {SUPABASE_URL}")

    def _create_stat_card(self, title: str, value: str, accent_color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #1e293b;
                border: 1px solid #334155;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {accent_color};")
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 11px; color: #94a3b8; font-weight: 600;")

        layout.addWidget(lbl_val)
        layout.addWidget(lbl_title)
        frame.lbl_val = lbl_val
        return frame

    def append_log(self, text: str):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        self.log_text.moveCursor(QTextCursor.End)

    def open_browser(self):
        """Launches a standalone visible browser window to let user browse, sign in, or solve CAPTCHAs."""
        self.append_log("🌐 Launching interactive browser for authentication...")
        import subprocess
        # Launch headed playwright in separate non-blocking process
        launcher_code = f"""
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=r'{BROWSER_PROFILE_DIR}',
            headless=False,
            args=['--start-maximized', '--no-sandbox']
        )
        page = await ctx.new_page()
        await page.goto('https://www.google.com')
        # Wait until browser is manually closed by user
        while len(ctx.pages) > 0:
            await asyncio.sleep(1)

asyncio.run(run())
"""
        subprocess.Popen([sys.executable, "-c", launcher_code])
        self.append_log("✅ Interactive browser window launched. Sign in to your accounts and close when done.")

    def start_scraping(self, target: str):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Job In Progress", "A scraping task is already running.")
            return

        self.btn_browser.setEnabled(False)
        self.btn_scrape_myntra.setEnabled(False)
        self.btn_scrape_ajio.setEnabled(False)
        self.btn_scrape_both.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.progress_bar.setValue(0)
        self.status_label.setText(f"Initializing scraping job for {target.upper()}...")

        self.worker = ScraperWorker(target)
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.stats_signal.connect(self.on_stats)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_scraping(self):
        if self.worker and self.worker.isRunning():
            self.append_log("⚠️ Stopping scraping task... waiting for safe cleanup.")
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    @Slot(int, int, str)
    def on_progress(self, current: int, total: int, stage_text: str):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        self.status_label.setText(stage_text)

    @Slot(int, int, int, int)
    def on_stats(self, prods: int, vars_cnt: int, offers: int, synced: int):
        self.card_products.lbl_val.setText(str(prods))
        self.card_variants.lbl_val.setText(str(vars_cnt))
        self.card_offers.lbl_val.setText(str(offers))
        self.card_synced.lbl_val.setText(str(synced))

    @Slot(bool, str)
    def on_finished(self, success: bool, message: str):
        self.btn_browser.setEnabled(True)
        self.btn_scrape_myntra.setEnabled(True)
        self.btn_scrape_ajio.setEnabled(True)
        self.btn_scrape_both.setEnabled(True)
        self.btn_stop.setEnabled(False)

        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText("Completed successfully.")
            QMessageBox.information(self, "Task Finished", "Scraping and Supabase synchronization completed!")
        else:
            self.status_label.setText(f"Finished with issues: {message}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ColumbiaScraperStudio")
    window = ProductScraperMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
