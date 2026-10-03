import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright


load_dotenv()

TOKEN = os.getenv("SHOPIFY_TOKEN")

if not TOKEN:
    raise RuntimeError("SHOPIFY_TOKEN is missing from .env")


async def main():
    scraper_path = Path("scraper/columbia_scraper.js")
    scraper_code = scraper_path.read_text(encoding="utf-8")

    # Inject the secret into the JS before running it
    scraper_code = scraper_code.replace(
        "__SHOPIFY_TOKEN__",
        TOKEN
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page()

        print("Opening Columbia...")

        await page.goto(
            "https://www.columbiasportswear.co.in/",
            wait_until="domcontentloaded"
        )

        print("Injecting scraper...")

        await page.evaluate(scraper_code)

        print("Waiting for product...")

        await page.wait_for_function(
            "() => window.output && window.output.length > 0",
            timeout=120_000
        )

        first_product = await page.evaluate(
            "() => window.output[0]"
        )

        print("\nFIRST PRODUCT:")
        print(first_product)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())