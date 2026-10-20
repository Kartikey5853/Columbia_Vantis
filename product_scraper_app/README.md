# Product Scraper Desktop Application (PySide6 & Playwright)

A high-performance, resilient desktop scraping application built in Python using **PySide6 (Qt for Python)** and **Playwright for Python**. It executes the production JavaScript scraper implementations (`new_myntra_scraper.js` and `New_ajio_scraper.js`) directly in a persistent browser session and synchronizes all products, variant sizes, and promotional offers to **Supabase** via duplicate-safe upserts.

---

## 🌟 Architecture & Features

### 1. Browser-First Persistent Profile
- **Profile Directory**: `%LOCALAPPDATA%\ProductScraper\BrowserProfile`
- **Session Continuity**: Retains all cookies, local storage, sessions, and login states across restarts.
- **Human-Assisted Login / CAPTCHA Handling**: Click **"Open Browser"** to launch Google/Myntra/Ajio, manually log in or solve any anti-bot challenges. All subsequent scrapers reuse the exact same browser profile without profile-lock conflicts.

### 2. Exact Scraper Injection
- Uses `scrapers/New_ajio_scraper.js` and `scrapers/new_myntra_scraper.js` without altering business logic.
- Injects scripts into active origin tabs (`https://www.ajio.com` and `https://www.myntra.com`) with full access to `window`, `fetch`, DOM parsers, and same-origin cookies.
- Bridges real-time progress (`window.__SCRAPER_PROGRESS__` and `window.updateScraperProgress`) directly to PySide6 progress bars and UI logs.

### 3. Variant & Special Offer Normalization
- **Ajio Sizes**: Solves the catalog API omission (where `variantOptions` is absent) by parsing real variant sizes (`UK 9`, `M`, `XXL`, `One Size`, etc.) from vendor SKUs (`{style}-{color}-{size}`).
- **Myntra Sizes**: Flattens and groups individual size records by `product_id`, ensuring all available sizes are retained rather than overwritten.
- **Promotional Offers**: Captures coupon codes (e.g., `COLUMBIA500`, `TRENDS`, `FLAT300`), bank discounts, and minimum transaction thresholds.

### 4. Duplicate-Safe Supabase Sync
- Upserts directly into the `products` table using `on_conflict=scraper_id,source_product_id` against the unique constraint `uq_product_scraper_source`.
- Automatically logs price snapshots into the `price_history` table for historical price tracking and Data Analysis charts.
- Local backups are automatically saved as JSON files in `%LOCALAPPDATA%\ProductScraper\Data\`.

---

## 📋 Prerequisites & Installation

### 1. Python Environment
Ensure Python 3.10+ is installed:
```powershell
python --version
```

### 2. Install Dependencies
Navigate into the `product_scraper_app` directory and install the required packages:
```powershell
cd product_scraper_app
pip install -r requirements.txt
```

### 3. Install Playwright Chromium Browser
```powershell
playwright install chromium
```

---

## 🚀 Running the Application

Launch the desktop GUI:
```powershell
python main.py
```

### GUI Operations
| Button | Description |
| :--- | :--- |
| **🌐 Open Browser** | Launches the persistent Chromium browser window to Google/e-commerce sites. Use this to verify logins or bypass CAPTCHAs. |
| **🛒 Scrape Myntra** | Navigates to Myntra, runs `new_myntra_scraper.js`, consolidates sizes, and syncs to Supabase. |
| **🏷️ Scrape AJIO** | Navigates to Ajio, runs `New_ajio_scraper.js`, extracts SKU sizes and offers, and syncs to Supabase. |
| **⚡ Scrape Both** | Sequentially executes both Myntra and Ajio scraping tasks. |
| **⏹️ Stop Scraping** | Gracefully stops the active scraping task without corrupting the persistent browser profile. |

---

## 📁 Directory Structure
```
product_scraper_app/
├── main.py                   # PySide6 desktop application & Playwright worker
├── requirements.txt          # Python dependencies (PySide6, playwright, httpx, python-dotenv)
├── README.md                 # This documentation file
└── scrapers/
    ├── New_ajio_scraper.js   # Production Ajio scraper
    └── new_myntra_scraper.js # Production Myntra scraper
```
