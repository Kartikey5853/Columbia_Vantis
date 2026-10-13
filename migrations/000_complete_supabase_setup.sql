-- =========================================================================
-- COMPLETE UNIFIED DATABASE SETUP FOR SUPABASE
-- Project: Columbia 4.0 Platform Intelligence Pipeline
-- Run this ENTIRE script in your Supabase SQL Editor:
-- Dashboard -> SQL Editor -> New Query -> Paste & Run
-- =========================================================================

-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================================================================
-- 1. Table: scrapers (Registered scrapers and data sources)
-- =========================================================================
CREATE TABLE IF NOT EXISTS scrapers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed all platform scrapers so foreign key references never fail
INSERT INTO scrapers (name, source, enabled)
VALUES 
    ('columbia', 'columbia_sportswear_india', true),
    ('amazon', 'amazon', true),
    ('tata', 'tatacliq', true),
    ('tata_lux', 'tatacliq_luxury', true),
    ('adv', 'adventuras', true),
    ('myntra', 'myntra', true),
    ('ajio', 'ajio', true)
ON CONFLICT (name) DO UPDATE 
SET source = EXCLUDED.source, enabled = EXCLUDED.enabled;

-- =========================================================================
-- 2. Table: products (One canonical row per product per source)
-- =========================================================================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scraper_id UUID NOT NULL REFERENCES scrapers(id) ON DELETE CASCADE,
    source_product_id TEXT NOT NULL,
    sku TEXT,
    ean TEXT,
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    available BOOLEAN NOT NULL DEFAULT true,
    current_price NUMERIC(12, 2),
    current_mrp NUMERIC(12, 2),
    variants JSONB NOT NULL DEFAULT '[]'::jsonb,
    style TEXT,
    stock INT DEFAULT 0,
    offers JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_product_scraper_source UNIQUE (scraper_id, source_product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_scraper_id ON products(scraper_id);
CREATE INDEX IF NOT EXISTS idx_products_source_product_id ON products(source_product_id);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_ean ON products(ean);
CREATE INDEX IF NOT EXISTS idx_products_style ON products(style);

-- =========================================================================
-- 3. Table: scrape_runs (Every scraper run execution and JSON reports)
-- =========================================================================
CREATE TABLE IF NOT EXISTS scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scraper_id UUID NOT NULL REFERENCES scrapers(id) ON DELETE CASCADE,
    business_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'paused', 'completed', 'failed')),
    stage TEXT NOT NULL CHECK (stage IN ('listings', 'products', 'variants', 'finalizing')),
    total_products INT NOT NULL DEFAULT 0,
    completed_products INT NOT NULL DEFAULT 0,
    failed_products INT NOT NULL DEFAULT 0,
    report JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_scraper_date ON scrape_runs(scraper_id, business_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_run_per_scraper_date 
ON scrape_runs(scraper_id, business_date) 
WHERE status IN ('queued', 'running');

-- =========================================================================
-- 4. Table: price_history (Historical price audits for analytics & graphs)
-- =========================================================================
CREATE TABLE IF NOT EXISTS price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price NUMERIC(12, 2) NOT NULL,
    mrp NUMERIC(12, 2),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    scrape_run_id UUID REFERENCES scrape_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history(product_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_run_id ON price_history(scrape_run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_product_run 
ON price_history(product_id, scrape_run_id) 
WHERE scrape_run_id IS NOT NULL;

-- =========================================================================
-- 5. Table: scrape_listing_pages (Checkpointing listing pages)
-- =========================================================================
CREATE TABLE IF NOT EXISTS scrape_listing_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id UUID NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    product_count INT NOT NULL DEFAULT 0,
    attempts INT NOT NULL DEFAULT 0,
    error TEXT,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_listing_page_run UNIQUE (scrape_run_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_listing_pages_run_id ON scrape_listing_pages(scrape_run_id, status);

-- =========================================================================
-- 6. Table: scrape_product_progress (Checkpointing product detail scrapes)
-- =========================================================================
CREATE TABLE IF NOT EXISTS scrape_product_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id UUID NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    source_product_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    variant_count INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_product_progress_run_product UNIQUE (scrape_run_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_product_progress_run_status ON scrape_product_progress(scrape_run_id, status);

-- =========================================================================
-- 7. Table: app_users (Employee logins, passwords, avatars, and roles)
-- =========================================================================
CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Product Intelligence Lead',
    avatar_url TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    notifications_enabled BOOLEAN NOT NULL DEFAULT true,
    theme TEXT NOT NULL DEFAULT 'light',
    has_master_excel BOOLEAN NOT NULL DEFAULT true,
    master_excel_filename TEXT DEFAULT 'Master_Catalog_Columbia.xlsx',
    master_excel_records INT DEFAULT 3513,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_users_username ON app_users(username);

-- =========================================================================
-- 8. Table: user_sessions (JWT session tokens, login history)
-- =========================================================================
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL REFERENCES app_users(username) ON DELETE CASCADE,
    session_token TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_username ON user_sessions(username);

-- =========================================================================
-- 9. Table: master_catalog (Master Excel catalog mapping)
-- =========================================================================
CREATE TABLE IF NOT EXISTS master_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ean TEXT,
    sku TEXT,
    style_code TEXT,
    style TEXT NOT NULL,
    soh INT DEFAULT 0,
    platform_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_master_catalog_sku UNIQUE (sku)
);

CREATE INDEX IF NOT EXISTS idx_master_catalog_style ON master_catalog(style);
CREATE INDEX IF NOT EXISTS idx_master_catalog_style_code ON master_catalog(style_code);
CREATE INDEX IF NOT EXISTS idx_master_catalog_ean ON master_catalog(ean);
CREATE INDEX IF NOT EXISTS idx_master_catalog_sku ON master_catalog(sku);

-- Seed initial employee accounts if not already present
INSERT INTO app_users (username, password_hash, display_name, role, avatar_url, has_master_excel, master_excel_filename, master_excel_records)
VALUES 
    (
        'kartikey',
        '2b00fd270242e8c9ef2fbd25c9916facb7eee85db31cb7a34570566343b0abe7',
        'Kartikey',
        '',
        NULL,
        true,
        'Master_Catalog_Columbia.xlsx',
        3513
    ),
    (
        'raj',
        '048ce982a3172bc31a1590a34a5d7e5ebfc885b97db7941937256e359628c08d',
        'Raj',
        '',
        NULL,
        true,
        'Master_Catalog_Columbia.xlsx',
        3513
    )
ON CONFLICT (username) DO NOTHING;

-- =========================================================================
-- 10. Diagnostics RPC function: get_database_size_stats
-- =========================================================================
CREATE OR REPLACE FUNCTION get_database_size_stats()
RETURNS TABLE (
    table_name TEXT,
    row_count BIGINT,
    total_size_bytes BIGINT,
    total_size_pretty TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    tbl RECORD;
    cnt BIGINT;
    sz BIGINT;
    db_sz BIGINT;
BEGIN
    FOR tbl IN 
        SELECT unnest(ARRAY[
            'products', 
            'price_history', 
            'scrape_runs', 
            'scrape_listing_pages', 
            'scrape_product_progress', 
            'scrapers',
            'app_users',
            'master_catalog'
        ]) AS name
    LOOP
        EXECUTE format('SELECT count(*) FROM %I', tbl.name) INTO cnt;
        SELECT pg_total_relation_size(quote_ident(tbl.name)) INTO sz;
        
        table_name := tbl.name;
        row_count := cnt;
        total_size_bytes := sz;
        total_size_pretty := pg_size_pretty(sz);
        RETURN NEXT;
    END LOOP;

    SELECT pg_database_size(current_database()) INTO db_sz;
    table_name := '__total_database__';
    row_count := 0;
    total_size_bytes := db_sz;
    total_size_pretty := pg_size_pretty(db_sz);
    RETURN NEXT;
END;
$$;

GRANT EXECUTE ON FUNCTION get_database_size_stats() TO anon, authenticated, service_role;
