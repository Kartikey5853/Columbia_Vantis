from fastapi import FastAPI
from runner import main


app = FastAPI(
    title="Columbia Product Scraper API",
    description="API for scraping Columbia Sportswear India product data.",
    version="1.0.0"
)


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Columbia Product Scraper API"
    }


@app.get("/scrape")
async def scrape():
    result = await main()
    return result