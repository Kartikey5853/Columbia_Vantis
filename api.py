from fastapi import FastAPI
from runner import scrape_columbia, scrape_tata, close_shared_browser


app = FastAPI(
    title="Product Scraper API",
    description="API for scraping Columbia Sportswear India and Tata CLiQ product data.",
    version="1.1.0"
)


@app.on_event("shutdown")
async def on_shutdown():
    await close_shared_browser()


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Product Scraper API",
        "scrapers": ["columbia", "tatacliq"],
        "endpoints": {
            "columbia": "/scrape",
            "tata": "/scrape/tata"
        }
    }


@app.get("/scrape")
async def scrape_columbia_endpoint():
    """Scrapes Columbia Sportswear India product data."""
    result = await scrape_columbia()
    return result


@app.get("/scrape/tata")
async def scrape_tata_endpoint():
    """Scrapes Tata CLiQ for Columbia products."""
    result = await scrape_tata()
    return result