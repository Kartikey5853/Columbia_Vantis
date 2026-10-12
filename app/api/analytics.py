from fastapi import APIRouter, HTTPException, Query, status
from typing import Optional, Dict, Any, List
from app.schemas.models import AnalyticsSummary, ProductPriceHistoryResponse
from app.services.catalog_service import catalog_service

router = APIRouter(prefix="/api/analytics", tags=["Product Analytics"])

@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary():
    """Returns high-level catalogue intelligence metrics."""
    return catalog_service.get_summary()

@router.get("/products")
async def get_analytics_product_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    gender: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    sort_by: str = Query("price_change")
):
    """
    Returns products formatted for the left pane of the Analytics workspace,
    including sparklines, price change %, min/max recorded prices.
    """
    return catalog_service.get_analytics_products(
        search=search,
        category=category,
        gender=gender,
        platform=platform,
        sort_by=sort_by,
        page=page,
        page_size=page_size
    )

@router.get("/price-history", response_model=ProductPriceHistoryResponse)
async def get_product_price_history(
    family_id: str = Query(..., description="Product family ID"),
    range: str = Query("6M", description="Date range: 1M, 3M, 6M, 1Y, ALL")
):
    """
    Returns multi-platform historical price points and platform statistics
    for the interactive Recharts multi-line chart.
    """
    data = catalog_service.get_price_history(family_id, range_filter=range)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family '{family_id}' not found"
        )
    return data

@router.get("/platform-comparison")
async def get_platform_comparison():
    """Aggregated comparison across the 7 platforms."""
    return {
        "platforms": [
            {"name": "Amazon", "key": "amazon", "avg_discount": 28.5, "in_stock_rate": 82.0, "total_listings": 1997},
            {"name": "Tata CLiQ", "key": "tata", "avg_discount": 22.0, "in_stock_rate": 79.0, "total_listings": 2108},
            {"name": "Tata CLiQ Luxury", "key": "tata_lux", "avg_discount": 18.0, "in_stock_rate": 85.0, "total_listings": 2244},
            {"name": "Columbia", "key": "columbia", "avg_discount": 15.0, "in_stock_rate": 92.0, "total_listings": 5408},
            {"name": "Advaatars", "key": "adv", "avg_discount": 25.0, "in_stock_rate": 78.0, "total_listings": 4906},
            {"name": "Myntra", "key": "myntra", "avg_discount": 30.0, "in_stock_rate": 88.0, "total_listings": 1704},
            {"name": "AJIO", "key": "ajio", "avg_discount": 26.5, "in_stock_rate": 81.0, "total_listings": 2210},
        ]
    }

@router.get("/categories")
async def get_category_insights():
    catalog_service.load_catalog()
    cat_counts: Dict[str, int] = {}
    for fam in catalog_service.families_list:
        c = fam["category"]
        cat_counts[c] = cat_counts.get(c, 0) + 1
    return {
        "categories": [{"name": k, "count": v} for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])]
    }
