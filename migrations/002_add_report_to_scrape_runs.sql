-- =========================================================================
-- Migration: 002_add_report_to_scrape_runs.sql
-- Description: Adds JSONB report column to scrape_runs for database reports
-- Idempotent: Can be executed multiple times safely
-- =========================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'scrape_runs' AND column_name = 'report'
    ) THEN
        ALTER TABLE scrape_runs ADD COLUMN report JSONB DEFAULT '{}'::jsonb;
    END IF;
END $$;
