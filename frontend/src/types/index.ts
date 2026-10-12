export interface User {
  id: string;
  username: string;
  display_name: string;
  role: string;
  avatar_url?: string;
  timezone: string;
  notifications_enabled: boolean;
  theme: string;
  has_master_excel?: boolean;
  master_excel_filename?: string | null;
}

export interface ProductOffer {
  kind: string;
  code?: string | null;
  title: string;
  description?: string | null;
  offer_price?: number | null;
  issuer?: string | null;
  card_type?: string | null;
  payment_network?: string | null;
  discount_percent?: number | null;
  discount_amount?: number | null;
  minimum_transaction_amount?: number | null;
  maximum_discount?: number | null;
  valid_from?: string | null;
  validity?: string | null;
  terms_url?: string | null;
}

export interface ProductVariant {
  size: string;
  color?: string | null;
  sku?: string | null;
  ean?: string | null;
  available: boolean;
  quantity?: number | string | null;
  stock?: number | string | null;
  price?: number | null;
  mrp?: number | null;
  url?: string | null;
}

export interface PlatformListing {
  platform: string;
  platform_name: string;
  platform_key: string;
  logo_key: string;
  product_id: string;
  listing_title: string;
  url: string;
  image_url?: string | null;
  price?: number | null;
  mrp?: number | null;
  price_difference?: number | null;
  availability_status: "In stock" | "Limited stock" | "Out of stock" | "Unknown";
  stock_text?: string | null;
  sizes_available_count: number;
  sizes_summary: string;
  offers: ProductOffer[];
  variants?: ProductVariant[];
  last_updated?: string | null;
}

export interface ProductFamily {
  family_id: string;
  title: string;
  brand: string;
  style?: string | null;
  ean?: string | null;
  sku?: string | null;
  category: string;
  gender: string;
  tags: string[];
  image_url?: string | null;
  gallery_images: string[];
  lowest_price: number;
  mrp?: number | null;
  discount_percent?: number | null;
  variants_count: number;
  sizes_count: number;
  platforms_count: number;
  colours_count: number;
  variants: ProductVariant[];
  colors: string[];
  sizes: string[];
  platforms: PlatformListing[];
  data_freshness?: string | null;
}

export interface ProductFamilySummary {
  family_id: string;
  title: string;
  brand: string;
  style?: string | null;
  ean?: string | null;
  sku?: string | null;
  category: string;
  gender: string;
  tags: string[];
  image_url?: string | null;
  lowest_price: number;
  mrp?: number | null;
  discount_percent?: number | null;
  variants_count: number;
  sizes_count: number;
  platforms_count: number;
  colours_count: number;
  platforms: PlatformListing[];
}

export interface PaginatedProductsResponse {
  total_records: number;
  page: number;
  page_size: number;
  total_pages: number;
  categories: string[];
  genders: string[];
  products: ProductFamilySummary[];
}

export interface AnalyticsSummary {
  total_products: number;
  total_variants: number;
  total_platforms: number;
  active_offers_count: number;
  avg_discount_percent: number;
  lowest_catalog_price: number;
  highest_catalog_price: number;
}

export interface AnalyticsProductRow {
  family_id: string;
  title: string;
  style?: string | null;
  ean?: string | null;
  category?: string;
  gender?: string;
  image_url?: string | null;
  lowest_price: number;
  price_change_percent: number;
  min_recorded_price: number;
  max_recorded_price: number;
  sparkline: number[];
  variants_count: number;
  sizes_count: number;
  platforms_count: number;
}

export interface PlatformPriceStat {
  platform: string;
  platform_name: string;
  current_price?: number | null;
  lowest_price?: number | null;
  highest_price?: number | null;
  trend: number[];
}

export interface ProductPriceHistoryResponse {
  family_id: string;
  title: string;
  style?: string | null;
  ean?: string | null;
  image_url?: string | null;
  category: string;
  gender: string;
  tags: string[];
  current_price: number;
  price_change_percent: number;
  lowest_recorded_price: number;
  lowest_recorded_date: string;
  highest_recorded_price: number;
  highest_recorded_date: string;
  price_range: number;
  price_range_percent: number;
  history_points: Array<Record<string, any>>;
  platform_stats: PlatformPriceStat[];
}

export interface ScraperPlatformStatus {
  platform: string;
  platform_name: string;
  logo_key: string;
  status: "completed" | "running" | "scheduled" | "failed" | "not_run";
  last_run?: string | null;
  next_scheduled_run?: string | null;
  products_fetched: number;
  duration?: string | null;
  last_error?: string | null;
}

export interface SystemStatusSummary {
  total_scrapers: number;
  running_scrapers: number;
  scheduled_scrapers: number;
  failed_scrapers: number;
  live_servers: number;
  sleeping_servers: number;
  suspended_servers: number;
  total_catalogue_products: number;
  last_successful_run?: string | null;
}

export interface ServerStatus {
  name: string;
  service_type: string;
  environment: string;
  status: "live" | "sleeping" | "suspended" | "degraded";
  base_url: string;
  region?: string;
  uptime?: string;
  memory?: string;
  database_size?: string;
  database_rows?: number;
  last_health_check?: string;
  recent_error?: string | null;
}

export interface RecentRun {
  timestamp: string;
  platform: string;
  job_id: string;
  status: string;
  products_fetched: number;
  duration: string;
  message: string;
}

export interface MasterDataStatus {
  is_configured: boolean;
  details: {
    loaded: boolean;
    filename?: string | null;
    record_count: number;
    last_updated?: string | null;
  };
  default_catalog_records: number;
}
