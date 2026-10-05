# Columbia Sportswear India & Tata CLiQ Scraper Architecture

A unified, lightweight, crash-safe scraping and Supabase persistence architecture designed for **Columbia Sportswear India** and **Tata CLiQ (Columbia)** scrapers, using the existing browser JS scrapers and optimized for 512 MB RAM environments (such as Render).

---

## 1. Architecture Overview

```
                         SCRAPERS
              ┌─────────────────────────────┐
              │  columbia_scraper.js        │ (Shopify GraphQL, ~20-30s in browser)
              │  tata_scraper.js            │ (Tata BFF APIs, concurrency=2, 7s timeout)
              └──────────────┬──────────────┘
                             │
                             ▼
                        runner.py
                  (Single Shared Browser)
                             │
                             ▼
                  NORMALIZED PRODUCT MODEL
                 (persistence/models.py)
                             │
                             ▼
                 SHARED PERSISTENCE LAYER
              ┌─────────────────────────────┐
              │ persistence/                │
              │   ├── supabase_client.py    │ (Async httpx PostgREST client)
              │   ├── product_store.py      │ (Canonical products & price changes)
              │   ├── run_store.py          │ (Scrape runs & Kolkata business date)
              │   ├── checkpoint_store.py   │ (Resumable pages & product progress)
              │   ├── exporter.py           │ (Atomic local rolling backup)
              │   └── diagnostics.py        │ (Real PostgreSQL storage metrics)
              └──────────────┬──────────────┘
                             │
                             ▼
                     SUPABASE DATABASE
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
     products          price_history        scrape_runs
 (one canonical row   (only changes on    (per business date
  per source_id)       price variance)     & active lock)
         │                   │                   │
         ▼                   ▼                   ▼
     variants        scrape_listing_pages  scrape_product_progress
   (jsonb field)      (page-level status)   (per-product retry status)
```

---

## 2. Supabase Setup & Database Migration

### Step 1: Execute SQL Migration in Supabase Dashboard
1. Open your Supabase project: [https://supabase.com/dashboard](https://supabase.com/dashboard)
2. Go to **SQL Editor** in the left sidebar.
3. Open `migrations/001_initial_schema.sql` from this repository.
4. Copy its contents, paste into the SQL editor, and click **Run**.

### Step 2: Verify Table Activation
Run:
```bash
python apply_migrations.py
```
This confirms that `scrapers`, `products`, `price_history`, `scrape_runs`, `scrape_listing_pages`, and `scrape_product_progress` are active and accessible in Supabase.

---

## 3. Running Scrapers Locally on Your PC

### Step 1: Run Columbia Scraper (~25-30 seconds)
Columbia Sportswear fetches all products in one quick run:
```bash
python runner.py columbia
```
This will:
- Launch a single lean browser tab (blocking unnecessary image/tracking assets).
- Run `columbia_scraper.js` to collect all products via Shopify GraphQL.
- Close the browser tab immediately to reclaim memory.
- Upsert all canonical products into the `products` table in Supabase.
- Insert initial price entries into `price_history`.
- Atomically export a local backup to `data/columbia/columbia_data.json`.

### Step 2: Run Tata CLiQ Scraper in Test Mode (10 Products)
To verify Tata CLiQ with variants quickly without running the full 2,100+ product catalog:
```bash
python runner.py tata --limit 10
```
This will:
- Open a lean browser tab for `tatacliq.com`.
- Collect the first page of products and limit variant processing to 10 products.
- Fetch variants with 2 workers and 7s timeouts.
- Close the tab immediately.
- Persist canonical products and price history to Supabase.
- Export rolling backup to `data/tata/tata_data.json`.

### Step 3: Run Sequential Pipeline
Runs Columbia followed by Tata CLiQ sequentially:
```bash
python runner.py pipeline
```

---

## 4. Checking Data in Supabase

1. **Supabase Dashboard**:
   - Go to **Table Editor** > `products`: view canonical products per source (`scraper_id`).
   - Go to `price_history`: view historical price changes over time.
   - Go to `scrape_runs`: view execution records and business dates (`Asia/Kolkata`).
   - Go to `scrape_product_progress`: view product-level completed status and variant counts.

2. **Storage Diagnostic CLI**:
   ```bash
   python -m persistence.diagnostics
   ```
   Reports table row counts and actual disk sizes in MB.

---

## 5. Automated Tests

Run the full 10-point test suite:
```bash
python run_tests.py
```

Tests verify:
- Product existence & attribute mapping
- Product count consistency
- Duplicate prevention on `(scraper_id, source_product_id)`
- Price history deduplication (only records changes)
- Crash / resume recovery without duplicate rows
- Failed product retry logic
- HTTP 429 and network error resilience
- Zero variants handling
- Listing page checkpoints
- Supabase storage size measurement

---

## 6. Pushing Changes & Production Deployment (Render 512 MB)

1. Review and commit changes:
   ```bash
   git status
   git add .
   git commit -m "feat: unified browser scraping and Supabase persistence architecture"
   git push origin main
   ```

2. Render Configuration:
   - Environment Variables in Render:
     - `SHOPIFY_TOKEN`
     - `SUPABASE_URL`
     - `SUPABASE_KEY` (or `SUPABASE_SECRET_KEY`)
   - Build Command: `pip install -r requirements.txt && playwright install chromium`
   - Start Command: `uvicorn api:app --host 0.0.0.0 --port $PORT`
