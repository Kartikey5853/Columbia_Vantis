from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# --- Auth Schemas ---
class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: Optional[bool] = False

class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    avatar_url: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    notifications_enabled: bool = True
    theme: str = "light"
    has_master_excel: bool = False
    master_excel_filename: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class ResetPasswordRequest(BaseModel):
    new_password: str
    current_password: Optional[str] = None

class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    theme: Optional[str] = None

# --- Product Schemas ---
class ProductOffer(BaseModel):
    kind: str = "offer"
    code: Optional[str] = None
    title: str
    description: Optional[str] = None
    offer_price: Optional[float] = None
    issuer: Optional[str] = None
    card_type: Optional[str] = None
    payment_network: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    minimum_transaction_amount: Optional[float] = None
    maximum_discount: Optional[float] = None
    valid_from: Optional[str] = None
    validity: Optional[str] = None
    terms_url: Optional[str] = None

class ProductVariant(BaseModel):
    size: str = ""
    color: Optional[str] = None
    sku: Optional[str] = None
    ean: Optional[str] = None
    available: bool = True
    quantity: Optional[Any] = None
    stock: Optional[Any] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    title: Optional[str] = None

class PlatformListing(BaseModel):
    platform: str
    platform_name: str
    platform_key: str
    logo_key: str
    product_id: str
    listing_title: str
    url: str
    image_url: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    price_difference: Optional[float] = None
    availability_status: str  # "In stock", "Limited stock", "Out of stock", "Unknown"
    stock_text: Optional[str] = None
    sizes_available_count: int = 0
    sizes_summary: str = ""
    offers: List[ProductOffer] = []
    variants: List[ProductVariant] = []
    last_updated: Optional[str] = None

class ProductFamily(BaseModel):
    family_id: str
    title: str
    brand: str = "Columbia"
    style: Optional[str] = None
    ean: Optional[str] = None
    sku: Optional[str] = None
    category: str
    gender: str
    tags: List[str] = []
    image_url: Optional[str] = None
    gallery_images: List[str] = []
    lowest_price: float
    mrp: Optional[float] = None
    discount_percent: Optional[float] = None
    variants_count: int = 0
    sizes_count: int = 0
    platforms_count: int = 0
    colours_count: int = 0
    variants: List[ProductVariant] = []
    colors: List[str] = []
    sizes: List[str] = []
    platforms: List[PlatformListing] = []
    data_freshness: Optional[str] = None

class ProductFamilySummary(BaseModel):
    family_id: str
    canonical_family_id: Optional[str] = None
    title: str
    brand: str = "Columbia"
    style: Optional[str] = None
    ean: Optional[str] = None
    sku: Optional[str] = None
    matched_sku: Optional[str] = None
    matched_size: Optional[str] = None
    category: str
    gender: str
    tags: List[str] = []
    image_url: Optional[str] = None
    lowest_price: float
    mrp: Optional[float] = None
    discount_percent: Optional[float] = None
    variants_count: int = 0
    sizes_count: int = 0
    platforms_count: int = 0
    colours_count: int = 0
    platforms: List[PlatformListing] = []

class PaginatedProductsResponse(BaseModel):
    total_records: int
    page: int
    page_size: int
    total_pages: int
    categories: List[str] = []
    genders: List[str] = []
    products: List[ProductFamilySummary]

class BulkSearchRequest(BaseModel):
    identifiers: List[str]

# --- Analytics Schemas ---
class AnalyticsSummary(BaseModel):
    total_products: int
    total_variants: int
    total_platforms: int = 7
    active_offers_count: int
    avg_discount_percent: float
    lowest_catalog_price: float
    highest_catalog_price: float

class AnalyticsProductRow(BaseModel):
    family_id: str
    title: str
    style: Optional[str] = None
    ean: Optional[str] = None
    image_url: Optional[str] = None
    lowest_price: float
    price_change_percent: float
    min_recorded_price: float
    max_recorded_price: float
    sparkline: List[float] = []
    variants_count: int
    sizes_count: int
    platforms_count: int

class PricePoint(BaseModel):
    date: str
    amazon: Optional[float] = None
    tata: Optional[float] = None
    tata_lux: Optional[float] = None
    columbia: Optional[float] = None
    adv: Optional[float] = None
    myntra: Optional[float] = None
    ajio: Optional[float] = None

class PlatformPriceStat(BaseModel):
    platform: str
    platform_name: str
    current_price: Optional[float] = None
    lowest_price: Optional[float] = None
    highest_price: Optional[float] = None
    trend: List[float] = []

class ProductPriceHistoryResponse(BaseModel):
    family_id: str
    title: str
    style: Optional[str] = None
    ean: Optional[str] = None
    image_url: Optional[str] = None
    category: str
    gender: str
    tags: List[str] = []
    current_price: float
    price_change_percent: float
    lowest_recorded_price: float
    lowest_recorded_date: str
    highest_recorded_price: float
    highest_recorded_date: str
    price_range: float
    price_range_percent: float
    history_points: List[Dict[str, Any]]
    platform_stats: List[PlatformPriceStat]

# --- Scraper & System Status Schemas ---
class ScraperPlatformStatus(BaseModel):
    platform: str
    platform_name: str
    status: str  # "completed", "running", "scheduled", "failed", "not_run"
    last_run: Optional[str] = None
    next_scheduled_run: Optional[str] = None
    products_fetched: int = 0
    duration: Optional[str] = None
    last_error: Optional[str] = None

class SystemStatusSummary(BaseModel):
    total_scrapers: int
    running_scrapers: int
    scheduled_scrapers: int
    failed_scrapers: int
    live_servers: int
    sleeping_servers: int
    suspended_servers: int
    total_catalogue_products: int
    last_successful_run: Optional[str] = None

class SystemHealthResponse(BaseModel):
    service_name: str
    environment: str
    status: str
    base_url: str
    uptime_seconds: float
    database_status: str
    database_rows: int
    database_size: str
    last_health_check: str
