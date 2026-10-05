-- =========================================================================
-- Migration: 001_initial_schema.sql
-- Description: Core tables, constraints, indexes, and diagnostics for scrapers
-- Idempotent: Can be executed multiple times safely
-- =========================================================================

-- Enable pgcrypto for UUID generation if needed
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -------------------------------------------------------------------------
-- 1. Table: scrapers
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrapers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default scrapers
INSERT INTO scrapers (name, source, enabled)
VALUES 
    ('tata', 'tatacliq', true),
    ('columbia', 'columbia_sportswear_india', true)
ON CONFLICT (name) DO UPDATE 
SET source = EXCLUDED.source, enabled = EXCLUDED.enabled;

-- -------------------------------------------------------------------------
-- 2. Table: products (One canonical row per product per source)
-- -------------------------------------------------------------------------
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_product_scraper_source UNIQUE (scraper_id, source_product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_scraper_id ON products(scraper_id);
CREATE INDEX IF NOT EXISTS idx_products_source_product_id ON products(source_product_id);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);

-- -------------------------------------------------------------------------
-- 3. Table: scrape_runs
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scraper_id UUID NOT NULL REFERENCES scrapers(id) ON DELETE CASCADE,
    business_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'paused', 'completed', 'failed')),
    stage TEXT NOT NULL CHECK (stage IN ('listings', 'products', 'variants', 'finalizing')),
    total_products INT NOT NULL DEFAULT 0,
    completed_products INT NOT NULL DEFAULT 0,
    failed_products INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_scraper_date ON scrape_runs(scraper_id, business_date);
-- Prevent duplicate concurrent active runs for the same scraper on the same business date
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_run_per_scraper_date 
ON scrape_runs(scraper_id, business_date) 
WHERE status IN ('queued', 'running');

-- -------------------------------------------------------------------------
-- 4. Table: price_history
-- -------------------------------------------------------------------------
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
-- Idempotency protection against duplicate history recordings in the same run for the same product
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_product_run 
ON price_history(product_id, scrape_run_id) 
WHERE scrape_run_id IS NOT NULL;

-- -------------------------------------------------------------------------
-- 5. Table: scrape_listing_pages
-- -------------------------------------------------------------------------
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

-- -------------------------------------------------------------------------
-- 6. Table: scrape_product_progress
-- -------------------------------------------------------------------------
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

-- -------------------------------------------------------------------------
-- 7. Diagnostic RPC function: get_database_size_stats
-- -------------------------------------------------------------------------
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
            'scrapers'
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

    -- Include total database size row
    SELECT pg_database_size(current_database()) INTO db_sz;
    table_name := '__total_database__';
    row_count := 0;
    total_size_bytes := db_sz;
    total_size_pretty := pg_size_pretty(db_sz);
    RETURN NEXT;
END;
$$;

-- Grant execution to service_role and anon/authenticated if needed
GRANT EXECUTE ON FUNCTION get_database_size_stats() TO anon, authenticated, service_role;
