import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright

# Support frozen execution (PyInstaller)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

SCRAPER_DIR = BASE_DIR / "scrapers"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROME_PROFILE_DIR = BASE_DIR / "chrome_profile"
CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Import local Supabase synchronization
from supabase_sync import sync_products_to_supabase, record_scrape_run

CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--password-store=basic",
]


async def launch_persistent_chrome(playwright_instance, headless: bool = False):
    """
    Launches Google Chrome using the local persistent profile.
    Cookies, Gmail login, and session tokens persist inside chrome_profile/.
    """
    print(f"\n[CHROME] Launching local Google Chrome with persistent profile: {CHROME_PROFILE_DIR.name}/")
    context = await playwright_instance.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE_DIR),
        channel="chrome",
        headless=headless,
        viewport={"width": 1400, "height": 900},
        args=CHROME_ARGS,
        ignore_default_args=["--enable-automation"],
    )
    return context


async def login_session_mode():
    """
    Opens Chrome headed with the persistent profile so the user can log in
    to Gmail, Google, Ajio, or Myntra. All cookies are saved locally.
    """
    print("\n" + "=" * 65)
    print("🔑 LOGIN MODE: PERSISTENT GOOGLE / STORE PROFILE SETUP")
    print("=" * 65)
    print(f"Profile Directory: {CHROME_PROFILE_DIR.resolve()}")
    print("Launching Chrome... Please log in to your Google / Gmail or store account.")

    async with async_playwright() as p:
        context = await launch_persistent_chrome(p, headless=False)
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto("https://accounts.google.com/signin", wait_until="domcontentloaded")
        print("\n👉 Chrome is open! You can now log into your Google Account / Store accounts.")
        print("👉 When you are finished logging in, return here and press ENTER.")

        # Wait for user input in terminal
        await asyncio.to_thread(input, "\n[PRESS ENTER TO SAVE PROFILE AND CLOSE CHROME] > ")

        await context.close()
        print("\n✅ Profile and login cookies have been saved successfully to chrome_profile/!")
        print("All future scraper runs will automatically reuse this authenticated session.")


async def run_myntra_local(context, limit_pages: Optional[int] = None):
    """Executes Myntra Columbia scraper in Chrome and syncs to Supabase."""
    print("\n" + "=" * 65)
    print("🚀 [MYNTRA] STARTING MYNTRA COLUMBIA SCRAPER")
    print("=" * 65)

    js_file = SCRAPER_DIR / "new_myntra_scraper.js"
    if not js_file.exists():
        raise FileNotFoundError(f"Scraper script not found: {js_file}")

    with open(js_file, "r", encoding="utf-8") as f:
        scraper_code = f.read()

    page = await context.new_page()
    page.on("console", lambda msg: print(f"[Myntra:Browser] {msg.text}"))

    t0 = time.perf_counter()
    try:
        print("[MYNTRA] Navigating to Myntra Columbia store in Chrome...")
        await page.goto("https://www.myntra.com/columbia?rawQuery=columbia", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        if limit_pages:
            await page.evaluate(f"() => {{ window.__MAX_PAGES__ = {limit_pages}; }}")

        print("[MYNTRA] Injecting new_myntra_scraper.js into Chrome tab...")
        await page.evaluate(f"() => {{ {scraper_code} }}")

        print("[MYNTRA] Scraper running. Monitoring real-time progress...")
        last_item = 0
        while True:
            await asyncio.sleep(3)
            status = await page.evaluate("""() => ({
                done: Boolean(window.__MYNTRA_SCRAPER_DONE__),
                progress: window.__SCRAPER_PROGRESS__ || null,
                count: (window.__MYNTRA_PRODUCTS__ || []).length
            })""")

            prog = status.get("progress") or {}
            curr = prog.get("current", 0)
            tot = prog.get("total", 0)
            stg = prog.get("stage", "Scraping")
            if curr != last_item and tot > 0:
                print(f"[MYNTRA:Progress] {stg} - Item {curr}/{tot} | Products collected: {status.get('count', 0)}")
                last_item = curr

            if status.get("done"):
                break

        raw_products = await page.evaluate("() => window.__MYNTRA_PRODUCTS__ || []")
        dur = round(time.perf_counter() - t0, 1)
        print(f"[MYNTRA] ✅ Scraper finished! Collected {len(raw_products)} products with full sizes & offers in {dur}s.")

        # Save local JSON backup
        backup_file = DATA_DIR / f"myntra_columbia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(raw_products, f, indent=2, ensure_ascii=False)
        print(f"[MYNTRA] 💾 Local backup saved to {backup_file.name}")

        # Sync to Supabase
        print(f"[MYNTRA] 📤 Syncing {len(raw_products)} products into Supabase...")
        res = await sync_products_to_supabase(raw_products, "myntra", log_func=print)
        await record_scrape_run("myntra", len(raw_products), dur, status="completed")
        print(f"🎉 [MYNTRA] Finished: {res['upserted']} products and {res['price_history']} prices in Supabase!")
        return raw_products
    finally:
        await page.close()


async def run_ajio_local(context, limit_pages: Optional[int] = None):
    """Executes Ajio Columbia scraper in Chrome and syncs to Supabase."""
    print("\n" + "=" * 65)
    print("🚀 [AJIO] STARTING AJIO COLUMBIA SCRAPER")
    print("=" * 65)

    js_file = SCRAPER_DIR / "New_ajio_scraper.js"
    if not js_file.exists():
        raise FileNotFoundError(f"Scraper script not found: {js_file}")

    with open(js_file, "r", encoding="utf-8") as f:
        scraper_code = f.read()

    page = await context.new_page()
    page.on("console", lambda msg: print(f"[Ajio:Browser] {msg.text}"))

    t0 = time.perf_counter()
    try:
        print("[AJIO] Navigating to Ajio Columbia store in Chrome...")
        await page.goto("https://www.ajio.com/search/?text=columbia", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        if limit_pages:
            await page.evaluate(f"() => {{ window.__MAX_PAGES__ = {limit_pages}; }}")

        print("[AJIO] Injecting New_ajio_scraper.js into Chrome tab...")
        await page.evaluate(f"() => {{ {scraper_code} }}")

        print("[AJIO] Scraper running. Monitoring real-time progress...")
        last_page = 0
        while True:
            await asyncio.sleep(3)
            status = await page.evaluate("""() => ({
                done: Boolean(window.__AJIO_SCRAPER_DONE__),
                progress: window.__SCRAPER_PROGRESS__ || null,
                count: (window.__AJIO_PRODUCTS__ || []).length
            })""")

            prog = status.get("progress") or {}
            curr = prog.get("current", 0)
            tot = prog.get("total", 0)
            stg = prog.get("stage", "Scraping")
            if curr != last_page and tot > 0:
                print(f"[AJIO:Progress] {stg} - Page {curr}/{tot} | Products collected: {status.get('count', 0)}")
                last_page = curr

            if status.get("done"):
                break

        raw_products = await page.evaluate("() => window.__AJIO_PRODUCTS__ || []")
        dur = round(time.perf_counter() - t0, 1)
        print(f"[AJIO] ✅ Scraper finished! Collected {len(raw_products)} products with sizes & offers in {dur}s.")

        # Save local JSON backup
        backup_file = DATA_DIR / f"ajio_columbia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(raw_products, f, indent=2, ensure_ascii=False)
        print(f"[AJIO] 💾 Local backup saved to {backup_file.name}")

        # Sync to Supabase
        print(f"[AJIO] 📤 Syncing {len(raw_products)} products into Supabase...")
        res = await sync_products_to_supabase(raw_products, "ajio", log_func=print)
        await record_scrape_run("ajio", len(raw_products), dur, status="completed")
        print(f"🎉 [AJIO] Finished: {res['upserted']} products and {res['price_history']} prices in Supabase!")
        return raw_products
    finally:
        await page.close()


async def run_scraper_session(target: str, limit_pages: Optional[int] = None):
    """Orchestrates scraper execution in persistent Chrome context."""
    async with async_playwright() as p:
        context = await launch_persistent_chrome(p, headless=False)
        try:
            if target in ("myntra", "all"):
                await run_myntra_local(context, limit_pages=limit_pages)
            if target in ("ajio", "all"):
                await run_ajio_local(context, limit_pages=limit_pages)
        finally:
            print("\n[CHROME] Closing Chrome context and saving profile...")
            await context.close()


def show_interactive_menu():
    print("\n" + "=" * 65)
    print("🌟 VANTIS LOCAL HEADED SCRAPER SUITE (MYNTRA & AJIO)")
    print("=" * 65)
    print("1. Login Mode (Open Chrome to log in to Gmail / Accounts and save profile)")
    print("2. Scrape Myntra Columbia Products -> Supabase")
    print("3. Scrape Ajio Columbia Products -> Supabase")
    print("4. Scrape Both (Myntra + Ajio) -> Supabase")
    print("5. Quick Test Run (1 Page Each) -> Supabase")
    print("0. Exit")
    print("=" * 65)

    choice = input("Enter choice (0-5) [Default: 4]: ").strip() or "4"
    return choice


def main():
    parser = argparse.ArgumentParser(description="Vantis Local Headed Scrapers (Ajio & Myntra)")
    parser.add_argument("--login", action="store_true", help="Launch Chrome in Login Mode to save profile")
    parser.add_argument("--scraper", choices=["myntra", "ajio", "all"], default=None, help="Target scraper")
    parser.add_argument("--limit", type=int, default=None, help="Limit pages to scrape for testing")
    args = parser.parse_args()

    if args.login:
        asyncio.run(login_session_mode())
        return

    if args.scraper:
        asyncio.run(run_scraper_session(args.scraper, limit_pages=args.limit))
        return

    # Interactive CLI Menu
    while True:
        choice = show_interactive_menu()
        if choice == "0":
            print("Exiting. Goodbye!")
            break
        elif choice == "1":
            asyncio.run(login_session_mode())
        elif choice == "2":
            asyncio.run(run_scraper_session("myntra", limit_pages=args.limit))
        elif choice == "3":
            asyncio.run(run_scraper_session("ajio", limit_pages=args.limit))
        elif choice == "4":
            asyncio.run(run_scraper_session("all", limit_pages=args.limit))
        elif choice == "5":
            asyncio.run(run_scraper_session("all", limit_pages=1))
        else:
            print("Invalid choice, please select 0-5.")


if __name__ == "__main__":
    main()
