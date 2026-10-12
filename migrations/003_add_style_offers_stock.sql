-- =========================================================================
-- Migration: 003_add_style_offers_stock.sql
-- Description: Adds optional style, stock, and offers columns to products
-- Idempotent: Can be executed multiple times safely
-- =========================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'products' AND column_name = 'style'
    ) THEN
        ALTER TABLE products ADD COLUMN style TEXT;
        CREATE INDEX IF NOT EXISTS idx_products_style ON products(style);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'products' AND column_name = 'stock'
    ) THEN
        ALTER TABLE products ADD COLUMN stock INT DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'products' AND column_name = 'offers'
    ) THEN
        ALTER TABLE products ADD COLUMN offers JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;
