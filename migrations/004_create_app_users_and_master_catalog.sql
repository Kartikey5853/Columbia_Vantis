-- =========================================================================
-- Migration: 004_create_app_users_and_master_catalog.sql
-- Description: Employee user authentication, profile data, JWT sessions, and Master Excel catalog in Supabase
-- Idempotent: Can be executed multiple times safely in Supabase SQL Editor
-- =========================================================================

-- Enable pgcrypto for UUID generation if needed
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -------------------------------------------------------------------------
-- 1. Table: app_users (Employee logins, passwords, avatars, and roles)
-- -------------------------------------------------------------------------
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

-- -------------------------------------------------------------------------
-- 2. Table: user_sessions (JWT session tokens, login history, IP & device info)
-- -------------------------------------------------------------------------
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

-- -------------------------------------------------------------------------
-- 3. Table: master_catalog (3,513 rows of master catalog data in Supabase)
-- -------------------------------------------------------------------------
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
-- kartikey (kartikey123) and raj (raj123)
INSERT INTO app_users (username, password_hash, display_name, role, avatar_url, has_master_excel, master_excel_filename, master_excel_records)
VALUES 
    (
        'kartikey',
        '2b00fd270242e8c9ef2fbd25c9916facb7eee85db31cb7a34570566343b0abe7',
        'Kartikey',
        '',
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
        true,
        'Master_Catalog_Columbia.xlsx',
        3513
    ),
    (
        'raj',
        '048ce982a3172bc31a1590a34a5d7e5ebfc885b97db7941937256e359628c08d',
        'Raj',
        '',
        'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80',
        true,
        'Master_Catalog_Columbia.xlsx',
        3513
    ),
    (
        'krishana',
        'e94e3e8e234ee80ad22b3681c24906dd3cf9bb03e7a2952bde9c844db230f86c',
        'Krishana',
        '',
        NULL,
        true,
        'Master_Catalog_Columbia.xlsx',
        3513
    )
ON CONFLICT (username) DO NOTHING;
