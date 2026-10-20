# Vantis Local Headed Scraper Suite (Myntra & Ajio)

Standalone local automation package to run headed Myntra and Ajio scrapers using real Google Chrome, persistent login profiles, and direct Supabase database synchronization.

---

## 📁 Directory Structure
```
Ajio_myntra_local_build/
├── run_local_scrapers.py        # Main execution script & interactive CLI
├── scrapers/                    # Production browser JS scrapers (sizes & offers)
│   ├── New_ajio_scraper.js      # Ajio Columbia catalog & offer extraction
│   └── new_myntra_scraper.js    # Myntra PDP size & bank offer enrichment
├── supabase_sync.py             # Direct PostgREST sync to Supabase (products, offers, price_history)
├── build_bundle.py              # Automated PyInstaller bundler script
├── build_bundle.bat             # 1-Click Windows batch script to build .exe
├── scraper_bundle.spec          # PyInstaller bundle specification
├── requirements.txt             # Python dependencies
├── chrome_profile/              # (Auto-created) Local persistent Chrome profile (saved Gmail session)
└── data/                        # (Auto-created) Local backup JSON files
```

---

## 🚀 Quick Start Guide

### Step 1: Install Dependencies
```powershell
pip install -r requirements.txt
playwright install
```

### Step 2: First-Time Google / Gmail Login (Persistent Profile)
To log into your Google Account / Gmail or store accounts so Chrome stays authenticated:
```powershell
python run_local_scrapers.py --login
```
1. Google Chrome will open pointing to Google Account Sign-In.
2. Sign in to your Gmail / Google account or Ajio/Myntra accounts normally.
3. Once logged in, return to the terminal and press **ENTER**.
4. Your authenticated session is permanently stored in the local `chrome_profile/` folder and will be reused automatically.

---

### Step 3: Run Scrapers (Interactive Menu)
```powershell
python run_local_scrapers.py
```
You can select from the interactive menu:
- `1`: Login Mode (Manage Chrome Google / Store login)
- `2`: Scrape Myntra Columbia Products -> Supabase
- `3`: Scrape Ajio Columbia Products -> Supabase
- `4`: Scrape Both (Myntra + Ajio) -> Supabase
- `5`: Quick 1-Page Test Run

Or run via CLI arguments:
```powershell
# Scrape both platforms
python run_local_scrapers.py --scraper all

# Scrape only Myntra
python run_local_scrapers.py --scraper myntra

# Scrape only Ajio
python run_local_scrapers.py --scraper ajio

# Test 1 page of Ajio
python run_local_scrapers.py --scraper ajio --limit 1
```

---

## 📦 How to Create the PyInstaller Bundle (.exe)

When you are ready to compile this into a standalone Windows application:
1. Double-click `build_bundle.bat` OR run:
```powershell
python build_bundle.py
```
2. PyInstaller will package the application into `dist/Vantis_Local_Scraper/`.
3. You can run `dist/Vantis_Local_Scraper/Vantis_Local_Scraper.exe` directly on any Windows PC without Python installed!
