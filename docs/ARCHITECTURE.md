# VANTIS Engineering Deep-Dive: Sub-512MB RAM Architecture & WAF Bypass

This technical document details the two core engineering breakthroughs powering the VANTIS Retail Intelligence Engine:
1. **Sub-512MB RAM Constraint Optimization** (Running full-scale retail synchronization without OOM)
2. **Enterprise Anti-Bot & WAF Bypass** (Bypassing Akamai Bot Manager and PerimeterX via Direct Backend Architecture)

---

## 1. Sub-512MB RAM Optimization Architecture

### The Problem
Traditional e-commerce intelligence systems consume several gigabytes of resident memory:
- Scraping pipelines keep large JSON trees (10,000+ products with 50,000+ variants) in Python dictionaries.
- Headless browsers (Chromium/Playwright) consume 400MB+ per page due to CSS styling, DOM tree parsing, image rendering, and font decoding.
- Multi-worker concurrency quickly triggers kernel Out-Of-Memory (OOM) kills on low-cost 512MB cloud servers (Render free/starter tiers, AWS t3.nano, low-cost VPSs).

### The Solution: Zero-In-Memory Disk B-Trees & Aggressive Asset Interception

```
[ Ingest Stream ]
       │
       ▼ (100-item chunks)
┌──────────────────────────────────────────────┐
│       SQLite Compound B-Tree Index           │
│   (Indexed on: sku, ean, style, platform)    │
│            resident RAM: ~15 MB              │
└──────────────────────┬───────────────────────┘
                       │
                       ▼ (Microsecond disk lookup)
              [ 87,197 Indexed Keys ]
              [ 42,595 Ops/Sec Benchmark ]
```

1. **Disk-Backed Compound B-Tree Indexing**:
   - Instead of in-memory hash maps, VANTIS maintains a compact SQLite catalog database with compound B-Tree indexes on `(sku, ean, style_code, source_id, platform)`.
   - Microsecond lookup times across 87,000+ indexed terms while resident RAM stays under **15 MB**.
   - Achieved benchmark: **42,595 query operations/second**.

2. **Network Engine Request Abortions**:
   - In all browser-driven stages, Playwright routes intercept and immediately cancel:
     - Images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`)
     - Fonts (`.woff`, `.woff2`, `.ttf`)
     - Stylesheets (`.css`)
     - Tracking/Ad pixels (Google Analytics, Facebook Pixel, Criteo, Hotjar)
   - Cuts Chromium tab memory from 450MB down to **under 85MB**.

3. **Eager Lifecycle Reclamation & Explicit GC Passes**:
   - Browser tabs close immediately following data extraction.
   - Processing loops invoke Python garbage collection (`gc.collect()`) after batch upserts.
   - Streams 100-row records directly to PostgREST to prevent response buffering.

---

## 2. Anti-Bot & WAF Bypass Strategy

### The Threat Model
Tier-1 e-commerce platforms (AJIO, Tata CLiQ, Myntra) protect their product pages using Akamai Bot Manager, PerimeterX (Human Security), and Cloudflare WAF.
These systems monitor:
- Rapid successive requests to Product Detail Page (PDP) URLs.
- TLS client hello fingerprints (JA3/JA4).
- Headless browser canvas/audio/WebGL anomalies.
- Client IP reputation (datacenter ASNs like AWS, GCP, DigitalOcean).

Heavy PDP burst scraping results in immediate `HTTP 403 Forbidden` responses, CAPTCHA blocks, and temporary IP bans.

### The Architecture: Decoupled Backend Catalog Extraction & Master Mapping

```
Traditional Scraper (Banned by WAF):
Catalog Listing ──> 2,000 PDP Requests ──> [Akamai 403 Forbidden] ──> Failure

VANTIS Anti-Bot Architecture:
Catalog Listing ──> BFF Backend Discovery (Native JSON)
                         │
                         ▼
             Master Catalog Mapping Engine
                         │
                         ▼
        Deterministic Sibling Size Run Synthesis
       (0 PDP requests, 0ms latency, 100% success)
```

1. **Direct Backend API Reverse-Engineering**:
   - Bypasses HTML rendering entirely by targeting internal Backend-For-Frontend (BFF) endpoints and native GraphQL APIs used by the platform's mobile applications.
   - Payloads return structured JSON directly without executing front-end DOM scripts.

2. **Deterministic Master Catalog Mapping**:
   - Why hit 2,000 separate PDP pages to find which sizes exist for a shoe or jacket?
   - VANTIS leverages authoritative Master Catalog Mappings to synthesize complete sibling size runs (e.g., S, M, L, XL, XXL) with exact brand style numbers and international EAN barcodes in **0ms**.
   - Eliminates 99.8% of network requests that would otherwise trigger WAF anomaly detection.

3. **In-Session Native JavaScript Execution**:
   - Where sessions are tied to dynamic tokens (e.g. Myntra/AJIO), requests are executed inside an active browser page via `page.evaluate(fetch, ...)`.
   - Every request carries valid Akamai cookies, correct browser headers, and a genuine TLS fingerprint matching the real browser engine.

4. **Distributed Standalone Nodes (`Vantis_Local_Scraper.exe`)**:
   - Standalone PyInstaller executable runs scrapers from residential network connections.
   - Encrypted PostgREST streams automatically relay parsed records to the central cloud Supabase instance, preventing cloud IP blocking.
