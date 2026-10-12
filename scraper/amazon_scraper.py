import asyncio
import json
import random
import html
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError
from selectolax.parser import HTMLParser

import time
from datetime import datetime
from pathlib import Path

from processing.platform_paths import BASE_DIR, dated_json_path
from processing.browser_paths import chromium_executable
from processing.process_status import update_site_status
# ---------------- CONFIG ---------------- #

SELLERS = [
    ("AUEEW31YCNC4K", "Chogori"),
    ("A1WYWER0W24N8S", "Seller2")
]

MAX_EMPTY_PAGES = 2

WORKERS = 4
START_PAGE = 1
HEADLESS = False
MAX_PAGES = 500
products = {}

total_products = 0
accepted_products = 0
rejected_products = 0

lock = asyncio.Lock()
START_TIME = None


SEARCH_RESULT_SELECTOR = 'div[data-component-type="s-search-result"]'


# ---------------- PARSER ---------------- #

def parse(html_doc):

    tree = HTMLParser(html_doc)

    cards = tree.css(SEARCH_RESULT_SELECTOR)

    parsed = []
    seen = set()

    for card in cards:

        asin = (card.attributes.get("data-asin") or "").strip()

        if not asin:
            continue

        title = ""
        brand = ""

        price = ""
        image = ""
        href = ""
        global total_products
        global accepted_products
        global rejected_products

        node = card.css_first("a h2 span")
        if node:
            title = node.text(strip=True)

        node = card.css_first("span.a-price > span.a-offscreen")
        if node:
            price = node.text(strip=True)

        node = card.css_first("img.s-image")
        if node:
            image = node.attributes.get("src", "")

        node = card.css_first("a[href*='/dp/']")
        if node:
            href = node.attributes.get("href", "")

       

        
        if href:
            # Amazon links are commonly /Columbia-.../dp/ASIN or /dp/ASIN.
            # Only use the slug when it is actually present; counting before
            # this extraction made every product look non-Columbia.
            parts = [part for part in href.split("/") if part]
            if "dp" in parts:
                slug = parts[max(0, parts.index("dp") - 1)]
                brand = slug.split("-")[0].lower()

        # Search results can use a generic /dp/ASIN link, so fall back to the
        # title when the URL does not contain a brand slug.
        if not brand and title:
            brand = title.split()[0].lower()

        total_products += 1
        if brand == "columbia" or "columbia" in title.lower():
            accepted_products += 1
        else:
            rejected_products += 1

        # -------------------------
        # Extract Variants FIRST
        # -------------------------

        variants = []

        node = card.css_first(
            "[data-puis-atcb-add-action-sizevariation]"
        )

        if node:

            raw = node.attributes.get(
                "data-puis-atcb-add-action-sizevariation",
                ""
            )

            try:

                raw = html.unescape(raw)

                data = json.loads(raw)

                variants = data.get("variations", [])

            except Exception:
                pass


        # -------------------------
        # Main Product
        # -------------------------

        parsed.append({

            "asin": asin,

            "brand": brand,

            "family": [asin] + variants,

            "title": title,

            "price": price,

            "image": image,

            "href": href,

            "is_main": True

        })
        seen.add(asin)

       

        # -------------------------
        # Variant ASINs
        # -------------------------

        for variant in variants:

            if variant in seen:
                continue

            parsed.append({

                "asin": variant,

                "family": [asin] + variants,

                "title": "",

                "price": "",

                "image": "",

                "href": "",

                "is_main": False

            })

            seen.add(variant)

           
    return parsed

# ---------------- WORKER ---------------- #

async def worker(worker_id, context, queue, seller_id, seller_name):

    page = await context.new_page()

    try:

        while True:

            try:
                page_no = queue.get_nowait()

            except asyncio.QueueEmpty:
                break

            url = (
                f"https://www.amazon.in/s?"
                f"i=merchant-items"
                f"&me={seller_id}"
                f"&k=Columbia"
                f"&page={page_no}"
            )

            success = False

            for attempt in range(3):

                try:

                    # Random human-ish delay
                    await asyncio.sleep(random.uniform(0.8, 1.6))

                    print(
                        f"[Worker {worker_id}] "
                        f"Page {page_no} "
                        f"(Attempt {attempt+1})"
                    )
                    elapsed = int(time.perf_counter() - START_TIME) if START_TIME else 0
                    eta = int((elapsed / max(1, page_no)) * max(0, MAX_PAGES - page_no)) if page_no > 0 else 0
                    update_site_status("amazon", {
                        "stage": "Collecting Products",
                        "current": page_no,
                        "total": MAX_PAGES,
                        "elapsed_seconds": elapsed,
                        "eta_seconds": eta,
                        "current_seller": seller_name
                    })

                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    try:
                        await page.wait_for_selector(
                            SEARCH_RESULT_SELECTOR,
                            timeout=15000,
                        )
                    except Exception:
                        # Amazon frequently delays or replaces the search
                        # results container with anti-bot or no-results markup.
                        # Continue below and inspect the actual page content so
                        # we can distinguish a real end-of-catalog from a retryable
                        # transient failure.
                        pass

                    html = await page.content()

                    parsed = parse(html)

                    if len(parsed) == 0:
                        page_text = await page.locator("body").inner_text(timeout=5000)
                        if "No results for your search query." in page_text:
                            print(
                                f"[Worker {worker_id}] "
                                f"Seller {seller_id} finished at page {page_no}"
                            )
                            queue.task_done()
                            return
                        if any(marker in page_text for marker in (
                            "Robot Check",
                            "Enter the characters you see",
                            "captcha",
                        )):
                            raise RuntimeError("Amazon returned a bot-check page")

                    async with lock:

                        for product in parsed:

                            asin = product["asin"]

                            if asin not in products:

                                products[asin] = product

                            else:

                                existing = products[asin]

                                # Never replace good data with blanks
                                if product["title"]:
                                    existing["title"] = product["title"]

                                if product["price"]:
                                    existing["price"] = product["price"]

                                if product["image"]:
                                    existing["image"] = product["image"]

                                if product["href"]:
                                    existing["href"] = product["href"]

                                # If we've ever seen it as a real product,
                                # keep it marked as a real product.
                                existing["is_main"] = (
                                    existing["is_main"] or product["is_main"]
                                )

                                # Preserve the first discovered parent
                                if len(product.get("family", [])) > len(existing.get("family", [])):
                                    existing["family"] = product["family"]




                        unique = len(products)
                    elapsed = max(0.0, time.perf_counter() - START_TIME) if START_TIME else 0.0
                    eta = (elapsed / page_no * (MAX_PAGES - page_no)) if page_no > 0 and MAX_PAGES > page_no else 0.0
                    update_site_status("amazon", {
                        "stage": f"Collecting: {seller_name}",
                        "current": page_no,
                        "total": MAX_PAGES,
                        "elapsed_seconds": int(elapsed),
                        "eta_seconds": int(eta),
                        "message": f"Page {page_no}/{MAX_PAGES} ({unique} unique)"
                    })

                    print(
                        f"[Worker {worker_id}] "
                        f"Page {page_no:03} | "
                        f"{len(parsed):02} products | "
                        f"Unique: {unique}"
                    )

                    success = True
                    break

                except Exception as e:

                    print(
                        f"[Worker {worker_id}] "
                        f"Page {page_no} failed "
                        f"(Attempt {attempt+1})"
                    )

                    print(e)

                    await asyncio.sleep(3)

            if not success:

                print(f"[ERROR] Page {page_no} permanently failed")

                try:
                    html = await page.content()

                    if "No results for your search query." in html:
                        print(f"\nSeller {seller_id} finished at page {page_no}")
                        queue.task_done()
                        return

                    with open(
                        f"failed_page_{page_no}.html",
                        "w",
                        encoding="utf8"
                    ) as f:
                        f.write(html)

                except:
                    pass

            queue.task_done()

    finally:

        await page.close()

# ---------------- MAIN ---------------- #

async def main():
    global START_TIME
    start_time = time.perf_counter()
    START_TIME = start_time
    update_site_status("amazon", {"stage": "Starting browser", "current": 0, "total": MAX_PAGES, "elapsed_seconds": 0, "eta_seconds": 0})

    async with async_playwright() as p:
        launch_kwargs = {"headless": HEADLESS}
        browser_path = chromium_executable()
        if browser_path is not None:
            launch_kwargs["executable_path"] = str(browser_path)
            print(f"Using installed browser at {browser_path}")

        try:
            browser = await p.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "No Chromium browser was found. Install Google Chrome or Edge, or run 'playwright install chromium' for this environment."
                ) from exc
            raise

        context = await browser.new_context(
            viewport={
                "width": 1400,
                "height": 1000
            }
        )

        async def block(route):

            if route.request.resource_type in (
                "image",
                "font",
                "media",
            ):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", block)

        # ------------------------------------
        # SCRAPE EVERY SELLER
        # ------------------------------------

        for seller_id, seller_name in SELLERS:
            update_site_status("amazon", {"stage": f"Collecting Products: {seller_name}", "current": 0, "total": MAX_PAGES})

            print("\n" + "=" * 60)
            print(f"SELLER : {seller_name} ({seller_id})")
            print("=" * 60)

            queue = asyncio.Queue()

            for page in range(1, MAX_PAGES + 1):
                queue.put_nowait(page)

            tasks = []

            for worker_id in range(WORKERS):

                tasks.append(
                    asyncio.create_task(
                        worker(
                            worker_id + 1,
                            context,
                            queue,
                            seller_id,
                            seller_name
                        )
                    )
                )

            await asyncio.gather(*tasks)

            print(f"Finished seller {seller_name}")

        await browser.close()

    print("\n===========================")
    print(f"Cards Seen          : {total_products}")
    print(f"Columbia Products   : {accepted_products}")
    print(f"Rejected Products   : {rejected_products}")
    print(f"Unique ASINs        : {len(products)}")

    # Write the same dated snapshot shape consumed by the shared pipeline.
    # Keep a copy at the old location for backwards compatibility with any
    # manual workflows that still look for seller_products.json.
    scraped_at = datetime.now().isoformat(timespec="seconds")
    payload = {
        "schema_version": 1,
        "source": "amazonV4",
        "scrape_date": scraped_at[:10],
        "scraped_at": scraped_at,
        "products": list(products.values()),
    }
    destination = dated_json_path("amazon", scraped_at[:10])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")
    update_site_status("amazon", {"stage": "Saving data", "current": MAX_PAGES, "total": MAX_PAGES})
    Path("seller_products.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")
    print(f"Saved {destination}")

    elapsed = time.perf_counter() - start_time
    update_site_status("amazon", {"stage": "Completed", "current": MAX_PAGES, "total": MAX_PAGES, "elapsed_seconds": int(elapsed), "eta_seconds": 0})

    minutes = int(elapsed // 60)
    seconds = elapsed % 60

    print(f"\nFinished in {minutes}m {seconds:.2f}s")
# ---------------- START ---------------- #

if __name__ == "__main__":

    asyncio.run(main())
