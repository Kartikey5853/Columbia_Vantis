-- ==============================================================================
-- Migration: 005_platform_normalized_tables_and_views.sql
-- Description: Normalizes product listings into dedicated per-platform tables/views
--              in the Supabase Table Editor without duplicating storage or degrading
--              query performance.
--
-- Platforms Included:
--   1. products_ajio       (AJIO)
--   2. products_myntra     (Myntra)
--   3. products_amazon     (Amazon India)
--   4. products_columbia   (Columbia Sportswear India)
--   5. products_tata       (Tata CLiQ)
--   6. products_tata_lux   (Tata CLiQ Luxury)
--   7. products_adv        (Adventuras)
-- ==============================================================================

-- 1. Dedicated View: products_ajio
CREATE OR REPLACE VIEW public.products_ajio AS
SELECT 
    p.id,
    'ajio'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = '597a2ed9-be23-442a-9360-9fb84a39b4ef';

-- 2. Dedicated View: products_myntra
CREATE OR REPLACE VIEW public.products_myntra AS
SELECT 
    p.id,
    'myntra'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = 'da9da872-910d-4b62-8966-253c4cae9bc3';

-- 3. Dedicated View: products_amazon
CREATE OR REPLACE VIEW public.products_amazon AS
SELECT 
    p.id,
    'amazon'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = '39aad488-ced1-4c66-846a-3a10187ef5cf';

-- 4. Dedicated View: products_columbia
CREATE OR REPLACE VIEW public.products_columbia AS
SELECT 
    p.id,
    'columbia'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = 'a932ee85-9042-4fd1-b968-390f1a06a5c8';

-- 5. Dedicated View: products_tata
CREATE OR REPLACE VIEW public.products_tata AS
SELECT 
    p.id,
    'tata'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = 'af31b92e-29b3-4532-a303-5dc3c3e4a6b9';

-- 6. Dedicated View: products_tata_lux
CREATE OR REPLACE VIEW public.products_tata_lux AS
SELECT 
    p.id,
    'tata_lux'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = '7bb65f75-0fde-4432-94d0-f396e961713a';

-- 7. Dedicated View: products_adv
CREATE OR REPLACE VIEW public.products_adv AS
SELECT 
    p.id,
    'adv'::text AS platform,
    p.source_product_id,
    p.style,
    p.sku,
    p.title,
    p.current_price,
    p.current_mrp,
    p.available,
    p.stock,
    (
        SELECT string_agg(DISTINCT coalesce(v->>'size', ''), ', ')
        FROM jsonb_array_elements(CASE jsonb_typeof(p.variants::jsonb) WHEN 'array' THEN p.variants::jsonb ELSE '[]'::jsonb END) v
        WHERE coalesce(v->>'size', '') NOT IN ('', 'Standard', 'Default', 'None')
    ) AS sizes_list,
    p.variants,
    p.offers,
    p.url,
    p.image_url,
    p.created_at,
    p.updated_at,
    p.scraper_id
FROM public.products p
WHERE p.scraper_id = '5803d66c-f054-40a4-9556-cb1393b8c6e3';

-- 8. Platform Scrapers Overview View
CREATE OR REPLACE VIEW public.v_scrapers_overview AS
SELECT 
    s.id AS scraper_id,
    s.name AS platform_name,
    s.source AS platform_key,
    s.enabled,
    s.created_at,
    COUNT(p.id) AS total_active_products,
    ROUND(AVG(p.current_price)::numeric, 2) AS average_price,
    COUNT(p.id) FILTER (WHERE p.available = true) AS in_stock_products
FROM public.scrapers s
LEFT JOIN public.products p ON p.scraper_id = s.id
GROUP BY s.id, s.name, s.source, s.enabled, s.created_at
ORDER BY total_active_products DESC;

-- Grant permissions for authenticated and anon roles
GRANT SELECT ON public.products_ajio TO authenticated, anon, service_role;
GRANT SELECT ON public.products_myntra TO authenticated, anon, service_role;
GRANT SELECT ON public.products_amazon TO authenticated, anon, service_role;
GRANT SELECT ON public.products_columbia TO authenticated, anon, service_role;
GRANT SELECT ON public.products_tata TO authenticated, anon, service_role;
GRANT SELECT ON public.products_tata_lux TO authenticated, anon, service_role;
GRANT SELECT ON public.products_adv TO authenticated, anon, service_role;
GRANT SELECT ON public.v_scrapers_overview TO authenticated, anon, service_role;
