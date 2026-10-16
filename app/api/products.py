from fastapi import APIRouter, HTTPException, Query, status
from typing import Optional, List, Dict, Any
from app.schemas.models import (
    ProductFamily, ProductFamilySummary, PaginatedProductsResponse,
    BulkSearchRequest, ProductVariant, PlatformListing, ProductOffer
)
from app.services.catalog_service import catalog_service

router = APIRouter(prefix="/api/products", tags=["Products & Catalogue"])

@router.get("", response_model=PaginatedProductsResponse)
async def list_products(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for SKU, EAN, or title"),
    category: Optional[str] = Query(None, description="Category filter"),
    gender: Optional[str] = Query(None, description="Gender filter"),
    platform: Optional[str] = Query(None, description="Platform availability filter"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price filter"),
    sort_by: str = Query("relevance", description="Sort by relevance, price_asc, price_desc, variants, or platforms")
):
    """
    Returns paginated product families with server-side filtering and sorting.
    Does NOT dump entire catalog into browser.
    """
    res = catalog_service.paginate_catalog(
        page=page,
        page_size=page_size,
        search=search,
        category=category,
        gender=gender,
        platform=platform,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by
    )
    return res

@router.get("/reload")
@router.post("/reload")
async def reload_catalog():
    """Forces fresh re-index of catalog directly from Supabase."""
    from jobs import is_pipeline_running
    if is_pipeline_running():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The scrapers are currently running. To save RAM and ensure optimal performance, reloading or fetching new products is paused. Please wait around 1 hour for the scrapers to complete."
        )
    catalog_service.load_catalog(force=True)
    return {
        "status": "success",
        "total_families": len(catalog_service.families),
        "raw_records": catalog_service.raw_records_count,
        "load_time": catalog_service.load_time_seconds
    }

@router.get("/search", response_model=List[ProductFamilySummary])
async def search_products(
    q: str = Query(..., min_length=1, description="Query string"),
    limit: int = Query(24, ge=1, le=100, description="Maximum results to return")
):
    """
    Fast search by product name, SKU, EAN, or style code across all 7 platforms.
    """
    results = catalog_service.search(query=q, limit=limit)
    return results

@router.post("/bulk-search", response_model=List[ProductFamilySummary])
async def bulk_search_products(req: BulkSearchRequest):
    """
    Bulk search endpoint accepting a list of parsed SKUs, EANs, or product IDs.
    Returns matched product families.
    """
    if not req.identifiers:
        return []
    results = catalog_service.bulk_search(req.identifiers)
    return results

@router.get("/{family_id}", response_model=ProductFamily)
async def get_product_details(family_id: str):
    """
    Returns comprehensive product family details including 3-column metadata,
    variant options, size selector, and 7-platform comparison.
    """
    fam = catalog_service.get_family_by_id(family_id)
    if not fam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family '{family_id}' not found in catalog"
        )
    return fam

@router.get("/{family_id}/variants", response_model=List[ProductVariant])
async def get_product_variants(family_id: str):
    fam = catalog_service.get_family_by_id(family_id)
    if not fam:
        raise HTTPException(status_code=404, detail="Product family not found")
    return fam.get("variants", [])

@router.get("/{family_id}/platforms", response_model=List[PlatformListing])
async def get_product_platforms(family_id: str):
    fam = catalog_service.get_family_by_id(family_id)
    if not fam:
        raise HTTPException(status_code=404, detail="Product family not found")
    return fam.get("platforms", [])

@router.get("/{family_id}/offers", response_model=List[ProductOffer])
async def get_product_offers(family_id: str):
    fam = catalog_service.get_family_by_id(family_id)
    if not fam:
        raise HTTPException(status_code=404, detail="Product family not found")
    all_offers = []
    for p in fam.get("platforms", []):
        all_offers.extend(p.get("offers", []))
    return all_offers
