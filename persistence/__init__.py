"""
Unified Supabase Persistence Layer for Tata CLiQ and Columbia Sportswear scrapers.
"""
from persistence.models import NormalizedProduct, NormalizedVariant
from persistence.supabase_client import SupabaseClient, get_supabase_client
from persistence.run_store import (
    get_or_create_daily_run,
    update_run_stage,
    update_run_counts,
    complete_run,
    fail_run,
    get_business_date,
    get_scraper_id
)
from persistence.checkpoint_store import (
    get_completed_listing_pages,
    record_listing_page_started,
    record_listing_page_completed,
    record_listing_page_failed,
    init_product_progress,
    get_incomplete_products,
    mark_product_in_progress,
    mark_product_completed,
    mark_product_failed,
    batch_record_product_progress
)
from persistence.product_store import (
    upsert_canonical_product,
    upsert_canonical_products_batch,
    record_price_if_changed,
    batch_record_prices_if_changed,
    get_canonical_product_by_id,
    get_all_canonical_products
)
from persistence.exporter import export_canonical_backup
from persistence.diagnostics import get_database_storage_stats, format_storage_report

__all__ = [
    "NormalizedProduct",
    "NormalizedVariant",
    "SupabaseClient",
    "get_supabase_client",
    "get_or_create_daily_run",
    "update_run_stage",
    "update_run_counts",
    "complete_run",
    "fail_run",
    "get_business_date",
    "get_scraper_id",
    "get_completed_listing_pages",
    "record_listing_page_started",
    "record_listing_page_completed",
    "record_listing_page_failed",
    "init_product_progress",
    "get_incomplete_products",
    "mark_product_in_progress",
    "mark_product_completed",
    "mark_product_failed",
    "batch_record_product_progress",
    "upsert_canonical_product",
    "upsert_canonical_products_batch",
    "record_price_if_changed",
    "batch_record_prices_if_changed",
    "get_canonical_product_by_id",
    "get_all_canonical_products",
    "export_canonical_backup",
    "get_database_storage_stats",
    "format_storage_report",
]
