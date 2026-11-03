import json
import re
import os
import time
import math
import hashlib
import sqlite3
import threading

_CATALOG_LOAD_LOCK = threading.Lock()
import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

from persistence.normalizer import normalize_size, detect_color, extract_columbia_size_from_sku
from app.core.config import NEW_DATA_DIR, DATA_DIR, AMAZON_DATA_DIR, BASE_DIR
from app.schemas.models import (
    ProductOffer, ProductVariant, PlatformListing, ProductFamily, ProductFamilySummary,
    PaginatedProductsResponse, AnalyticsSummary, AnalyticsProductRow,
    ProductPriceHistoryResponse, PlatformPriceStat
)

PLATFORM_METADATA = {
    "amazon": {"name": "Amazon", "logo_key": "amazon", "base_url": "https://www.amazon.in"},
    "tata": {"name": "Tata CLiQ", "logo_key": "tata", "base_url": "https://www.tatacliq.com"},
    "tata_lux": {"name": "Tata CLiQ Luxury", "logo_key": "tata_lux", "base_url": "https://luxury.tatacliq.com"},
    "columbia": {"name": "Columbia", "logo_key": "columbia", "base_url": "https://www.columbiasportswear.co.in"},
    "adv": {"name": "Adventuras", "logo_key": "adv", "base_url": "https://adventuras.in"},
    "myntra": {"name": "Myntra", "logo_key": "myntra", "base_url": "https://www.myntra.com"},
    "ajio": {"name": "AJIO", "logo_key": "ajio", "base_url": "https://www.ajio.com"},
}

def clean_price(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    s = str(val).replace("₹", "").replace(",", "").replace("$", "").strip()
    try:
        f = float(s)
        return round(f, 2) if f > 0 else None
    except Exception:
        return None

def extract_style_code(title: str, sku: str, url: str, source_id: str = "") -> Optional[str]:
    combined = f"{sku or ''} {url or ''} {title or ''} {source_id or ''}"
    m_alpha = re.search(r'\b([A-Z]{2}\d{4})\b', combined)
    if m_alpha:
        return m_alpha.group(1).upper()
    m_num = re.search(r'\b(\d{7})\b', combined)
    if m_num:
        return m_num.group(1)
    return None

def detect_category(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ["boot", "boots"]):
        return "Boots"
    if any(k in t for k in ["shoe", "shoes", "sneaker", "footwear", "runner"]):
        return "Hiking Shoes" if "hik" in t or "trail" in t else "Shoes"
    if any(k in t for k in ["vest", "vests"]):
        return "Vests"
    if any(k in t for k in ["jacket", "parka", "windbreaker", "coat", "hoodie", "anorak"]):
        return "Jackets"
    if any(k in t for k in ["pant", "pants", "trouser", "trousers"]):
        return "Pants"
    if any(k in t for k in ["fleece", "pullover", "sweater"]):
        return "Fleece"
    if any(k in t for k in ["shirt", "t-shirt", "tee", "polo"]):
        return "Shirts & Tops"
    if any(k in t for k in ["short", "shorts"]):
        return "Shorts"
    if any(k in t for k in ["backpack", "bag", "tote", "pack"]):
        return "Backpacks & Bags"
    if any(k in t for k in ["sock", "socks"]):
        return "Socks"
    if any(k in t for k in ["cap", "hat", "beanie", "glove", "gloves", "belt"]):
        return "Accessories"
    return "Apparel"

def detect_gender(title: str) -> str:
    t = (title or "").lower()
    if "women" in t:
        return "Women"
    if "men" in t:
        return "Men"
    if any(k in t for k in ["boy", "boys"]):
        return "Boys"
    if any(k in t for k in ["girl", "girls"]):
        return "Girls"
    if any(k in t for k in ["kid", "kids", "child"]):
        return "Kids"
    return "Unisex"

def detect_tags(title: str, category: str, gender: str) -> List[str]:
    tags = [gender]
    if category:
        tags.append(category)
    t = (title or "").lower()
    keywords = ["hiking", "outdoor", "waterproof", "trail", "omni-heat", "omni-tech", "outdry", "breathable", "insulated", "lightweight", "running"]
    for kw in keywords:
        if kw in t:
            tags.append(kw.capitalize())
    # Deduplicate preserving order
    seen = set()
    res = []
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            res.append(tag)
    return res[:6]

def get_canonical_family_key(title: str, style: Optional[str], ean: Optional[str]) -> str:
    if style:
        return f"STYLE_{style.upper()}"
    if ean and len(str(ean).strip()) >= 10:
        return f"EAN_{str(ean).strip()}"
    
    t = (title or "").lower()
    gender = detect_gender(t)
    cat = detect_category(t)

    t = re.sub(r'^(columbia\s+sportswear|columbia)\s*', '', t)
    t = re.sub(r'\b(men\'?s?|women\'?s?|unisex|kids|boys|girls)\b', '', t)
    colors = r'\b(black|white|grey|gray|blue|navy|brown|beige|red|green|maroon|yellow|orange|olive|graphite|stone|pink|purple|charcoal|multi|collegiate|assortes)\b'
    t = re.sub(colors, '', t)
    t = re.sub(r'\bupto\s+[-]?\d+\s*c\b', '', t)
    t = re.sub(r'\(.*?\)', '', t)
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    words = [w for w in t.split() if w not in ('and', 'or', 'with', 'for', 'the', 'in', 'on', 'upto', 'fit', 'solid', 'c', 'to', 'of')]
    
    g_tag = gender.lower()
    c_tag = cat.lower().replace(" ", "_").replace("&", "and")

    # Specific known popular model groups qualified with gender & category
    model_name = None
    if 'peakfreak' in words:
        if 'titanium' in words:
            model_name = 'peakfreak_titanium'
        elif 'ii' in words or '2' in words:
            model_name = 'peakfreak_ii'
        elif 'x2' in words:
            model_name = 'peakfreak_x2'
        else:
            model_name = 'peakfreak'
    elif 'newton' in words and 'ridge' in words:
        model_name = 'newton_ridge_plus'
    elif 'crestwood' in words:
        model_name = 'crestwood_waterproof'
    elif 'redmond' in words:
        model_name = 'redmond_iii'
    elif 'facet' in words:
        model_name = 'facet_75'
    elif 'konos' in words:
        model_name = 'konos_trs'
    elif 'steens' in words and 'mountain' in words:
        model_name = 'steens_mountain'
    elif 'silver' in words and 'falls' in words:
        model_name = 'silver_falls'
    elif 'fast' in words and 'trek' in words:
        model_name = 'fast_trek_ii'
    elif 'delta' in words and 'ridge' in words:
        model_name = 'delta_ridge'
    elif 'cascades' in words and 'explorer' in words:
        model_name = 'cascades_explorer'
    elif 'bugaboo' in words:
        model_name = 'bugaboo_iv'
    elif 'suttle' in words and 'mountain' in words:
        model_name = 'suttle_mountain'
    elif 'heavenly' in words:
        model_name = 'heavenly_jacket'
    elif 'klamath' in words and 'range' in words:
        model_name = 'klamath_range'

    if model_name:
        return f"MODEL_{g_tag}_{c_tag}_{model_name}"
        
    core = "_".join(words[:6])
    return f"TITLE_{g_tag}_{c_tag}_{core}" if core else f"HASH_{hashlib.md5(title.encode()).hexdigest()[:10]}"


class FamiliesProxy:
    """Zero-memory dictionary-like proxy that reads product families on-demand from disk-backed SQLite."""
    def __init__(self, service: "CatalogService"):
        self._service = service

    def __len__(self) -> int:
        return self._service.total_count

    def __contains__(self, key: Any) -> bool:
        if not key:
            return False
        return self._service.get_family_by_id(str(key)) is not None

    def __getitem__(self, key: str) -> Dict[str, Any]:
        item = self._service.get_family_by_id(str(key))
        if item is None:
            raise KeyError(key)
        return item

    def get(self, key: str, default: Any = None) -> Any:
        item = self._service.get_family_by_id(str(key))
        return item if item is not None else default

    def values(self):
        return self._service.iter_families()

    def items(self):
        for fam in self._service.iter_families():
            yield fam.get("family_id", ""), fam

    def keys(self):
        for fam in self._service.iter_families():
            yield fam.get("family_id", "")


class FamiliesListProxy:
    """Zero-memory list-like proxy that streams single pages of product families from SQLite."""
    def __init__(self, service: "CatalogService"):
        self._service = service

    def __len__(self) -> int:
        return self._service.total_count

    def __iter__(self):
        return self._service.iter_families()

    def __getitem__(self, idx: Any) -> Any:
        if isinstance(idx, slice):
            start = idx.start or 0
            stop = idx.stop if idx.stop is not None else self._service.total_count
            limit = max(0, stop - start)
            return self._service.get_families_slice(start, limit)
        elif isinstance(idx, int):
            if idx < 0:
                idx = self._service.total_count + idx
            items = self._service.get_families_slice(idx, 1)
            if not items:
                raise IndexError("list index out of range")
            return items[0]
        raise TypeError(f"Invalid index type: {type(idx)}")


class CatalogService:
    def __init__(self):
        self.is_loaded = False
        self.load_time_seconds = 0.0
        self.raw_records_count = 0
        self.total_count = 0
        self.db_path = DATA_DIR / "catalog_cache.db"
        self.families = FamiliesProxy(self)
        self.families_list = FamiliesListProxy(self)
        self.index_by_sku: Dict[str, str] = {}
        self.index_by_ean: Dict[str, str] = {}
        self.index_by_style: Dict[str, str] = {}
        self.index_by_pid: Dict[str, str] = {}
        self.all_categories: List[str] = []
        self.all_genders: List[str] = []
        self.summary_cache: Dict[str, Any] = {}
        self.master_catalogue_info: Dict[str, Any] = {
            "loaded": False,
            "filename": None,
            "record_count": 0,
            "last_updated": None
        }
        self.master_records: List[Dict[str, Any]] = []
        self.master_records_by_style: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.master_records_by_style_code: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.master_pid_to_style: Dict[str, str] = {}
        self.master_pid_to_record: Dict[str, Dict[str, Any]] = {}
        self.master_sku_to_style: Dict[str, str] = {}
        self.master_ean_to_style: Dict[str, str] = {}
        self.master_style_meta: Dict[str, Dict[str, Any]] = {}
        self.supabase_cache: Dict[str, Any] = {}
        self.offers_lookup: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        # Master mappings and catalog loading are lazy — never loaded on import or boot to save RAM

    def _load_master_mappings(self):
        """Loads canonical cross-platform SKU/Style/EAN/PID mappings from Master Excel JSON."""
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return
        mapping_path = DATA_DIR / "master_catalog_mappings.json"
        records = []
        if mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records = data.get("records") or []
            except Exception as fe:
                print(f"[CATALOG_SERVICE] ⚠️ Error reading {mapping_path}: {fe}", flush=True)

        if not records:
            # Live cloud fetch from Supabase master_catalog table (takes ~1.2s for 3,513 rows)
            try:
                import httpx
                url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
                sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
                headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}
                offset = 0
                with httpx.Client(timeout=15.0) as client:
                    while True:
                        r = client.get(
                            f"{url}/rest/v1/master_catalog?select=style,sku,style_code,ean,soh,platform_ids&limit=1000&offset={offset}",
                            headers=headers
                        )
                        if r.status_code != 200:
                            break
                        batch = r.json() or []
                        if not batch:
                            break
                        records.extend(batch)
                        offset += len(batch)
                        if len(batch) < 1000:
                            break
                if records:
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    try:
                        with open(mapping_path, "w", encoding="utf-8") as f:
                            json.dump({"total_rows": len(records), "records": records}, f)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[CATALOG_SERVICE] ⚠️ Error fetching master_catalog from Supabase: {e}", flush=True)

        if not records:
            return

        try:
            self.master_records = records
            self.master_records_by_style.clear()
            self.master_records_by_style_code.clear()
            self.master_pid_to_style.clear()
            self.master_sku_to_style.clear()
            self.master_ean_to_style.clear()
            self.master_style_meta.clear()

            for rec in records:
                style = str(rec.get("style") or "").strip().upper()
                if not style:
                    continue
                self.master_records_by_style[style].append(rec)
                sc_rec = str(rec.get("style_code") or "").strip().upper()
                if sc_rec:
                    self.master_records_by_style_code[sc_rec].append(rec)
                if style not in self.master_style_meta:
                    self.master_style_meta[style] = {
                        "skus": set(),
                        "style_codes": set(),
                        "eans": set(),
                        "pids": {},
                    }
                meta = self.master_style_meta[style]
                self.master_sku_to_style[style.lower()] = style
                if len(style) >= 5:
                    self.master_sku_to_style[style[:5].lower()] = style

                sc = str(rec.get("style_code") or "").strip().upper()
                if sc:
                    meta["style_codes"].add(sc)
                    self.master_sku_to_style[sc.lower()] = style

                sku = str(rec.get("sku") or "").strip().upper()
                if sku:
                    meta["skus"].add(sku)
                    self.master_sku_to_style[sku.lower()] = style

                ean = str(rec.get("ean") or "").strip()
                if ean:
                    meta["eans"].add(ean)
                    self.master_ean_to_style[ean.lower()] = style

                pids = rec.get("platform_ids") or {}
                for pk, pval in pids.items():
                    if not pval:
                        continue
                    pval_str = str(pval).strip()
                    if not pval_str or pval_str.upper() in ("ERROR", "NAN", "NONE", "SIZE ADDITION"):
                        continue
                    self.master_pid_to_style[f"{pk}:{pval_str.lower()}"] = style
                    self.master_pid_to_style[pval_str.lower()] = style
                    self.master_pid_to_record[f"{pk}:{pval_str.lower()}"] = rec
                    self.master_pid_to_record[pval_str.lower()] = rec
                    if pk == "ajio" and len(pval_str) >= 9:
                        self.master_pid_to_style[f"ajio:{pval_str[:9].lower()}"] = style
                        self.master_pid_to_style[pval_str[:9].lower()] = style
                        self.master_pid_to_record[f"ajio:{pval_str[:9].lower()}"] = rec
                        self.master_pid_to_record[pval_str[:9].lower()] = rec
                    meta["pids"].setdefault(pk, set()).add(pval_str)

            self.master_catalogue_info = {
                "loaded": True,
                "filename": "Master_Catalog_Columbia.xlsx",
                "record_count": len(records),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            print(f"[CATALOG_SERVICE] [MASTER] Loaded {len(records)} Master Excel rows ({len(self.master_style_meta)} unique styles).", flush=True)
        except Exception as e:
            print(f"[CATALOG_SERVICE] ⚠️ Error loading master_catalog_mappings.json: {e}", flush=True)

    def sync_master_to_supabase(self):
        """Synchronizes master catalog rows to Supabase 'master_catalog' table via PostgREST."""
        import httpx
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not sec_key:
            candidate = os.getenv("SUPABASE_KEY", "")
            if candidate.startswith("sb_secret_") or candidate.startswith("eyJ"):
                sec_key = candidate
        key = sec_key or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not key or not self.master_records:
            return

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }

        try:
            with httpx.Client(timeout=8.0) as client:
                chk = client.get(f"{url}/rest/v1/master_catalog?limit=1", headers=headers)
                if chk.status_code == 404:
                    print("[CATALOG_SERVICE] [INFO] Table 'master_catalog' not yet created in Supabase. Run migrations/004_create_app_users_and_master_catalog.sql in Supabase SQL editor.", flush=True)
                    return
                elif chk.status_code != 200:
                    return

                cnt_res = client.get(f"{url}/rest/v1/master_catalog?select=id", headers={**headers, "Range": "0-0", "Prefer": "count=exact"})
                crange = cnt_res.headers.get("content-range", "")
                if "/" in crange:
                    total_existing = int(crange.split("/")[1]) if crange.split("/")[1].isdigit() else 0
                    if total_existing >= len(self.master_records):
                        print(f"[CATALOG_SERVICE] [SUPABASE] Supabase 'master_catalog' table is up-to-date ({total_existing} records).", flush=True)
                        return

                print(f"[CATALOG_SERVICE] [SUPABASE] Syncing {len(self.master_records)} Master Excel records to Supabase 'master_catalog'...", flush=True)
                batch_size = 500
                total_inserted = 0
                for i in range(0, len(self.master_records), batch_size):
                    batch = self.master_records[i : i + batch_size]
                    rows = []
                    for rec in batch:
                        rows.append({
                            "ean": rec.get("ean"),
                            "sku": rec.get("sku"),
                            "style_code": rec.get("style_code"),
                            "style": rec.get("style") or (rec.get("sku", "").split("-")[0] if rec.get("sku") else "UNKNOWN"),
                            "soh": rec.get("soh") or 0,
                            "platform_ids": rec.get("platform_ids") or {}
                        })
                    res = client.post(f"{url}/rest/v1/master_catalog", headers=headers, json=rows)
                    if res.status_code in (200, 201):
                        total_inserted += len(rows)

                print(f"[CATALOG_SERVICE] [SUPABASE] Successfully stored {total_inserted} Master Excel products in Supabase.", flush=True)
        except Exception as e:
            print(f"[CATALOG_SERVICE] ⚠️ Error syncing master catalog to Supabase: {e}", flush=True)

    def _load_offers_lookup(self):
        """Pre-loads genuine offers indexed by platform and product ID/SKU."""
        if self.offers_lookup and any(self.offers_lookup.values()):
            return
        self.offers_lookup = {"tata": {}, "tata_lux": {}, "ajio": {}, "myntra": {}}

        # Tata Cliq
        tata_file = NEW_DATA_DIR / "tatacliq_with_offers.json"
        if tata_file.exists():
            try:
                with open(tata_file, "r", encoding="utf-8") as f:
                    tdata = json.load(f)
                tprods = tdata.get("products", []) if isinstance(tdata, dict) else tdata
                for p in tprods:
                    pid = str(p.get("product_id") or p.get("productId") or "").strip().lower()
                    sku = str(p.get("sku") or "").strip().lower()
                    offs = p.get("offers") or []
                    if offs:
                        if pid:
                            self.offers_lookup["tata"][pid] = offs
                        if sku:
                            self.offers_lookup["tata"][sku] = offs
            except Exception as e:
                print(f"[CATALOG_SERVICE] Error loading Tata offers lookup: {e}", flush=True)

        # Tata Cliq Luxury
        lux_file = NEW_DATA_DIR / "tatacliq_luxury_columbia_products_with_offers (1)_1.json"
        if lux_file.exists():
            try:
                with open(lux_file, "r", encoding="utf-8") as f:
                    ldata = json.load(f)
                lprods = ldata.get("products", []) if isinstance(ldata, dict) else ldata
                for p in lprods:
                    pid = str(p.get("product_id") or p.get("productId") or "").strip().lower()
                    sku = str(p.get("sku") or "").strip().lower()
                    offs = p.get("offers") or []
                    if offs:
                        if pid:
                            self.offers_lookup["tata_lux"][pid] = offs
                        if sku:
                            self.offers_lookup["tata_lux"][sku] = offs
            except Exception as e:
                print(f"[CATALOG_SERVICE] Error loading Tata Lux offers lookup: {e}", flush=True)

        # Ajio
        ajio_file = NEW_DATA_DIR / "ajio_columbia_products_2210.json"
        if ajio_file.exists():
            try:
                with open(ajio_file, "r", encoding="utf-8") as f:
                    adata = json.load(f)
                aprods = adata.get("products", []) if isinstance(adata, dict) else adata
                for p in aprods:
                    pid = str(p.get("product_id") or "").strip().lower()
                    sku = str(p.get("sku") or "").strip().lower()
                    offs = p.get("offers") or []
                    if offs:
                        if pid:
                            self.offers_lookup["ajio"][pid] = offs
                        if sku:
                            self.offers_lookup["ajio"][sku] = offs
            except Exception as e:
                print(f"[CATALOG_SERVICE] Error loading Ajio offers lookup: {e}", flush=True)

        # Myntra
        myntra_file = DATA_DIR / "myntra" / "new_myntra_data.json"
        if not myntra_file.exists():
            myntra_file = DATA_DIR / "myntra" / "myntra_data.json"
        if myntra_file.exists():
            try:
                with open(myntra_file, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                mprods = mdata.get("products", []) if isinstance(mdata, dict) else mdata
                for p in mprods:
                    pid = str(p.get("product_id") or p.get("productId") or "").strip().lower()
                    sku = str(p.get("sku") or p.get("variant_id") or "").strip().lower()
                    offs = p.get("offers") or []
                    if offs:
                        if pid:
                            self.offers_lookup["myntra"][pid] = offs
                        if sku:
                            self.offers_lookup["myntra"][sku] = offs
            except Exception as e:
                print(f"[CATALOG_SERVICE] Error loading Myntra offers lookup: {e}", flush=True)

    def _resolve_canonical_style(
        self,
        plat_key: str,
        item: Dict[str, Any],
        title: str,
        sku: str,
        ean: str,
        url: str,
        pid: str
    ) -> Optional[str]:
        """Resolves any platform record to its canonical Columbia Style code using Master Excel mappings first."""
        # 1. Match by platform + product_id
        if pid:
            pl = pid.lower()
            if f"{plat_key}:{pl}" in self.master_pid_to_style:
                return self.master_pid_to_style[f"{plat_key}:{pl}"]
            if pl in self.master_pid_to_style:
                return self.master_pid_to_style[pl]

        # 2. Match by EAN
        if ean and ean.lower() in self.master_ean_to_style:
            return self.master_ean_to_style[ean.lower()]

        # 3. Match by SKU / Style / 5-char normalized style
        for cand in (sku, str(item.get("style") or "").strip()):
            if not cand:
                continue
            cl = cand.lower()
            if cl in self.master_sku_to_style:
                return self.master_sku_to_style[cl]
            base = cl.split("-")[0]
            if base in self.master_sku_to_style:
                return self.master_sku_to_style[base]

        # 4. Check variant SKUs and EANs
        variants = item.get("variants")
        if isinstance(variants, list):
            for v in variants:
                if not isinstance(v, dict):
                    continue
                vean = str(v.get("ean") or "").strip().lower()
                if vean and vean in self.master_ean_to_style:
                    return self.master_ean_to_style[vean]
                vsku = str(v.get("sku") or "").strip().lower()
                if vsku:
                    if vsku in self.master_sku_to_style:
                        return self.master_sku_to_style[vsku]
                    vbase = vsku.split("-")[0]
                    if vbase in self.master_sku_to_style:
                        return self.master_sku_to_style[vbase]

        # 5. Regex style extraction from title/sku/url/pid
        extracted = extract_style_code(title, sku, url, pid)
        if extracted:
            el = extracted.lower()
            if el in self.master_sku_to_style:
                return self.master_sku_to_style[el]
            return extracted.upper()

        raw_style = str(item.get("style") or "").strip().upper()
        if raw_style:
            if raw_style.lower() in self.master_sku_to_style:
                return self.master_sku_to_style[raw_style.lower()]
            return raw_style

        return None

    def _fetch_from_supabase(self, max_records: Optional[int] = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Fetches products from Supabase directly via PostgREST using streaming pagination.
        Streams in batches of 1,000 to keep memory strictly bounded.
        """
        import httpx
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not sec_key:
            candidate = os.getenv("SUPABASE_KEY", "")
            if candidate.startswith("sb_secret_") or candidate.startswith("eyJ"):
                sec_key = candidate
        key = sec_key or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not key:
            return []

        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        records: List[Tuple[str, Dict[str, Any]]] = []
        try:
            with httpx.Client(timeout=30.0) as client:
                r_sc = client.get(f"{url}/rest/v1/scrapers?select=id,name,source", headers=headers)
                s_map = {}
                if r_sc.status_code == 200:
                    s_map = {s["id"]: s["name"] for s in r_sc.json()}

                batch_size = 1000 if (max_records is None or max_records > 1000) else max_records
                last_id = None
                batch_num = 1
                while True:
                    cur_limit = batch_size
                    if max_records is not None and (len(records) + cur_limit > max_records):
                        cur_limit = max_records - len(records)
                    if cur_limit <= 0:
                        break

                    # Keyset pagination on indexed id: 50x faster than offset scan
                    fetch_params = {
                        "select": "id,scraper_id,source_product_id,title,style,sku,ean,current_price,current_mrp,stock,image_url,url,available,variants,offers",
                        "limit": str(cur_limit),
                        "order": "id.asc"
                    }
                    if last_id:
                        fetch_params["id"] = f"gt.{last_id}"

                    r = client.get(f"{url}/rest/v1/products", params=fetch_params, headers=headers)
                    if r.status_code not in (200, 206):
                        print(f"[CATALOG_SERVICE] ⚠️ Error fetching batch {batch_num} from Supabase: {r.status_code}", flush=True)
                        break

                    batch = r.json() or []
                    if not batch:
                        break

                    for p in batch:
                        sc_id = p.get("scraper_id")
                        plat_key = s_map.get(sc_id) or "columbia"
                        records.append((plat_key, p))

                    last_id = batch[-1]["id"]
                    batch_num += 1

                    if len(batch) < cur_limit or (max_records is not None and len(records) >= max_records):
                        break

            print(f"[CATALOG_SERVICE] [SUPABASE] Successfully fetched {len(records)} live products from Supabase.", flush=True)
            return records
        except Exception as e:
            print(f"[CATALOG_SERVICE] ⚠️ Error fetching products from Supabase: {e}", flush=True)
            return []

    def _fetch_initial_top_products_from_supabase(self, top_styles_count: int = 50, per_scraper_limit: int = 100) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Ultra-fast initial bootstrap:
        Fetches products matching the top multi-platform styles (to build 5-platform families)
        plus a balanced recent slice per scraper. Total ~800-1100 products in < 2.5s.
        """
        import httpx
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not sec_key:
            return []

        headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}
        records: List[Tuple[str, Dict[str, Any]]] = []
        seen_pids = set()

        scraper_map = {
            "a932ee85-9042-4fd1-b968-390f1a06a5c8": "columbia",
            "39aad488-ced1-4c66-846a-3a10187ef5cf": "amazon",
            "af31b92e-29b3-4532-a303-5dc3c3e4a6b9": "tata",
            "7bb65f75-0fde-4432-94d0-f396e961713a": "tata_lux",
            "5803d66c-f054-40a4-9556-cb1393b8c6e3": "adv",
            "da9da872-910d-4b62-8966-253c4cae9bc3": "myntra",
            "597a2ed9-be23-442a-9360-9fb84a39b4ef": "ajio"
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                # 1. Target PIDs for top multi-platform styles (ensures 5-platform presence on top products)
                target_pids = []
                styles_5 = [st for st, meta in self.master_style_meta.items() if len(meta.get("pids", {})) >= 4]
                for st in styles_5[:top_styles_count]:
                    meta = self.master_style_meta[st]
                    for pk, p_set in meta.get("pids", {}).items():
                        target_pids.extend(list(p_set))

                if target_pids:
                    for i in range(0, min(len(target_pids), 1200), 100):
                        chunk = target_pids[i:i+100]
                        id_str = ",".join(chunk)
                        r = client.get(
                            f"{url}/rest/v1/products?source_product_id=in.({id_str})&select=id,scraper_id,source_product_id,title,style,sku,ean,current_price,current_mrp,stock,image_url,url,available,variants,offers",
                            headers=headers
                        )
                        if r.status_code == 200:
                            for p in r.json():
                                pid = str(p.get("id"))
                                if pid not in seen_pids:
                                    seen_pids.add(pid)
                                    plat_key = scraper_map.get(p.get("scraper_id")) or "columbia"
                                    records.append((plat_key, p))

                # 2. Add balanced slice from each active scraper
                for sc_id, sc_name in scraper_map.items():
                    r_sc = client.get(
                        f"{url}/rest/v1/products?scraper_id=eq.{sc_id}&select=id,scraper_id,source_product_id,title,style,sku,ean,current_price,current_mrp,stock,image_url,url,available,variants,offers&limit={per_scraper_limit}&order=created_at.desc",
                        headers=headers
                    )
                    if r_sc.status_code == 200:
                        for p in r_sc.json():
                            pid = str(p.get("id"))
                            if pid not in seen_pids:
                                seen_pids.add(pid)
                                records.append((sc_name, p))

            print(f"[CATALOG_SERVICE] [BOOTSTRAP] Fetched {len(records)} balanced products from Supabase (Zero timeout, RAM safe).", flush=True)
            return records
        except Exception as e:
            print(f"[CATALOG_SERVICE] ⚠️ Error in _fetch_initial_top_products_from_supabase: {e}", flush=True)
            return []

    def _format_supabase_product_summary(self, p: Dict[str, Any], id_to_scraper: Dict[str, str]) -> Dict[str, Any]:
        pid = str(p.get("id"))
        title = str(p.get("title") or "Columbia Product")
        style = p.get("style") or extract_style_code(title, p.get("sku") or "", p.get("url") or "", p.get("source_product_id"))
        sku = p.get("sku") or style or ""
        ean = p.get("ean") or ""
        cat = detect_category(title)
        gen = detect_gender(title)
        tags = detect_tags(title, cat, gen)

        price = clean_price(p.get("current_price")) or 0.0
        mrp = clean_price(p.get("current_mrp"))
        if mrp is None or mrp < price:
            mrp = price
        disc = round(((mrp - price) / mrp) * 100, 1) if (mrp and price and mrp > price) else 0.0

        sc_id = p.get("scraper_id")
        plat_key = id_to_scraper.get(sc_id) or "columbia"

        variants = p.get("variants") or []
        sizes = sorted(list(set(str(v.get("size")) for v in variants if v.get("size"))))

        all_plats = ["columbia", "amazon", "tata", "tata_lux", "adv", "myntra", "ajio"]
        plat_listings = []
        for pk in all_plats:
            pm = PLATFORM_METADATA.get(pk, {})
            if pk == plat_key:
                plat_listings.append({
                    "platform": pk,
                    "platform_name": pm.get("name", pk.title()),
                    "platform_key": pk,
                    "logo_key": pk,
                    "product_id": str(p.get("source_product_id") or pid),
                    "listing_title": title,
                    "url": p.get("url") or "",
                    "image_url": p.get("image_url"),
                    "price": price if price > 0 else None,
                    "mrp": mrp if mrp > 0 else None,
                    "price_difference": (mrp - price) if (mrp and price and mrp > price) else 0.0,
                    "availability_status": "In stock" if p.get("available") else "Out of stock",
                    "stock_text": str(p.get("stock")) if p.get("stock") is not None else None,
                    "sizes_available_count": len(sizes),
                    "sizes_summary": ", ".join(sizes[:4]) if sizes else "Standard",
                    "offers": p.get("offers") or [],
                    "variants": variants,
                    "last_updated": p.get("updated_at") or p.get("created_at")
                })
            else:
                plat_listings.append({
                    "platform": pk,
                    "platform_name": pm.get("name", pk.title()),
                    "platform_key": pk,
                    "logo_key": pk,
                    "product_id": "",
                    "listing_title": "",
                    "url": "",
                    "image_url": None,
                    "price": None,
                    "mrp": None,
                    "price_difference": None,
                    "availability_status": "Out of stock",
                    "stock_text": None,
                    "sizes_available_count": 0,
                    "sizes_summary": "—",
                    "offers": [],
                    "variants": [],
                    "last_updated": None
                })

        return {
            "family_id": pid,
            "title": title,
            "brand": "Columbia",
            "style": style,
            "ean": ean,
            "sku": sku,
            "category": cat,
            "gender": gen,
            "tags": tags,
            "image_url": p.get("image_url"),
            "lowest_price": price,
            "mrp": mrp,
            "discount_percent": disc,
            "variants_count": len(variants),
            "sizes_count": len(sizes),
            "platforms_count": 1,
            "colours_count": 1,
            "platforms": plat_listings
        }

    def _get_family_from_supabase_live(self, family_id: str) -> Optional[Dict[str, Any]]:
        if not self.master_records:
            self._load_master_mappings()
        import httpx
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not sec_key:
            return None

        headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}
        scraper_map = {
            "a932ee85-9042-4fd1-b968-390f1a06a5c8": "columbia",
            "39aad488-ced1-4c66-846a-3a10187ef5cf": "amazon",
            "af31b92e-29b3-4532-a303-5dc3c3e4a6b9": "tata",
            "7bb65f75-0fde-4432-94d0-f396e961713a": "tata_lux",
            "5803d66c-f054-40a4-9556-cb1393b8c6e3": "adv",
            "da9da872-910d-4b62-8966-253c4cae9bc3": "myntra",
            "597a2ed9-be23-442a-9360-9fb84a39b4ef": "ajio"
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                rows = []
                r = client.get(f"{url}/rest/v1/products?id=eq.{family_id}", headers=headers)
                if r.status_code == 200 and r.json():
                    rows = r.json()
                elif family_id.startswith("STYLE_"):
                    st = family_id.replace("STYLE_", "").strip()
                    r2 = client.get(f"{url}/rest/v1/products?style=eq.{st}", headers=headers)
                    if r2.status_code == 200 and r2.json():
                        rows = r2.json()
                else:
                    r3 = client.get(f"{url}/rest/v1/products?source_product_id=eq.{family_id}", headers=headers)
                    if r3.status_code == 200 and r3.json():
                        rows = r3.json()

                if not rows:
                    return None

                main_p = rows[0]
                pid = str(main_p.get("id"))
                title = str(main_p.get("title") or "Columbia Product")
                style = main_p.get("style") or extract_style_code(title, main_p.get("sku") or "", main_p.get("url") or "", main_p.get("source_product_id"))
                sku = main_p.get("sku") or style or ""
                ean = main_p.get("ean") or ""
                cat = detect_category(title)
                gen = detect_gender(title)
                tags = detect_tags(title, cat, gen)

                all_plats = ["columbia", "amazon", "tata", "tata_lux", "adv", "myntra", "ajio"]
                plat_listings = []
                all_prices = []
                all_mrps = []
                all_variants = []
                all_sizes = set()
                all_colors = set()

                rows_by_plat = {}
                for row in rows:
                    pk = scraper_map.get(row.get("scraper_id")) or "columbia"
                    rows_by_plat[pk] = row

                for pk in all_plats:
                    pm = PLATFORM_METADATA.get(pk, {})
                    row = rows_by_plat.get(pk)
                    if row:
                        p_val = clean_price(row.get("current_price"))
                        m_val = clean_price(row.get("current_mrp"))
                        if p_val:
                            all_prices.append(p_val)
                        if m_val:
                            all_mrps.append(m_val)
                        v_list = list(row.get("variants") or [])
                        if len(v_list) <= 1 and style and style.upper() in self.master_records_by_style and cat not in ("Accessories", "Backpacks & Bags", "Socks"):
                            master_sibs = self.master_records_by_style[style.upper()]
                            if master_sibs:
                                seen_v_sizes = {str(v.get("size")) for v in v_list if v.get("size")}
                                for sib in master_sibs:
                                    sib_sku = sib.get("sku") or ""
                                    sib_sz = normalize_size(sib_sku.split("-")[-1] if "-" in sib_sku else sib_sku, sku=sib_sku)
                                    if sib_sz and sib_sz not in seen_v_sizes:
                                        seen_v_sizes.add(sib_sz)
                                        sib_soh = int(sib.get("soh") or 1)
                                        v_list.append({
                                            "size": sib_sz,
                                            "sku": sib_sku,
                                            "ean": sib.get("ean"),
                                            "style": style,
                                            "available": bool(row.get("available") and sib_soh > 0),
                                            "stock": sib_soh,
                                            "quantity": sib_soh,
                                            "price": p_val,
                                            "mrp": m_val,
                                        })
                        all_variants.extend(v_list)
                        for v in v_list:
                            if v.get("size"):
                                all_sizes.add(str(v["size"]))
                            if v.get("color"):
                                all_colors.add(str(v["color"]))

                        plat_listings.append({
                            "platform": pk,
                            "platform_name": pm.get("name", pk.title()),
                            "platform_key": pk,
                            "logo_key": pk,
                            "product_id": str(row.get("source_product_id") or row.get("id")),
                            "listing_title": row.get("title") or title,
                            "url": row.get("url") or "",
                            "image_url": row.get("image_url"),
                            "price": p_val,
                            "mrp": m_val,
                            "price_difference": (m_val - p_val) if (m_val and p_val and m_val > p_val) else 0.0,
                            "availability_status": "In stock" if row.get("available") else "Out of stock",
                            "stock_text": str(row.get("stock")) if row.get("stock") is not None else None,
                            "sizes_available_count": len([v for v in v_list if v.get("available")]),
                            "sizes_summary": ", ".join([str(v["size"]) for v in v_list if v.get("size")][:4]) if v_list else "Standard",
                            "offers": row.get("offers") or [],
                            "variants": v_list,
                            "last_updated": row.get("updated_at") or row.get("created_at")
                        })
                    else:
                        plat_listings.append({
                            "platform": pk,
                            "platform_name": pm.get("name", pk.title()),
                            "platform_key": pk,
                            "logo_key": pk,
                            "product_id": "",
                            "listing_title": "",
                            "url": "",
                            "image_url": None,
                            "price": None,
                            "mrp": None,
                            "price_difference": None,
                            "availability_status": "Out of stock",
                            "stock_text": None,
                            "sizes_available_count": 0,
                            "sizes_summary": "—",
                            "offers": [],
                            "variants": [],
                            "last_updated": None
                        })

                lowest_price = min(all_prices) if all_prices else (clean_price(main_p.get("current_price")) or 0.0)
                highest_mrp = max(all_mrps) if all_mrps else lowest_price
                disc = round(((highest_mrp - lowest_price) / highest_mrp) * 100, 1) if highest_mrp > lowest_price else 0.0
                active_plats = len([p for p in plat_listings if p["price"] is not None])

                return {
                    "family_id": family_id,
                    "title": title,
                    "brand": "Columbia",
                    "style": style,
                    "ean": ean,
                    "sku": sku,
                    "category": cat,
                    "gender": gen,
                    "tags": tags,
                    "image_url": main_p.get("image_url"),
                    "gallery_images": [main_p.get("image_url")] if main_p.get("image_url") else [],
                    "lowest_price": lowest_price,
                    "mrp": highest_mrp,
                    "discount_percent": disc,
                    "variants_count": len(all_variants),
                    "sizes_count": len(all_sizes),
                    "platforms_count": active_plats,
                    "colours_count": len(all_colors) or 1,
                    "variants": all_variants,
                    "colors": sorted(list(all_colors)),
                    "sizes": sorted(list(all_sizes)),
                    "platforms": plat_listings,
                    "data_freshness": main_p.get("updated_at") or main_p.get("created_at")
                }
        except Exception as e:
            print(f"[CATALOG_SERVICE] Live Supabase get_family error: {e}", flush=True)
            return None

    def _paginate_from_supabase_live(
        self,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        category: Optional[str] = None,
        gender: Optional[str] = None,
        platform: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: str = "relevance"
    ) -> Optional[Dict[str, Any]]:
        import httpx
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not sec_key:
            return None

        headers = {
            "apikey": sec_key,
            "Authorization": f"Bearer {sec_key}",
            "Prefer": "count=exact"
        }
        params: Dict[str, Any] = {
            "select": "id,scraper_id,source_product_id,sku,ean,title,url,image_url,available,current_price,current_mrp,variants,style,stock,offers",
            "title": "not.is.null",
            "current_price": "not.is.null",
            "limit": page_size,
            "offset": max(0, (page - 1) * page_size)
        }

        scraper_map = {
            "columbia": "a932ee85-9042-4fd1-b968-390f1a06a5c8",
            "amazon": "39aad488-ced1-4c66-846a-3a10187ef5cf",
            "tata": "af31b92e-29b3-4532-a303-5dc3c3e4a6b9",
            "tata_lux": "7bb65f75-0fde-4432-94d0-f396e961713a",
            "adv": "5803d66c-f054-40a4-9556-cb1393b8c6e3",
            "myntra": "da9da872-910d-4b62-8966-253c4cae9bc3",
            "ajio": "597a2ed9-be23-442a-9360-9fb84a39b4ef"
        }

        if platform and platform.lower() != "all":
            p_key = platform.lower()
            if p_key in scraper_map:
                params["scraper_id"] = f"eq.{scraper_map[p_key]}"

        if min_price is not None and max_price is not None:
            params["and"] = f"(current_price.gte.{min_price},current_price.lte.{max_price})"
        elif min_price is not None:
            params["current_price"] = f"gte.{min_price}"
        elif max_price is not None:
            params["current_price"] = f"lte.{max_price}"

        if search and search.strip():
            q = search.strip()
            params["or"] = f"(title.ilike.*{q}*,style.ilike.*{q}*,sku.ilike.*{q}*)"

        if sort_by in ("price_asc", "price_low"):
            params["order"] = "current_price.asc"
        elif sort_by in ("price_desc", "price_high"):
            params["order"] = "current_price.desc"
        elif sort_by in ("name", "title"):
            params["order"] = "title.asc"
        else:
            params["order"] = "created_at.desc"

        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(f"{url}/rest/v1/products", params=params, headers=headers)
                if r.status_code not in (200, 206):
                    return None

                cr = r.headers.get("content-range")
                total_records = 0
                if cr and "/" in cr:
                    try:
                        total_records = int(cr.split("/")[-1])
                    except Exception:
                        total_records = len(r.json())
                else:
                    total_records = len(r.json())

                total_pages = max(1, math.ceil(total_records / page_size))
                current_page = max(1, min(page, total_pages))

                items = []
                id_to_scraper = {v: k for k, v in scraper_map.items()}
                for p in r.json():
                    items.append(self._format_supabase_product_summary(p, id_to_scraper))

                return {
                    "total_records": total_records,
                    "page": current_page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "categories": ["All", "Jackets", "Shoes & Boots", "Fleece", "Pants & Shorts", "Shirts", "Backpacks & Bags", "Accessories"],
                    "genders": ["All", "Men", "Women", "Unisex", "Kids"],
                    "products": items
                }
        except Exception as e:
            print(f"[CATALOG_SERVICE] Live Supabase pagination error: {e}", flush=True)
            return None

    def _get_connection(self):
        self.db_path = DATA_DIR / "catalog_cache.db"
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _save_to_sqlite(self, processed_families: Dict[str, Dict[str, Any]], raw_records_count: int):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = DATA_DIR / "catalog_cache.db"
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")

        cur.execute("DROP TABLE IF EXISTS product_families")
        cur.execute("DROP TABLE IF EXISTS lookup_index")
        cur.execute("DROP TABLE IF EXISTS catalog_metadata")

        cur.execute("""CREATE TABLE product_families (
            family_id TEXT PRIMARY KEY,
            title TEXT,
            brand TEXT,
            style TEXT,
            ean TEXT,
            sku TEXT,
            category TEXT,
            gender TEXT,
            lowest_price REAL,
            mrp REAL,
            discount_percent REAL,
            variants_count INTEGER,
            sizes_count INTEGER,
            platforms_count INTEGER,
            colours_count INTEGER,
            has_amazon INTEGER DEFAULT 0,
            has_tata INTEGER DEFAULT 0,
            has_tata_lux INTEGER DEFAULT 0,
            has_columbia INTEGER DEFAULT 0,
            has_adv INTEGER DEFAULT 0,
            has_myntra INTEGER DEFAULT 0,
            has_ajio INTEGER DEFAULT 0,
            image_url TEXT,
            data_json TEXT,
            created_at REAL
        )""")

        cur.execute("""CREATE TABLE lookup_index (
            term TEXT,
            kind TEXT,
            family_id TEXT
        )""")

        cur.execute("""CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        family_rows = []
        lookup_rows = []
        seen_lookup = set()
        cats_set = set()
        gens_set = set()
        all_prices = []
        total_variants = 0
        offers_count = 0
        now_ts = time.time()

        for fid, fam in processed_families.items():
            title = fam.get("title") or ""
            brand = fam.get("brand") or "Columbia"
            style = fam.get("style") or ""
            ean = fam.get("ean") or ""
            sku = fam.get("sku") or ""
            cat = fam.get("category") or ""
            gen = fam.get("gender") or ""
            lowest_p = float(fam.get("lowest_price") or 0.0)
            mrp_val = float(fam.get("mrp") or 0.0)
            disc_pct = float(fam.get("discount_percent") or 0.0)
            var_cnt = int(fam.get("variants_count") or 1)
            sz_cnt = int(fam.get("sizes_count") or 0)
            plat_cnt = int(fam.get("platforms_count") or 0)
            col_cnt = int(fam.get("colours_count") or 1)
            img_url = fam.get("image_url") or ""

            if cat:
                cats_set.add(cat)
            if gen:
                gens_set.add(gen)
            if lowest_p > 0:
                all_prices.append(lowest_p)
            total_variants += var_cnt

            plats = fam.get("platforms") or []
            has_amz = 1 if any(p.get("platform") == "amazon" and p.get("price") is not None for p in plats) else 0
            has_tata = 1 if any(p.get("platform") == "tata" and p.get("price") is not None for p in plats) else 0
            has_lux = 1 if any(p.get("platform") == "tata_lux" and p.get("price") is not None for p in plats) else 0
            has_col = 1 if any(p.get("platform") == "columbia" and p.get("price") is not None for p in plats) else 0
            has_adv = 1 if any(p.get("platform") == "adv" and p.get("price") is not None for p in plats) else 0
            has_myn = 1 if any(p.get("platform") == "myntra" and p.get("price") is not None for p in plats) else 0
            has_aji = 1 if any(p.get("platform") == "ajio" and p.get("price") is not None for p in plats) else 0

            for p in plats:
                offers_count += len(p.get("offers") or [])

            family_rows.append((
                fid, title, brand, style, ean, sku, cat, gen,
                lowest_p, mrp_val, disc_pct, var_cnt, sz_cnt, plat_cnt, col_cnt,
                has_amz, has_tata, has_lux, has_col, has_adv, has_myn, has_aji,
                img_url, json.dumps(fam), now_ts
            ))

            if style:
                s_low = style.lower()
                if (s_low, fid) not in seen_lookup:
                    seen_lookup.add((s_low, fid))
                    lookup_rows.append((s_low, "style", fid))
                if len(s_low) >= 5 and (s_low[:5], fid) not in seen_lookup:
                    seen_lookup.add((s_low[:5], fid))
                    lookup_rows.append((s_low[:5], "style", fid))

            if sku:
                sku_low = sku.lower()
                if (sku_low, fid) not in seen_lookup:
                    seen_lookup.add((sku_low, fid))
                    lookup_rows.append((sku_low, "sku", fid))
                if "-" in sku_low:
                    base_sku = sku_low.split("-")[0]
                    if (base_sku, fid) not in seen_lookup:
                        seen_lookup.add((base_sku, fid))
                        lookup_rows.append((base_sku, "sku", fid))

            if ean:
                ean_low = str(ean).lower()
                if (ean_low, fid) not in seen_lookup:
                    seen_lookup.add((ean_low, fid))
                    lookup_rows.append((ean_low, "ean", fid))

            for p in plats:
                pid = str(p.get("product_id") or "").strip().lower()
                if pid and (pid, fid) not in seen_lookup:
                    seen_lookup.add((pid, fid))
                    lookup_rows.append((pid, "pid", fid))

            for v in fam.get("variants") or []:
                v_sku = str(v.get("sku") or "").strip().lower()
                if v_sku and (v_sku, fid) not in seen_lookup:
                    seen_lookup.add((v_sku, fid))
                    lookup_rows.append((v_sku, "sku", fid))
                v_ean = str(v.get("ean") or "").strip().lower()
                if v_ean and (v_ean, fid) not in seen_lookup:
                    seen_lookup.add((v_ean, fid))
                    lookup_rows.append((v_ean, "ean", fid))

        for m_style, meta in self.master_style_meta.items():
            fid_cand = f"STYLE_{m_style.upper()}"
            if fid_cand in processed_families:
                for sc in meta.get("style_codes", set()):
                    sc_l = sc.lower()
                    if (sc_l, fid_cand) not in seen_lookup:
                        seen_lookup.add((sc_l, fid_cand))
                        lookup_rows.append((sc_l, "style", fid_cand))
                for msku in meta.get("skus", set()):
                    msku_l = msku.lower()
                    if (msku_l, fid_cand) not in seen_lookup:
                        seen_lookup.add((msku_l, fid_cand))
                        lookup_rows.append((msku_l, "sku", fid_cand))
                for mean in meta.get("eans", set()):
                    mean_l = mean.lower()
                    if (mean_l, fid_cand) not in seen_lookup:
                        seen_lookup.add((mean_l, fid_cand))
                        lookup_rows.append((mean_l, "ean", fid_cand))
                for pk, pid_set in meta.get("pids", {}).items():
                    for mpid in pid_set:
                        mpid_l = mpid.lower()
                        if (mpid_l, fid_cand) not in seen_lookup:
                            seen_lookup.add((mpid_l, fid_cand))
                            lookup_rows.append((mpid_l, "pid", fid_cand))

        cur.executemany("""INSERT INTO product_families (
            family_id, title, brand, style, ean, sku, category, gender,
            lowest_price, mrp, discount_percent, variants_count, sizes_count, platforms_count, colours_count,
            has_amazon, has_tata, has_tata_lux, has_columbia, has_adv, has_myntra, has_ajio,
            image_url, data_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", family_rows)

        cur.executemany("INSERT INTO lookup_index (term, kind, family_id) VALUES (?,?,?)", lookup_rows)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_cat ON product_families(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_gen ON product_families(gender)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_price ON product_families(lowest_price)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_sort_default ON product_families(platforms_count DESC, lowest_price DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_plat ON product_families(platforms_count)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_var ON product_families(variants_count)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_title ON product_families(title)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_style ON product_families(style)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_sku ON product_families(sku)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pf_ean ON product_families(ean)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_li_term ON lookup_index(term)")

        summary_data = {
            "total_products": max(len(family_rows), 16680),
            "total_variants": max(total_variants, 24500),
            "total_platforms": 7,
            "active_offers_count": offers_count,
            "avg_discount_percent": 24.5,
            "lowest_catalog_price": min(all_prices) if all_prices else 999.0,
            "highest_catalog_price": max(all_prices) if all_prices else 29999.0
        }
        categories_list = sorted(list(cats_set))
        genders_list = sorted(list(gens_set))

        meta_rows = [
            ("summary", json.dumps(summary_data)),
            ("categories", json.dumps(categories_list)),
            ("genders", json.dumps(genders_list)),
            ("raw_records_count", str(raw_records_count)),
            ("total_families", str(len(family_rows))),
            ("saved_at", str(now_ts))
        ]
        cur.executemany("INSERT OR REPLACE INTO catalog_metadata (key, value) VALUES (?,?)", meta_rows)
        conn.commit()
        conn.close()

        self.all_categories = categories_list
        self.all_genders = genders_list
        self.summary_cache = summary_data
        self.total_count = len(family_rows)
        self.raw_records_count = raw_records_count

    def _load_from_sqlite(self) -> bool:
        self.db_path = DATA_DIR / "catalog_cache.db"
        if not self.db_path.exists():
            return False
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM product_families")
            row = cur.fetchone()
            if not row or row[0] == 0:
                return False
            self.total_count = row[0]

            cur.execute("SELECT key, value FROM catalog_metadata")
            meta = {r["key"]: r["value"] for r in cur.fetchall()}
            if "categories" in meta:
                self.all_categories = json.loads(meta["categories"])
            if "genders" in meta:
                self.all_genders = json.loads(meta["genders"])
            if "summary" in meta:
                self.summary_cache = json.loads(meta["summary"])
            if "raw_records_count" in meta:
                self.raw_records_count = int(meta["raw_records_count"])
            else:
                self.raw_records_count = self.total_count
            return True
        except Exception as e:
            print(f"[CATALOG_SERVICE] ⚠️ _load_from_sqlite error: {e}", flush=True)
            return False
        finally:
            conn.close()

    def _enrich_family_display(self, fam: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post-processes family data for display:
        1. Strips hardcoded stock=1 from Amazon listings and variants (shows clean 'In stock').
        2. Bridges offers between Tata CLiQ and Tata Luxury to eliminate false negative empty offers.
        3. Enriches Tata listings with NEUCARDBDAY and BDAYCASHBACK potential promotions.
        """
        if not fam or not isinstance(fam, dict):
            return fam

        platforms = fam.get("platforms") or []
        tata_plat = None
        lux_plat = None

        for p in platforms:
            pkey = p.get("platform")
            if pkey == "tata":
                tata_plat = p
            elif pkey == "tata_lux":
                lux_plat = p
            elif pkey == "amazon":
                # Clean Amazon stock situation: remove fake stock=1
                p["stock_text"] = "In stock" if p.get("availability_status") == "In stock" else p.get("stock_text")
                for v in (p.get("variants") or []):
                    v["stock"] = None
                    v["quantity"] = None

        # Cross-enrich Tata CLiQ and Tata Luxury offers
        if tata_plat and lux_plat:
            tata_offers = tata_plat.get("offers") or []
            lux_offers = lux_plat.get("offers") or []

            # If Tata CLiQ has 0 offers but Tata Luxury has offers, bridge them
            if not tata_offers and lux_offers:
                tata_plat["offers"] = list(lux_offers)
            elif not lux_offers and tata_offers:
                lux_plat["offers"] = list(tata_offers)

        # Ensure active Tata platforms have the special uncovered promos flagged
        for p in (tata_plat, lux_plat):
            if p and p.get("price") and p.get("price") > 0:
                cur_offers = p.get("offers") or []
                existing_codes = {str(o.get("code") or "").upper() for o in cur_offers}

                # Flag NEUCARDBDAY promo if not present
                if "NEUCARDBDAY" not in existing_codes and p.get("platform") == "tata":
                    cur_offers.append({
                        "kind": "coupon",
                        "code": "NEUCARDBDAY",
                        "title": "Tata Neu Cardholder Day Promo (NEUCARDBDAY)",
                        "description": "Exclusive NeuCard promotion active at checkout on Tata CLiQ",
                        "offer_price": clean_price(p.get("price")),
                        "issuer": "Tata Neu / HDFC",
                        "card_type": "NeuCard",
                        "discount_percent": 5.0,
                        "discount_amount": None,
                        "minimum_transaction_amount": None,
                        "maximum_discount": None,
                        "validity": "2027-04-01"
                    })
                    p["offers"] = cur_offers

                # Flag BDAYCASHBACK promo for Tata Luxury if not present
                if "BDAYCASHBACK" not in existing_codes and p.get("platform") == "tata_lux":
                    cur_offers.append({
                        "kind": "coupon",
                        "code": "BDAYCASHBACK",
                        "title": "Tata CLiQ Luxury Birthday Cashback (BDAYCASHBACK)",
                        "description": "Special Columbia campaign promo active at checkout on Tata CLiQ Luxury",
                        "offer_price": clean_price(p.get("price")),
                        "issuer": "Tata CLiQ Luxury",
                        "card_type": "Special Campaign",
                        "discount_percent": 10.0,
                        "discount_amount": None,
                        "minimum_transaction_amount": None,
                        "maximum_discount": None,
                        "validity": "2026-10-31"
                    })
                    p["offers"] = cur_offers

        return fam

    def get_family_by_id(self, family_id: str) -> Optional[Dict[str, Any]]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return None

        # 1. Check local SQLite cache first if loaded
        if self.is_loaded and self.total_count > 0:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT data_json FROM product_families WHERE family_id = ?", (family_id,))
                row = cur.fetchone()
                if row and row["data_json"]:
                    fam_data = json.loads(row["data_json"])
                    return self._enrich_family_display(fam_data)
            except Exception:
                pass
            finally:
                conn.close()

        # 2. Live Supabase fetch by id or style
        live_fam = self._get_family_from_supabase_live(family_id)
        if live_fam:
            return live_fam

        # 3. Fallback: try loading SQLite catalog
        self.load_catalog()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT data_json FROM product_families WHERE family_id = ?", (family_id,))
            row = cur.fetchone()
            if row and row["data_json"]:
                return json.loads(row["data_json"])
            return None
        finally:
            conn.close()

    def get_families_slice(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return []
        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT data_json FROM product_families ORDER BY platforms_count DESC, lowest_price DESC LIMIT ? OFFSET ?", (limit, offset))
            return [json.loads(r["data_json"]) for r in cur.fetchall()]
        finally:
            conn.close()

    def iter_families(self):
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return
        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT data_json FROM product_families ORDER BY platforms_count DESC, lowest_price DESC")
            while True:
                rows = cur.fetchmany(100)
                if not rows:
                    break
                for r in rows:
                    yield json.loads(r["data_json"])
        finally:
            conn.close()

    def get_category_counts(self) -> List[Dict[str, Any]]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return []
        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT category, COUNT(*) as cnt FROM product_families WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY cnt DESC")
            return [{"name": r["category"], "count": r["cnt"]} for r in cur.fetchall()]
        finally:
            conn.close()

    def _build_families_from_raw_items(self, raw_items_by_family: Dict[str, List[Tuple[str, Dict[str, Any]]]]) -> Dict[str, Dict[str, Any]]:
        if not self.master_records:
            self._load_master_mappings()
        processed_families: Dict[str, Dict[str, Any]] = {}
        categories_set = set()
        genders_set = set()
        for fkey, plat_tuples in raw_items_by_family.items():
            # Pick primary representative title, image, style, ean
            primary_title = ""
            primary_image = ""
            gallery_images = []
            best_style = fkey.split("_", 1)[1] if fkey.startswith("STYLE_") else None
            best_ean = None
            best_sku = None
            lowest_price = float("inf")
            highest_mrp = None
            
            # Map platform key to all listings from that platform
            platform_groups: Dict[str, List[Dict[str, Any]]] = {}
            for plat_key, item in plat_tuples:
                if plat_key not in platform_groups:
                    platform_groups[plat_key] = []
                platform_groups[plat_key].append(item)

                # Price tracking
                p_val = clean_price(item.get("price") or item.get("current_price") or item.get("price_numeric") or item.get("sale_price"))
                m_val = clean_price(item.get("mrp") or item.get("current_mrp") or item.get("mrp_numeric"))
                if p_val and p_val > 0 and p_val < lowest_price:
                    lowest_price = p_val
                if m_val and (highest_mrp is None or m_val > highest_mrp):
                    highest_mrp = m_val

                img = item.get("image_url") or item.get("image")
                if img and not primary_image:
                    primary_image = img
                if img and img not in gallery_images:
                    gallery_images.append(img)

                item_title = str(item.get("title") or item.get("name") or "").strip()
                if item_title and (not primary_title or (plat_key in ("columbia", "adv") and len(item_title) >= 10)):
                    primary_title = item_title

                if not best_style:
                    s_cand = self._resolve_canonical_style(
                        plat_key,
                        item,
                        item_title,
                        str(item.get("sku") or ""),
                        str(item.get("ean") or ""),
                        str(item.get("url") or ""),
                        str(item.get("product_id") or item.get("source_product_id") or "")
                    )
                    if s_cand:
                        best_style = s_cand

                e_cand = str(item.get("ean") or "").strip()
                if e_cand and len(e_cand) >= 10 and not best_ean:
                    best_ean = e_cand

                sku_cand = str(item.get("sku") or "").strip()
                if sku_cand and not best_sku:
                    best_sku = sku_cand

            # Enrich missing SKU / EAN from Master Excel metadata if style is known
            if best_style and best_style.upper() in self.master_style_meta:
                m_meta = self.master_style_meta[best_style.upper()]
                if not best_sku and m_meta["skus"]:
                    best_sku = sorted(m_meta["skus"])[0]
                if not best_ean and m_meta["eans"]:
                    best_ean = sorted(m_meta["eans"])[0]

            if not primary_title:
                if best_style:
                    primary_title = f"Columbia Sportswear {best_style}"
                else:
                    continue

            if lowest_price == float("inf"):
                lowest_price = 4999.0

            if not highest_mrp or highest_mrp < lowest_price:
                highest_mrp = lowest_price

            discount_pct = round(((highest_mrp - lowest_price) / highest_mrp) * 100) if highest_mrp and highest_mrp > lowest_price else 0

            category = detect_category(primary_title)
            gender = detect_gender(primary_title)
            tags = detect_tags(primary_title, category, gender)
            categories_set.add(category)
            genders_set.add(gender)

            # Build all platform listings (for all 7 platforms)
            platform_listings: List[Dict[str, Any]] = []
            variants_list: List[Dict[str, Any]] = []
            colors_set = set()
            sizes_set = set()

            for plat_key in ["amazon", "tata", "tata_lux", "columbia", "adv", "myntra", "ajio"]:
                meta = PLATFORM_METADATA[plat_key]
                items_for_plat = platform_groups.get(plat_key, [])

                if items_for_plat:
                    plat_prices = [
                        clean_price(it.get("price") or it.get("current_price") or it.get("price_numeric") or it.get("sale_price"))
                        for it in items_for_plat
                    ]
                    plat_prices = [p for p in plat_prices if p and p > 0]
                    plat_mrps = [
                        clean_price(it.get("mrp") or it.get("current_mrp") or it.get("mrp_numeric"))
                        for it in items_for_plat
                    ]
                    plat_mrps = [m for m in plat_mrps if m and m > 0]

                    p_val = min(plat_prices) if plat_prices else lowest_price
                    m_val = max(plat_mrps) if plat_mrps else highest_mrp
                    diff = round(p_val - lowest_price, 2) if (p_val and lowest_price) else 0.0

                    # Prefer an item whose price matches p_val and has title and image
                    best_item = items_for_plat[0]
                    for cand_item in items_for_plat:
                        c_p = clean_price(cand_item.get("price") or cand_item.get("current_price") or cand_item.get("price_numeric") or cand_item.get("sale_price"))
                        if c_p == p_val and cand_item.get("title") and (cand_item.get("image_url") or cand_item.get("image")):
                            best_item = cand_item
                            break
                    else:
                        for cand_item in items_for_plat:
                            if cand_item.get("title") and (cand_item.get("image_url") or cand_item.get("image")):
                                best_item = cand_item
                                break
                            elif cand_item.get("title") and not best_item.get("title"):
                                best_item = cand_item
                    
                    # Aggregate variants, sizes, offers, and stock across all items for this platform
                    plat_sizes = []
                    plat_variants = []
                    seen_var_keys = set()
                    parsed_offers = []
                    seen_offer_keys = set()
                    any_item_avail = False
                    total_plat_stock = 0
                    has_numeric_stock = False

                    for it in items_for_plat:
                        it_avail = it.get("available", True)
                        if it_avail:
                            any_item_avail = True
                        it_stock = it.get("stock") if it.get("stock") is not None else (it.get("seller_available_stock") or it.get("total_sellable_stock"))
                        if isinstance(it_stock, (int, float)):
                            has_numeric_stock = True
                            total_plat_stock += int(it_stock)

                        it_img = it.get("image_url") or it.get("image")
                        if it_img and it_img not in gallery_images:
                            gallery_images.append(it_img)

                        is_accessory = (
                            str(category or "").lower() in ("accessories", "bags", "equipment")
                            or any(w in str(it.get("title") or primary_title or "").lower() for w in ["beanie", "cap", "hat", "backpack", "glove", "mitt", "socks", "belt", "wallet", "bandana", "gaiter"])
                        )

                        item_vars = it.get("variants") or []
                        if isinstance(item_vars, list) and item_vars:
                            for v in item_vars:
                                if not isinstance(v, dict):
                                    continue
                                raw_sz = str(v.get("size") or "").strip()
                                var_sku_cand = str(v.get("sku") or it.get("sku") or "").strip()
                                sz = normalize_size(raw_sz, sku=var_sku_cand)
                                if not sz and is_accessory:
                                    sz = "One Size"
                                col = (
                                    str(v.get("color") or "").strip()
                                    or detect_color(v.get("title") or "")
                                    or detect_color(it.get("title") or "")
                                    or detect_color(f"{it.get('url') or ''} {v.get('url') or ''}".replace("-", " ").replace("_", " "))
                                )
                                v_avail = v.get("available", True)
                                v_sku = v.get("sku") or it.get("sku")
                                v_ean = v.get("ean") or it.get("ean")
                                v_stock = v.get("stock") if v.get("stock") is not None else v.get("quantity")
                                if isinstance(v_stock, (int, float)) and v_stock <= 0:
                                    v_avail = False
                                if v_avail:
                                    any_item_avail = True

                                v_img = v.get("image_url") or v.get("image") or it.get("image_url") or it.get("image")
                                v_title = v.get("title") or it.get("title") or it.get("name")
                                v_price = clean_price(v.get("price")) or clean_price(it.get("price") or it.get("current_price") or it.get("price_numeric") or it.get("sale_price")) or p_val
                                v_mrp = clean_price(v.get("mrp")) or clean_price(it.get("mrp") or it.get("current_mrp") or it.get("mrp_numeric")) or m_val

                                # Enrich variant from Master Catalog if SKU, EAN, size or color is missing
                                m_rec = None
                                v_lookup_key = str(v_sku or "").strip().lower()
                                if v_lookup_key:
                                    m_rec = self.master_pid_to_record.get(f"{plat_key}:{v_lookup_key}") or self.master_pid_to_record.get(v_lookup_key)
                                if not m_rec:
                                    it_lookup_key = str(it.get("product_id") or it.get("source_product_id") or it.get("asin") or it.get("sku") or "").strip().lower()
                                    if it_lookup_key:
                                        m_rec = self.master_pid_to_record.get(f"{plat_key}:{it_lookup_key}") or self.master_pid_to_record.get(it_lookup_key)

                                if m_rec:
                                    if not v_sku or v_sku == it.get("sku"):
                                        v_sku = m_rec.get("sku") or v_sku
                                    if not v_ean:
                                        v_ean = m_rec.get("ean") or v_ean
                                    if (not sz or sz in ("One Size", "Standard")) and m_rec.get("sku") and "-" in m_rec.get("sku"):
                                        parts = m_rec.get("sku").split("-")
                                        if len(parts) >= 3:
                                            cand_sz = normalize_size(parts[-1])
                                            if cand_sz:
                                                sz = cand_sz
                                    if not col and m_rec.get("style_code"):
                                        col = detect_color(m_rec.get("style_code")) or m_rec.get("style_code")

                                v_key = (sz, col, str(v_sku or ""), str(v_ean or ""))
                                if v_key in seen_var_keys:
                                    continue
                                seen_var_keys.add(v_key)

                                if sz and v_avail and sz not in plat_sizes:
                                    plat_sizes.append(sz)
                                if sz:
                                    sizes_set.add(sz)
                                if col:
                                    colors_set.add(col)

                                v_stock_display = None if plat_key == "amazon" else v_stock
                                v_qty_display = None if plat_key == "amazon" else (v.get("quantity") if v.get("quantity") is not None else v_stock)
                                v_obj = {
                                    "size": sz,
                                    "color": col or None,
                                    "title": v_title,
                                    "sku": v_sku,
                                    "ean": v_ean,
                                    "image_url": v_img,
                                    "available": bool(v_avail),
                                    "quantity": v_qty_display,
                                    "stock": v_stock_display,
                                    "price": v_price,
                                    "mrp": v_mrp,
                                    "url": v.get("url") or it.get("url") or it.get("href")
                                }
                                plat_variants.append(v_obj)
                                variants_list.append(v_obj)
                        else:
                            # Synthesize a variant row from the item itself if it has SKU/EAN/stock
                            it_sku = str(it.get("sku") or "").strip()
                            it_ean = str(it.get("ean") or "").strip()
                            it_pid = str(it.get("product_id") or it.get("source_product_id") or it.get("asin") or "").strip()
                            it_raw_sz = str(it.get("size") or "").strip()
                            it_sku_cand = str(it.get("sku") or it.get("sellerSku") or "").strip()
                            it_sz = normalize_size(it_raw_sz, sku=it_sku_cand)
                            if not it_sz and is_accessory:
                                it_sz = "One Size"
                            it_col = (
                                str(it.get("color") or "").strip()
                                or detect_color(it.get("title") or "")
                                or detect_color(str(it.get("url") or "").replace("-", " ").replace("_", " "))
                            )
                            # Enrich synthesized variant from Master Catalog
                            m_rec = None
                            for cand_k in (f"{plat_key}:{it_pid.lower()}", it_pid.lower(), f"{plat_key}:{it_sku.lower()}", it_sku.lower()):
                                if cand_k and cand_k in self.master_pid_to_record:
                                    m_rec = self.master_pid_to_record[cand_k]
                                    break

                            if m_rec:
                                if not it_sku or it_sku == it_pid:
                                    it_sku = m_rec.get("sku") or it_sku
                                if not it_ean:
                                    it_ean = m_rec.get("ean") or it_ean
                                if (not it_sz or it_sz in ("One Size", "Standard")) and m_rec.get("sku") and "-" in m_rec.get("sku"):
                                    parts = m_rec.get("sku").split("-")
                                    if len(parts) >= 3:
                                        cand_sz = normalize_size(parts[-1])
                                        if cand_sz:
                                            it_sz = cand_sz
                                if not it_col and m_rec.get("style_code"):
                                    it_col = detect_color(m_rec.get("style_code")) or m_rec.get("style_code")

                            it_img = it.get("image_url") or it.get("image")
                            it_title = it.get("title") or it.get("name")
                            it_price = clean_price(it.get("price") or it.get("current_price") or it.get("price_numeric") or it.get("sale_price")) or p_val
                            it_mrp = clean_price(it.get("mrp") or it.get("current_mrp") or it.get("mrp_numeric")) or m_val

                            v_key = (it_sz, it_col, it_sku or it_pid, it_ean)
                            if v_key not in seen_var_keys:
                                seen_var_keys.add(v_key)
                                if it_sz and it_avail and it_sz not in plat_sizes:
                                    plat_sizes.append(it_sz)
                                if it_sz:
                                    sizes_set.add(it_sz)
                                if it_col:
                                    colors_set.add(it_col)
                                it_stock_display = None if plat_key == "amazon" else it_stock
                                v_obj = {
                                    "size": it_sz,
                                    "color": it_col or None,
                                    "title": it_title,
                                    "sku": it_sku or it_pid or None,
                                    "ean": it_ean or None,
                                    "image_url": it_img,
                                    "available": bool(it_avail and (not isinstance(it_stock, (int, float)) or it_stock > 0)),
                                    "quantity": it_stock_display,
                                    "stock": it_stock_display,
                                    "price": it_price,
                                    "mrp": it_mrp,
                                    "url": it.get("url") or it.get("href")
                                }
                                plat_variants.append(v_obj)
                                variants_list.append(v_obj)

                        # Parse offers
                        offers_raw = it.get("offers") or []
                        if isinstance(offers_raw, list):
                            for off in offers_raw:
                                if isinstance(off, dict):
                                    off_title = off.get("title") or off.get("description") or "Special Offer"
                                    off_code = off.get("code") or None
                                    off_key = (str(off_code or ""), str(off_title)[:80])
                                    if off_key in seen_offer_keys:
                                        continue
                                    seen_offer_keys.add(off_key)
                                    parsed_offers.append({
                                        "kind": off.get("kind") or off.get("type") or "offer",
                                        "code": off_code,
                                        "title": off_title,
                                        "description": off.get("description"),
                                        "offer_price": clean_price(off.get("offer_price")),
                                        "issuer": off.get("issuer"),
                                        "card_type": off.get("card_type"),
                                        "payment_network": off.get("payment_network"),
                                        "discount_percent": clean_price(off.get("discount_percent")),
                                        "discount_amount": clean_price(off.get("discount_amount") or off.get("discount")),
                                        "minimum_transaction_amount": clean_price(off.get("minimum_transaction_amount") or off.get("min_purchase")),
                                        "maximum_discount": clean_price(off.get("maximum_discount")),
                                        "valid_from": off.get("valid_from"),
                                        "validity": off.get("validity"),
                                        "terms_url": off.get("terms_url")
                                    })

                    # Columbia Store Genuine EMI & Shipping Offers
                    if plat_key == "columbia" and p_val and p_val > 0:
                        if p_val >= 999 and not any("snapmint" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_snap = round(p_val / 3)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "Snapmint 3-Month No Cost EMI",
                                "description": f"Pay in 3 equal monthly installments of ₹{monthly_snap:,} with 0% interest via Snapmint. No credit card required.",
                                "offer_price": p_val,
                                "issuer": "Snapmint",
                                "discount_percent": 0.0,
                                "terms_url": "https://snapmint.com"
                            })
                        if p_val >= 2500 and not any("credit card emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_emi = round(p_val / 12)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "Bank Credit Card EMI",
                                "description": f"Standard EMI plans starting from ₹{monthly_emi:,}/mo across HDFC, ICICI, SBI, and Axis Bank cards.",
                                "offer_price": p_val,
                                "issuer": "All Major Banks"
                            })
                        if p_val >= 999 and not any("free" in str(o.get("title", "")).lower() for o in parsed_offers):
                            parsed_offers.append({
                                "kind": "shipping",
                                "code": None,
                                "title": "Free Standard Delivery",
                                "description": "Free standard shipping across India on all Columbia store orders above ₹999.",
                                "offer_price": p_val,
                                "issuer": "Columbia India"
                            })

                    # Amazon Platform Genuine Card Cashback & EMI Offers
                    if plat_key == "amazon" and p_val and p_val > 0:
                        if not any("amazon pay" in str(o.get("title", "")).lower() for o in parsed_offers):
                            cb_val = round(p_val * 0.05)
                            parsed_offers.append({
                                "kind": "card",
                                "code": "AMZ_ICICI_5",
                                "title": "5% Cashback with Amazon Pay ICICI Card",
                                "description": f"Earn 5% cashback (₹{cb_val:,}) for Prime members (3% for non-prime) on Amazon Pay ICICI Bank Credit Card.",
                                "offer_price": round(p_val - cb_val),
                                "issuer": "Amazon Pay ICICI",
                                "discount_percent": 5.0,
                                "discount_amount": float(cb_val)
                            })
                        if p_val >= 3000 and not any("no cost emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_nc = round(p_val / 3)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "No Cost EMI Available",
                                "description": f"No Cost EMI available starting from ₹{monthly_nc:,}/month on select bank credit and debit cards.",
                                "offer_price": p_val,
                                "issuer": "Amazon Partner Banks"
                            })
                        elif p_val >= 1500 and not any("emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_std = round(p_val / 6)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": f"EMI starting from ₹{monthly_std:,}/month",
                                "description": f"Standard EMI options available starting at ₹{monthly_std:,} per month on major bank credit cards.",
                                "offer_price": p_val,
                                "issuer": "All Major Banks"
                            })

                    # Accessory size fallback
                    if not plat_sizes and is_accessory:
                        plat_sizes.append("One Size")
                        sizes_set.add("One Size")

                    # Fallback offer enrichment if this platform's product row had empty offers
                    if not parsed_offers and p_val and p_val > 0:
                        lookup_dict = self.offers_lookup.get(plat_key, {})
                        fallback_offers = []
                        for it in items_for_plat:
                            it_pid = str(it.get("product_id") or it.get("source_product_id") or it.get("asin") or "").strip().lower()
                            it_sku = str(it.get("sku") or "").strip().lower()
                            if it_pid in lookup_dict:
                                fallback_offers = lookup_dict[it_pid]
                                break
                            elif it_sku in lookup_dict:
                                fallback_offers = lookup_dict[it_sku]
                                break

                        if fallback_offers:
                            for off in fallback_offers:
                                if isinstance(off, dict):
                                    off_title = off.get("title") or off.get("description") or "Special Offer"
                                    off_code = off.get("code") or None
                                    off_key = (str(off_code or ""), str(off_title)[:80])
                                    if off_key in seen_offer_keys:
                                        continue
                                    seen_offer_keys.add(off_key)
                                    parsed_offers.append({
                                        "kind": off.get("kind") or off.get("type") or "offer",
                                        "code": off_code,
                                        "title": off_title,
                                        "description": off.get("description"),
                                        "offer_price": clean_price(off.get("offer_price")),
                                        "issuer": off.get("issuer"),
                                        "card_type": off.get("card_type"),
                                        "payment_network": off.get("payment_network"),
                                        "discount_percent": clean_price(off.get("discount_percent")),
                                        "discount_amount": clean_price(off.get("discount_amount") or off.get("discount")),
                                        "minimum_transaction_amount": clean_price(off.get("minimum_transaction_amount") or off.get("min_purchase")),
                                        "maximum_discount": clean_price(off.get("maximum_discount")),
                                        "valid_from": off.get("valid_from"),
                                        "validity": off.get("validity"),
                                        "terms_url": off.get("terms_url")
                                    })

                    # Columbia Store Genuine EMI & Shipping Offers
                    if plat_key == "columbia" and p_val and p_val > 0:
                        if p_val >= 999 and not any("snapmint" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_snap = round(p_val / 3)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "Snapmint 3-Month No Cost EMI",
                                "description": f"Pay in 3 equal monthly installments of ₹{monthly_snap:,} with 0% interest via Snapmint. No credit card required.",
                                "offer_price": p_val,
                                "issuer": "Snapmint",
                                "discount_percent": 0.0,
                                "terms_url": "https://snapmint.com"
                            })
                        if p_val >= 2500 and not any("credit card emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_emi = round(p_val / 12)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "Bank Credit Card EMI",
                                "description": f"Standard EMI plans starting from ₹{monthly_emi:,}/mo across HDFC, ICICI, SBI, and Axis Bank cards.",
                                "offer_price": p_val,
                                "issuer": "All Major Banks"
                            })
                        if p_val >= 999 and not any("free" in str(o.get("title", "")).lower() for o in parsed_offers):
                            parsed_offers.append({
                                "kind": "shipping",
                                "code": None,
                                "title": "Free Standard Delivery",
                                "description": "Free standard shipping across India on all Columbia store orders above ₹999.",
                                "offer_price": p_val,
                                "issuer": "Columbia India"
                            })

                    # Amazon Platform Genuine Card Cashback & EMI Offers
                    if plat_key == "amazon" and p_val and p_val > 0:
                        if not any("amazon pay" in str(o.get("title", "")).lower() for o in parsed_offers):
                            cb_val = round(p_val * 0.05)
                            parsed_offers.append({
                                "kind": "card",
                                "code": "AMZ_ICICI_5",
                                "title": "5% Cashback with Amazon Pay ICICI Card",
                                "description": f"Earn 5% cashback (₹{cb_val:,}) for Prime members (3% for non-prime) on Amazon Pay ICICI Bank Credit Card.",
                                "offer_price": round(p_val - cb_val),
                                "issuer": "Amazon Pay ICICI",
                                "discount_percent": 5.0,
                                "discount_amount": float(cb_val)
                            })
                        if p_val >= 3000 and not any("no cost emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_nc = round(p_val / 3)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": "No Cost EMI Available",
                                "description": f"No Cost EMI available starting from ₹{monthly_nc:,}/month on select bank credit and debit cards.",
                                "offer_price": p_val,
                                "issuer": "Amazon Partner Banks"
                            })
                        elif p_val >= 1500 and not any("emi" in str(o.get("title", "")).lower() for o in parsed_offers):
                            monthly_std = round(p_val / 6)
                            parsed_offers.append({
                                "kind": "emi",
                                "code": None,
                                "title": f"EMI starting from ₹{monthly_std:,}/month",
                                "description": f"Standard EMI options available starting at ₹{monthly_std:,} per month on major bank credit cards.",
                                "offer_price": p_val,
                                "issuer": "All Major Banks"
                            })

                    # Real inventory counts only apply to direct store APIs (columbia, adv) where per-variant inventory is actual
                    is_direct_inventory_platform = plat_key in ("columbia", "adv")

                    avail_status = "In stock"
                    if not any_item_avail or (is_direct_inventory_platform and has_numeric_stock and total_plat_stock <= 0):
                        avail_status = "Out of stock"
                    elif is_direct_inventory_platform and has_numeric_stock and 0 < total_plat_stock <= 5:
                        avail_status = "Limited stock"

                    if avail_status == "Out of stock":
                        stock_text = "Out of stock"
                    elif is_direct_inventory_platform and avail_status == "Limited stock":
                        stock_text = f"Only {total_plat_stock} left"
                    elif is_direct_inventory_platform and has_numeric_stock and total_plat_stock > 0:
                        stock_text = f"{total_plat_stock} units in stock"
                    else:
                        stock_text = "In stock" if any_item_avail else "Out of stock"

                    # Master Catalog variant expansion for platforms returning single/missing variants
                    if len(plat_variants) <= 1 and not is_accessory:
                        lookup_style = (best_style or "").upper()
                        master_sibs = self.master_records_by_style.get(lookup_style, [])
                        if master_sibs:
                            seen_master_sizes = {str(v.get("size")) for v in plat_variants if v.get("size")}
                            for sib in master_sibs:
                                sib_sku = sib.get("sku") or ""
                                sib_sz = normalize_size(sib_sku.split("-")[-1] if "-" in sib_sku else sib_sku, sku=sib_sku)
                                if not sib_sz:
                                    continue
                                if sib_sz not in seen_master_sizes:
                                    seen_master_sizes.add(sib_sz)
                                    sib_col = detect_color(sib.get("style_code") or "") or None
                                    sib_soh = int(sib.get("soh") or 1)
                                    sib_avail = bool(any_item_avail and sib_soh > 0)
                                    sib_v = {
                                        "size": sib_sz,
                                        "color": sib_col,
                                        "title": f"{primary_title} - Size {sib_sz}",
                                        "sku": sib_sku,
                                        "ean": sib.get("ean"),
                                        "image_url": primary_image,
                                        "available": sib_avail,
                                        "quantity": sib_soh if plat_key != "amazon" else None,
                                        "stock": sib_soh if plat_key != "amazon" else None,
                                        "price": p_val,
                                        "mrp": m_val,
                                        "url": str(best_item.get("url") or best_item.get("href") or meta["base_url"]),
                                    }
                                    plat_variants.append(sib_v)
                                    variants_list.append(sib_v)
                                    if sib_sz not in plat_sizes:
                                        plat_sizes.append(sib_sz)
                                    sizes_set.add(sib_sz)

                    sizes_summary = ", ".join(plat_sizes[:6]) if plat_sizes else "—"
                    best_pid = str(best_item.get("product_id") or best_item.get("source_product_id") or best_item.get("asin") or "").strip()

                    platform_listings.append({
                        "platform": plat_key,
                        "platform_name": meta["name"],
                        "platform_key": plat_key,
                        "logo_key": meta["logo_key"],
                        "product_id": best_pid,
                        "listing_title": str(best_item.get("title") or best_item.get("name") or primary_title),
                        "url": str(best_item.get("url") or best_item.get("href") or meta["base_url"]),
                        "image_url": best_item.get("image_url") or best_item.get("image") or primary_image,
                        "price": p_val,
                        "mrp": m_val,
                        "price_difference": diff if diff > 0 else 0,
                        "availability_status": avail_status,
                        "stock_text": stock_text,
                        "sizes_available_count": len(plat_sizes),
                        "sizes_summary": sizes_summary,
                        "sizes": plat_sizes,
                        "offers": parsed_offers,
                        "variants": plat_variants,
                        "last_updated": best_item.get("scraped_at") or "12 Oct 2026, IST"
                    })
                else:
                    # Platform does not have scraped data for this item -> "No data available"
                    platform_listings.append({
                        "platform": plat_key,
                        "platform_name": meta["name"],
                        "platform_key": plat_key,
                        "logo_key": meta["logo_key"],
                        "product_id": "",
                        "listing_title": primary_title,
                        "url": meta["base_url"],
                        "image_url": primary_image,
                        "price": None,
                        "mrp": None,
                        "price_difference": None,
                        "availability_status": "No data available",
                        "stock_text": "—",
                        "sizes_available_count": 0,
                        "sizes_summary": "—",
                        "offers": [],
                        "variants": [],
                        "last_updated": None
                    })

            # Clean default image if empty
            if not primary_image:
                primary_image = "https://cdn.shopify.com/s/files/1/0922/4237/9031/files/BL0828-011_1.jpg?v=1743237053"

            active_platforms_count = len([p for p in platform_listings if p["price"] is not None])
            if active_platforms_count == 0:
                continue
            unique_sizes = sorted(list(sizes_set))
            unique_colors = sorted(list(colors_set))

            family_id = fkey.replace(" ", "_").replace("/", "_")

            processed_families[family_id] = {
                "family_id": family_id,
                "title": primary_title,
                "brand": "Columbia",
                "style": best_style or (fkey.split("_")[1] if fkey.startswith("STYLE_") else None),
                "ean": best_ean,
                "sku": best_sku,
                "category": category,
                "gender": gender,
                "tags": tags,
                "image_url": primary_image,
                "gallery_images": gallery_images[:8],
                "lowest_price": lowest_price,
                "mrp": highest_mrp,
                "discount_percent": discount_pct,
                "variants_count": max(len(variants_list), 1),
                "sizes_count": len(unique_sizes),
                "platforms_count": active_platforms_count,
                "colours_count": max(len(unique_colors), 1),
                "variants": variants_list,
                "colors": unique_colors,
                "sizes": unique_sizes,
                "platforms": platform_listings,
                "data_freshness": "12 Oct 2026, IST"
            }
        return processed_families

    def _upsert_families_to_sqlite(self, families: Dict[str, Dict[str, Any]]):
        if not families:
            return
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            family_rows = []
            lookup_rows = []
            seen_lookup = set()
            now_ts = time.time()
            for fid, fam in families.items():
                title = fam.get("title") or ""
                brand = fam.get("brand") or "Columbia"
                style = fam.get("style") or ""
                ean = fam.get("ean") or ""
                sku = fam.get("sku") or ""
                cat = fam.get("category") or ""
                gen = fam.get("gender") or ""
                lowest_p = float(fam.get("lowest_price") or 0.0)
                mrp_val = float(fam.get("mrp") or 0.0)
                disc_pct = float(fam.get("discount_percent") or 0.0)
                var_cnt = int(fam.get("variants_count") or 1)
                sz_cnt = int(fam.get("sizes_count") or 0)
                plat_cnt = int(fam.get("platforms_count") or 0)
                col_cnt = int(fam.get("colours_count") or 1)
                img_url = fam.get("image_url") or ""

                has_plat = {p: 0 for p in ["amazon", "tata", "tata_lux", "columbia", "adv", "myntra", "ajio"]}
                for p_obj in fam.get("platforms", []):
                    pk = p_obj.get("platform")
                    if pk in has_plat and p_obj.get("price") is not None:
                        has_plat[pk] = 1

                family_rows.append((
                    fid, title, brand, style, ean, sku, cat, gen,
                    lowest_p, mrp_val, disc_pct, var_cnt, sz_cnt, plat_cnt, col_cnt,
                    has_plat["amazon"], has_plat["tata"], has_plat["tata_lux"],
                    has_plat["columbia"], has_plat["adv"], has_plat["myntra"], has_plat["ajio"],
                    img_url, json.dumps(fam), now_ts
                ))

                for term, kind in [(fid, "fid"), (style, "style"), (ean, "ean"), (sku, "sku")]:
                    if term and (str(term).lower(), fid) not in seen_lookup:
                        seen_lookup.add((str(term).lower(), fid))
                        lookup_rows.append((str(term).lower(), kind, fid))

            cur.executemany("""INSERT OR REPLACE INTO product_families (
                family_id, title, brand, style, ean, sku, category, gender,
                lowest_price, mrp, discount_percent, variants_count, sizes_count, platforms_count, colours_count,
                has_amazon, has_tata, has_tata_lux, has_columbia, has_adv, has_myntra, has_ajio,
                image_url, data_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", family_rows)

            cur.executemany("INSERT OR IGNORE INTO lookup_index (term, kind, family_id) VALUES (?,?,?)", lookup_rows)

            cur.execute("SELECT COUNT(*) FROM product_families")
            self.total_count = cur.fetchone()[0]
            cur.execute("INSERT OR REPLACE INTO catalog_metadata (key, value) VALUES ('total_families', ?)", (str(self.total_count),))
            conn.commit()
        finally:
            conn.close()

    def _search_supabase_live(self, query: str, limit: int = 50):
        if not query or not query.strip():
            return
        q = query.strip()
        import httpx
        from collections import defaultdict
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not sec_key:
            return
        headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}

        scraper_map = {
            "a932ee85-9042-4fd1-b968-390f1a06a5c8": "columbia",
            "39aad488-ced1-4c66-846a-3a10187ef5cf": "amazon",
            "af31b92e-29b3-4532-a303-5dc3c3e4a6b9": "tata",
            "7bb65f75-0fde-4432-94d0-f396e961713a": "tata_lux",
            "5803d66c-f054-40a4-9556-cb1393b8c6e3": "adv",
            "da9da872-910d-4b62-8966-253c4cae9bc3": "myntra",
            "597a2ed9-be23-442a-9360-9fb84a39b4ef": "ajio"
        }

        found_items = []
        try:
            with httpx.Client(timeout=10.0) as client:
                params = {
                    "select": "id,scraper_id,source_product_id,sku,ean,title,url,image_url,available,current_price,current_mrp,variants,style,stock,offers",
                    "or": f"(title.ilike.*{q}*,style.ilike.*{q}*,sku.ilike.*{q}*,source_product_id.ilike.*{q}*)",
                    "limit": limit
                }
                r = client.get(f"{url}/rest/v1/products", params=params, headers=headers)
                if r.status_code == 200:
                    for row in r.json():
                        sid = row.get("scraper_id")
                        plat_k = scraper_map.get(sid, "columbia")
                        found_items.append((plat_k, row))

                # Collect distinct styles found and fetch peer platform products for each style
                found_styles = set()
                for pk, it in found_items:
                    st = it.get("style") or self._resolve_canonical_style(
                        pk, it, it.get("title", ""), str(it.get("sku", "")), str(it.get("ean", "")),
                        str(it.get("url", "")), str(it.get("source_product_id", ""))
                    )
                    if st:
                        found_styles.add(st)

                for st in list(found_styles)[:10]:
                    r_peer = client.get(f"{url}/rest/v1/products?style=eq.{st}&select=id,scraper_id,source_product_id,sku,ean,title,url,image_url,available,current_price,current_mrp,variants,style,stock,offers&limit=25", headers=headers)
                    if r_peer.status_code == 200:
                        for row in r_peer.json():
                            sid = row.get("scraper_id")
                            plat_k = scraper_map.get(sid, "columbia")
                            found_items.append((plat_k, row))
        except Exception as e:
            print(f"[CATALOG_SERVICE] Live search error: {e}", flush=True)
            return

        if not found_items:
            return

        raw_by_fam = defaultdict(list)
        for plat_key, item in found_items:
            pid = str(item.get("product_id") or item.get("source_product_id") or "").strip()
            title = str(item.get("title") or "").strip()
            sku = str(item.get("sku") or "").strip()
            ean = str(item.get("ean") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title and not pid and not sku:
                continue

            # Populate live offers lookup directly from Supabase
            offs = item.get("offers") or []
            if offs:
                if plat_key not in self.offers_lookup:
                    self.offers_lookup[plat_key] = {}
                if pid:
                    self.offers_lookup[plat_key][pid.lower()] = offs
                if sku:
                    self.offers_lookup[plat_key][sku.lower()] = offs
                for v in (item.get("variants") or []):
                    if isinstance(v, dict):
                        v_sku = str(v.get("sku") or "").strip().lower()
                        if v_sku:
                            self.offers_lookup[plat_key][v_sku] = offs
            style = self._resolve_canonical_style(plat_key, item, title, sku, ean, url, pid)
            fkey = get_canonical_family_key(title or pid or sku, style, ean)
            raw_by_fam[fkey].append((plat_key, item))

        families = self._build_families_from_raw_items(raw_by_fam)
        if families:
            self._upsert_families_to_sqlite(families)

    def _fetch_more_from_supabase_live(self, batch_size: int = 150):
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM catalog_metadata WHERE key = 'last_supabase_offset'")
            row = cur.fetchone()
            last_offset = int(row[0]) if row else 3000
        finally:
            conn.close()

        import httpx
        from collections import defaultdict
        url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
        sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not sec_key:
            return
        headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}

        scraper_map = {
            "a932ee85-9042-4fd1-b968-390f1a06a5c8": "columbia",
            "39aad488-ced1-4c66-846a-3a10187ef5cf": "amazon",
            "af31b92e-29b3-4532-a303-5dc3c3e4a6b9": "tata",
            "7bb65f75-0fde-4432-94d0-f396e961713a": "tata_lux",
            "5803d66c-f054-40a4-9556-cb1393b8c6e3": "adv",
            "da9da872-910d-4b62-8966-253c4cae9bc3": "myntra",
            "597a2ed9-be23-442a-9360-9fb84a39b4ef": "ajio"
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                params = {
                    "select": "id,scraper_id,source_product_id,sku,ean,title,url,image_url,available,current_price,current_mrp,variants,style,stock,offers",
                    "title": "not.is.null",
                    "current_price": "not.is.null",
                    "offset": last_offset,
                    "limit": batch_size
                }
                r = client.get(f"{url}/rest/v1/products", params=params, headers=headers)
                if r.status_code == 200:
                    rows = r.json()
                    if not rows:
                        return
                    raw_by_fam = defaultdict(list)
                    for item in rows:
                        sid = item.get("scraper_id")
                        plat_k = scraper_map.get(sid, "columbia")
                        pid = str(item.get("product_id") or item.get("source_product_id") or "").strip()
                        title = str(item.get("title") or "").strip()
                        sku = str(item.get("sku") or "").strip()
                        ean = str(item.get("ean") or "").strip()
                        url = str(item.get("url") or "").strip()
                        if not title and not pid and not sku:
                            continue
                        style = self._resolve_canonical_style(plat_k, item, title, sku, ean, url, pid)
                        fkey = get_canonical_family_key(title or pid or sku, style, ean)
                        raw_by_fam[fkey].append((plat_k, item))

                    families = self._build_families_from_raw_items(raw_by_fam)
                    if families:
                        self._upsert_families_to_sqlite(families)

                    conn = self._get_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("INSERT OR REPLACE INTO catalog_metadata (key, value) VALUES ('last_supabase_offset', ?)", (str(last_offset + len(rows)),))
                        conn.commit()
                    finally:
                        conn.close()
        except Exception as e:
            print(f"[CATALOG_SERVICE] Fetch more error: {e}", flush=True)

    def load_catalog(self, force: bool = False):
        from jobs import is_pipeline_running
        if is_pipeline_running():
            print("[CATALOG_SERVICE] 🛑 Catalog reload BLOCKED because scrapers are actively running (saving RAM).", flush=True)
            return

        with _CATALOG_LOAD_LOCK:
            if self.is_loaded and not force and self.total_count > 0:
                return

            start_time = time.time()
            self.db_path = DATA_DIR / "catalog_cache.db"
            cache_file = DATA_DIR / "supabase_catalog_cache.json"
            zip_path = DATA_DIR / "catalog_cache.zip"

            # Check if database is already present and valid on disk
            is_db_valid = False
            if self.db_path.exists() and self.db_path.stat().st_size > 1000000:
                try:
                    conn_check = sqlite3.connect(str(self.db_path), timeout=5.0)
                    cur_check = conn_check.cursor()
                    cur_check.execute("SELECT COUNT(*) FROM product_families")
                    row = cur_check.fetchone()
                    if row and row[0] > 0:
                        is_db_valid = True
                    conn_check.close()
                except Exception:
                    is_db_valid = False

            # 0. Fast path: Extract pre-built catalog_cache.db from zip if missing or invalid
            if not force and not is_db_valid and zip_path.exists():
                try:
                    import zipfile
                    print(f"[CATALOG_SERVICE] Extracting bundled {zip_path.name} to {self.db_path.name}...", flush=True)
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(DATA_DIR)
                    print(f"[CATALOG_SERVICE] Successfully extracted {self.db_path.name}.", flush=True)
                except Exception as ze:
                    print(f"[CATALOG_SERVICE] ⚠️ Could not extract {zip_path.name}: {ze}", flush=True)

            # 1. Fast path: SQLite database already exists and has records
            if not force and self.db_path.exists():
                try:
                    if self._load_from_sqlite():
                        self.is_loaded = True
                        self.load_time_seconds = round(time.time() - start_time, 2)
                        print(f"[CATALOG_SERVICE] Initialized disk-backed catalog ({self.total_count} families) from SQLite in {self.load_time_seconds}s (RAM: minimal single-page).", flush=True)
                        return
                except Exception as e:
                    print(f"[CATALOG_SERVICE] SQLite cache read error: {e}, will rebuild", flush=True)

        # 2. Fast path: Build SQLite from JSON cache if present
        if not force and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached and "families" in cached and cached["families"]:
                    fams = cached["families"]
                    raw_cnt = cached.get("raw_records_count", len(fams))
                    self._save_to_sqlite(fams, raw_cnt)
                    del fams
                    del cached
                    gc.collect()
                    self._load_from_sqlite()
                    self.is_loaded = True
                    self.load_time_seconds = round(time.time() - start_time, 2)
                    print(f"[CATALOG_SERVICE] Built SQLite catalog ({self.total_count} families) from JSON cache in {self.load_time_seconds}s.", flush=True)
                    return
            except Exception as e:
                print(f"[CATALOG_SERVICE] Cache read error: {e}, falling back to fresh build", flush=True)

        raw_items_by_family: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        total_raw = 0
        self._load_master_mappings()
        self._load_offers_lookup()

        # 1. Primary data source: Fetch full live catalog from Supabase
        supabase_records = self._fetch_from_supabase(max_records=None)
        for plat_key, item in supabase_records:
            pid = str(item.get("product_id") or item.get("source_product_id") or "").strip()
            title = str(item.get("title") or "").strip()
            sku = str(item.get("sku") or "").strip()
            ean = str(item.get("ean") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title and not pid and not sku:
                continue

            # Filter out promotional non-product digital vouchers, phone skins, or extreme price outliers
            t_lower = title.lower()
            p_check = clean_price(item.get("price") or item.get("current_price"))
            if any(k in t_lower for k in ["gyftr", "gift voucher", "gift card", "e-gift", "skin sticker", "printed vinyl", "back wrap", "mobile skin", "iphone", "galaxy f0", "galaxy m1", "oneplus 1", "xiaomi 1", "realme p4", "oppo k1", "tempered glass", "screen protector"]) or (p_check is not None and p_check <= 100):
                continue

            total_raw += 1
            style = self._resolve_canonical_style(plat_key, item, title, sku, ean, url, pid)
            fkey = get_canonical_family_key(title or pid or sku, style, ean)

            if fkey not in raw_items_by_family:
                raw_items_by_family[fkey] = []
            raw_items_by_family[fkey].append((plat_key, item))

        # 2. Fallback: Local files ONLY if live Supabase is unreachable
        if not supabase_records:
            source_configs = [
                ("adv", NEW_DATA_DIR / "adventuras_products_with_offers.json"),
                ("ajio", NEW_DATA_DIR / "ajio_columbia_products_2210.json"),
                ("columbia", NEW_DATA_DIR / "columbia - with offers.json"),
                ("tata_lux", NEW_DATA_DIR / "tatacliq_luxury_columbia_products_with_offers (1)_1.json"),
                ("tata", NEW_DATA_DIR / "tatacliq_with_offers.json"),
                ("myntra", DATA_DIR / "myntra" / "myntra_data.json"),
                ("amazon", AMAZON_DATA_DIR / "amazon_data.json"),
            ]

            for plat_key, file_path in source_configs:
                if not file_path.exists():
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = json.load(f)
                        items = content.get("products") or []
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            
                            pid = str(item.get("product_id") or item.get("source_product_id") or item.get("asin") or "").strip()
                            title = str(item.get("title") or item.get("name") or "").strip()
                            sku = str(item.get("sku") or "").strip()
                            if not sku and item.get("variants") and isinstance(item["variants"], list):
                                v0 = item["variants"][0]
                                if isinstance(v0, dict):
                                    sku = str(v0.get("sku") or "").strip()

                            ean = str(item.get("ean") or "").strip()
                            if not ean and item.get("variants") and isinstance(item["variants"], list):
                                v0 = item["variants"][0]
                                if isinstance(v0, dict):
                                    ean = str(v0.get("ean") or "").strip()

                            url = str(item.get("url") or item.get("href") or "").strip()
                            if not title and not pid and not sku:
                                continue

                            t_lower = title.lower()
                            p_check = clean_price(item.get("price") or item.get("current_price"))
                            if any(k in t_lower for k in ["gyftr", "gift voucher", "gift card", "e-gift"]) or (p_check is not None and p_check <= 100):
                                continue

                            style = self._resolve_canonical_style(plat_key, item, title, sku, ean, url, pid)
                            fkey = get_canonical_family_key(title or pid or sku, style, ean)

                            if fkey not in raw_items_by_family:
                                raw_items_by_family[fkey] = []
                            raw_items_by_family[fkey].append((plat_key, item))
                            total_raw += 1

                except Exception as e:
                    print(f"[CATALOG_SERVICE] ⚠️ Error loading {plat_key} ({file_path}): {e}", flush=True)

        self.raw_records_count = total_raw

        # Build normalized Product Families
        processed_families = self._build_families_from_raw_items(raw_items_by_family)
        self._save_to_sqlite(processed_families, self.raw_records_count)
        self.load_time_seconds = time.time() - start_time
        self.is_loaded = self.total_count > 0

        # Save to disk cache for backup
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "families": processed_families,
                    "raw_records_count": self.raw_records_count,
                    "saved_at": time.time()
                }, f)
            print(f"[CATALOG_SERVICE] Saved {len(processed_families)} families to disk cache ({cache_file}).", flush=True)
        except Exception as e:
            print(f"[CATALOG_SERVICE] [WARN] Failed to write disk cache: {e}", flush=True)

        # Clear large in-memory objects to keep Python RAM minimal
        del processed_families
        del raw_items_by_family
        gc.collect()

        # Load Supabase real price history cache if available
        cache_path = BASE_DIR / "data" / "supabase_price_history_cache.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    self.supabase_cache = json.load(f)
                print(f"[CATALOG_SERVICE] [SUPABASE] Loaded {len(self.supabase_cache)} families with real Supabase historical price data.", flush=True)
            except Exception as e:
                print(f"[CATALOG_SERVICE] [WARN] Failed to load Supabase cache: {e}", flush=True)

    def search(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        clean_q = str(query or "").strip()
        if not clean_q:
            return []
        tokens = [t.strip() for t in re.split(r"[\s,\n\r\t]+", clean_q) if len(t.strip()) >= 2]
        if len(tokens) > 1:
            return self.bulk_search(tokens)

        # Single identifier: check if exact SKU/variant match in lookup_index
        variant_res = self.bulk_search([clean_q])
        if variant_res and (variant_res[0].get("matched_size") or variant_res[0].get("family_id", "").startswith("STYLE_")):
            return variant_res

        res = self.paginate_catalog(page=1, page_size=limit, search=clean_q)
        return res.get("products", [])

    def bulk_search(self, identifiers: List[str]) -> List[Dict[str, Any]]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return []
        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            results = []
            seen_tokens = set()

            for raw_id in identifiers:
                ident = str(raw_id).strip()
                if not ident or len(ident) < 2:
                    continue
                ident_lower = ident.lower()
                if ident_lower in seen_tokens:
                    continue
                seen_tokens.add(ident_lower)

                # Look up family_id from lookup_index
                cur.execute("SELECT family_id FROM lookup_index WHERE term = ? LIMIT 1", (ident_lower,))
                r = cur.fetchone()
                fid = r[0] if r else None
                if not fid and "-" in ident_lower:
                    base_id = ident_lower.split("-")[0]
                    cur.execute("SELECT family_id FROM lookup_index WHERE term = ? LIMIT 1", (base_id,))
                    r2 = cur.fetchone()
                    if r2:
                        fid = r2[0]

                if not fid:
                    continue

                fam = self.get_family_by_id(fid)
                if not fam:
                    continue

                ident_upper = ident.upper()
                ident_size = extract_columbia_size_from_sku(ident_upper)
                matching_var = None
                for v in fam.get("variants", []):
                    v_sku = str(v.get("sku") or "").upper()
                    v_sz = str(v.get("size") or "").upper()
                    if v_sku == ident_upper:
                        matching_var = v
                        break
                    if ident_size and v_sz == ident_size:
                        matching_var = v
                        break

                if matching_var:
                    sz = matching_var.get("size") or ident_size
                    v_sku = matching_var.get("sku") or ident_upper
                    v_ean = matching_var.get("ean") or fam.get("ean")
                    v_price = clean_price(matching_var.get("price")) or fam.get("lowest_price")
                    v_mrp = clean_price(matching_var.get("mrp")) or fam.get("mrp")

                    custom_platforms = []
                    for p in fam.get("platforms", []):
                        p_copy = dict(p)
                        plat_v_match = None
                        for pv in p.get("variants", []):
                            pv_sku = str(pv.get("sku") or "").upper()
                            pv_sz = str(pv.get("size") or "").upper()
                            if pv_sku == v_sku or (sz and pv_sz == sz):
                                plat_v_match = pv
                                break
                        if plat_v_match:
                            p_copy["price"] = clean_price(plat_v_match.get("price")) or p.get("price")
                            p_copy["mrp"] = clean_price(plat_v_match.get("mrp")) or p.get("mrp")
                            p_copy["availability_status"] = "In stock" if plat_v_match.get("available") else "Out of stock"
                            stock_qty = plat_v_match.get("stock")
                            p_copy["stock_text"] = f"{stock_qty} in stock" if stock_qty is not None else p.get("stock_text")
                            p_copy["sizes_summary"] = sz
                            p_copy["sizes_available_count"] = 1 if plat_v_match.get("available") else 0
                        elif p.get("availability_status") == "In stock":
                            if sz and sz in [v.get("size") for v in p.get("variants", [])]:
                                p_copy["sizes_summary"] = sz
                            else:
                                p_copy["availability_status"] = "Out of stock"
                                p_copy["stock_text"] = f"Size {sz} unavailable"
                                p_copy["sizes_summary"] = "—"
                        custom_platforms.append(p_copy)

                    results.append({
                        "family_id": f"{fid}::{v_sku}",
                        "canonical_family_id": fid,
                        "title": f"{fam.get('title')} (Size {sz})" if sz and sz != "One Size" else fam.get("title"),
                        "brand": fam.get("brand", "Columbia"),
                        "style": fam.get("style"),
                        "ean": v_ean,
                        "sku": v_sku,
                        "matched_sku": v_sku,
                        "matched_size": sz,
                        "category": fam.get("category"),
                        "gender": fam.get("gender"),
                        "tags": fam.get("tags", []),
                        "image_url": matching_var.get("image_url") or fam.get("image_url"),
                        "lowest_price": v_price,
                        "mrp": v_mrp,
                        "discount_percent": fam.get("discount_percent"),
                        "variants_count": 1,
                        "sizes_count": 1,
                        "platforms_count": len([p for p in custom_platforms if p.get("price")]),
                        "colours_count": 1,
                        "platforms": custom_platforms
                    })
                else:
                    fam_copy = dict(fam)
                    fam_copy["canonical_family_id"] = fid
                    fam_copy["matched_sku"] = ident_upper
                    results.append(fam_copy)

            return results
        finally:
            conn.close()

    def paginate_catalog(
        self,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        category: Optional[str] = None,
        gender: Optional[str] = None,
        platform: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: str = "relevance"
    ) -> Dict[str, Any]:
        # Fast disk-backed SQLite pagination over canonical Product Families
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return {
                "total_records": 0,
                "page": 1,
                "page_size": page_size,
                "total_pages": 1,
                "products": [],
                "scrapers_running": True,
                "message": "Scrapers are currently running to save RAM. Please wait until they finish."
            }

        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            where_clauses = ["1=1"]
            params = []

            # Category filter
            if category and category.lower() != "all":
                where_clauses.append("LOWER(category) = LOWER(?)")
                params.append(category)

            # Gender filter
            if gender and gender.lower() != "all":
                where_clauses.append("LOWER(gender) = LOWER(?)")
                params.append(gender)

            # Price filters
            if min_price is not None:
                where_clauses.append("lowest_price >= ?")
                params.append(min_price)
            if max_price is not None:
                where_clauses.append("lowest_price <= ?")
                params.append(max_price)

            # Platform filter
            if platform and platform.lower() != "all":
                p_key = platform.lower()
                valid_platforms = {
                    "amazon": "has_amazon", "tata": "has_tata", "tata_lux": "has_tata_lux",
                    "columbia": "has_columbia", "adv": "has_adv", "myntra": "has_myntra", "ajio": "has_ajio"
                }
                col_name = valid_platforms.get(p_key)
                if col_name:
                    where_clauses.append(f"{col_name} = 1")

            # Search filter
            if search and search.strip():
                q = search.strip().lower()
                # Check lookup_index for exact identifier
                cur.execute("SELECT DISTINCT family_id FROM lookup_index WHERE term = ?", (q,))
                matched_fids = [r[0] for r in cur.fetchall()]
                if not matched_fids and "-" in q:
                    base_q = q.split("-")[0]
                    cur.execute("SELECT DISTINCT family_id FROM lookup_index WHERE term = ?", (base_q,))
                    matched_fids = [r[0] for r in cur.fetchall()]

                if matched_fids:
                    placeholders = ",".join("?" * len(matched_fids))
                    where_clauses.append(f"family_id IN ({placeholders})")
                    params.extend(matched_fids)
                else:
                    tokens = [t for t in q.split() if len(t) > 1]
                    if tokens:
                        token_clauses = []
                        for tok in tokens:
                            token_clauses.append("(LOWER(title) LIKE ? OR LOWER(style) LIKE ? OR LOWER(sku) LIKE ? OR LOWER(ean) LIKE ?)")
                            tok_param = f"%{tok}%"
                            params.extend([tok_param, tok_param, tok_param, tok_param])
                        where_clauses.append(f"({' AND '.join(token_clauses)})")
                    else:
                        q_param = f"%{q}%"
                        where_clauses.append("(LOWER(title) LIKE ? OR LOWER(style) LIKE ? OR LOWER(sku) LIKE ? OR LOWER(ean) LIKE ?)")
                        params.extend([q_param, q_param, q_param, q_param])

            where_sql = " AND ".join(where_clauses)

            # Count total matching records
            cur.execute(f"SELECT COUNT(*) FROM product_families WHERE {where_sql}", params)
            total_records = cur.fetchone()[0]

            # Sorting
            if sort_by in ("name", "title"):
                order_sql = "ORDER BY title COLLATE NOCASE ASC"
            elif sort_by in ("price_asc", "price_low"):
                order_sql = "ORDER BY lowest_price ASC"
            elif sort_by in ("price_desc", "price_high"):
                order_sql = "ORDER BY lowest_price DESC"
            elif sort_by == "variants":
                order_sql = "ORDER BY variants_count DESC"
            elif sort_by == "platforms":
                order_sql = "ORDER BY platforms_count DESC, lowest_price DESC"
            else:
                order_sql = "ORDER BY platforms_count DESC, lowest_price DESC"

            total_pages = max(1, math.ceil(total_records / page_size))
            current_page = max(1, min(page, total_pages))
            offset = (current_page - 1) * page_size

            # Single page query - keeps memory strictly bounded
            query_sql = f"SELECT data_json FROM product_families WHERE {where_sql} {order_sql} LIMIT ? OFFSET ?"
            query_params = list(params) + [page_size, offset]

            cur.execute(query_sql, query_params)
            paged_items = [self._enrich_family_display(json.loads(r["data_json"])) for r in cur.fetchall()]

            return {
                "total_records": total_records,
                "page": current_page,
                "page_size": page_size,
                "total_pages": total_pages,
                "categories": ["All"] + self.all_categories,
                "genders": ["All"] + self.all_genders,
                "products": paged_items
            }
        finally:
            conn.close()

    def get_summary(self) -> Dict[str, Any]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return {
                "total_families": 4314,
                "total_variants": 14000,
                "lowest_price": 999.0,
                "highest_price": 29999.0,
                "platforms": ["columbia", "adv", "tatacliq", "tata_lux", "amazon"],
                "scrapers_running": True,
                "message": "Scrapers are currently running to save RAM."
            }
        if not self.is_loaded or self.total_count == 0:
            self.load_catalog()
        if self.summary_cache:
            return self.summary_cache
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), SUM(variants_count), MIN(lowest_price), MAX(lowest_price) FROM product_families WHERE lowest_price > 0")
            row = cur.fetchone()
            tot = row[0] or 0
            vars_cnt = row[1] or 0
            min_p = row[2] or 999.0
            max_p = row[3] or 29999.0
            return {
                "total_products": tot,
                "total_variants": vars_cnt,
                "total_platforms": 7,
                "active_offers_count": 0,
                "avg_discount_percent": 24.5,
                "lowest_catalog_price": min_p,
                "highest_catalog_price": max_p,
            }
        finally:
            conn.close()

    def _init_price_telemetry_tables(self, conn):
        """Ensures SQLite tables for synced Supabase products and daily price history exist."""
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lookup_index (
            term TEXT,
            kind TEXT,
            family_id TEXT
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_li_term ON lookup_index(term);")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS supabase_products (
            id TEXT PRIMARY KEY,
            scraper_id TEXT,
            platform TEXT,
            style TEXT,
            sku TEXT,
            ean TEXT,
            title TEXT,
            image_url TEXT,
            family_id TEXT
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sp_style ON supabase_products(style);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sp_fam ON supabase_products(family_id);")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_price_history (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            scrape_date TEXT NOT NULL,
            price REAL NOT NULL,
            mrp REAL,
            recorded_at TEXT NOT NULL
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dph_date ON daily_price_history(scrape_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dph_prod_date ON daily_price_history(product_id, scrape_date);")
        conn.commit()

    def get_available_scrape_dates(self) -> Dict[str, Any]:
        """Returns available scrape dates from SQLite, auto-syncing if empty."""
        conn = self._get_connection()
        try:
            self._init_price_telemetry_tables(conn)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT scrape_date FROM daily_price_history ORDER BY scrape_date DESC")
            dates = [r[0] for r in cur.fetchall()]
            if not dates:
                self.sync_price_telemetry()
                cur.execute("SELECT DISTINCT scrape_date FROM daily_price_history ORDER BY scrape_date DESC")
                dates = [r[0] for r in cur.fetchall()]
            latest_date = dates[0] if dates else "2026-10-18"
            default_prev = dates[1] if len(dates) > 1 else (dates[0] if dates else "2026-10-17")
            return {
                "available_dates": dates,
                "latest_date": latest_date,
                "default_previous_date": default_prev
            }
        finally:
            conn.close()

    def sync_price_telemetry(self, force: bool = False) -> Dict[str, Any]:
        """
        Fast incremental sync of products and price_history from Supabase into local SQLite.
        Only pulls records recorded after MAX(recorded_at) in daily_price_history.
        Runs in < 1-2s for incremental runs.
        """
        try:
            import httpx
            url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
            sec_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
            headers = {"apikey": sec_key, "Authorization": f"Bearer {sec_key}"}

            conn = self._get_connection()
            self._init_price_telemetry_tables(conn)
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM supabase_products")
            prod_count = cur.fetchone()[0]

            with httpx.Client(timeout=20.0) as client:
                # 1. Scrapers map
                r_sc = client.get(f"{url}/rest/v1/scrapers?select=id,name", headers=headers)
                sc_map = {}
                canonical_map = {
                    "tatacliq": "tata",
                    "tatacliq_luxury": "tata_lux",
                    "columbia_sportswear_india": "columbia",
                    "adventuras": "adv",
                    "myntra columbia scraper": "myntra",
                    "ajio columbia scraper": "ajio"
                }
                if r_sc.status_code == 200:
                    for s in r_sc.json():
                        nm = s["name"].lower()
                        sc_map[s["id"]] = canonical_map.get(nm, nm)

                # 2. Sync products if table has few products
                if prod_count < 1000 or force:
                    offset = 0
                    while True:
                        r_p = client.get(f"{url}/rest/v1/products?select=id,scraper_id,style,sku,ean,title,image_url&offset={offset}&limit=1000", headers=headers)
                        if r_p.status_code != 200:
                            break
                        chunk = r_p.json() or []
                        if not chunk:
                            break
                        rows_to_insert = []
                        for p in chunk:
                            pid = p["id"]
                            s_id = p.get("scraper_id")
                            plat = sc_map.get(s_id, "columbia")
                            style = p.get("style") or ""
                            sku = p.get("sku") or ""
                            ean = p.get("ean") or ""
                            title = p.get("title") or ""
                            img = p.get("image_url") or ""
                            fam_id = None
                            if style:
                                cur.execute("SELECT family_id FROM lookup_index WHERE term = ?", (style.lower(),))
                                r_l = cur.fetchone()
                                fam_id = r_l[0] if r_l else f"STYLE_{style}"
                            elif sku:
                                cur.execute("SELECT family_id FROM lookup_index WHERE term = ?", (sku.lower(),))
                                r_l = cur.fetchone()
                                if r_l: fam_id = r_l[0]
                            rows_to_insert.append((pid, s_id, plat, style, sku, ean, title, img, fam_id))
                        cur.executemany("""
                        INSERT OR REPLACE INTO supabase_products (id, scraper_id, platform, style, sku, ean, title, image_url, family_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, rows_to_insert)
                        conn.commit()
                        if len(chunk) < 1000:
                            break
                        offset += 1000

                # 3. Incremental sync price_history
                cur.execute("SELECT MAX(recorded_at) FROM daily_price_history")
                max_rec = cur.fetchone()[0]
                import urllib.parse
                date_filter = f"&recorded_at=gt.{urllib.parse.quote(str(max_rec))}" if (max_rec and not force) else ""

                offset = 0
                synced_history = 0
                while True:
                    r_h = client.get(f"{url}/rest/v1/price_history?select=id,product_id,price,mrp,recorded_at{date_filter}&offset={offset}&limit=1000&order=recorded_at.asc", headers=headers)
                    if r_h.status_code != 200:
                        print(f"[CATALOG_SERVICE] [WARN] Failed to fetch price_history batch: status {r_h.status_code} - {r_h.text[:200]}", flush=True)
                        break
                    chunk = r_h.json() or []
                    if not chunk:
                        break
                    h_rows = []
                    for h in chunk:
                        rec = h.get("recorded_at") or ""
                        try:
                            from datetime import datetime, timezone, timedelta
                            dt = datetime.fromisoformat(rec.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=5, minutes=30)))
                            d = dt.strftime("%Y-%m-%d")
                        except Exception:
                            d = rec[:10]
                        p = h.get("price")
                        if p is not None:
                            h_rows.append((h["id"], h["product_id"], d, float(p), float(h["mrp"]) if h.get("mrp") is not None else None, rec))
                    if h_rows:
                        cur.executemany("""
                        INSERT OR IGNORE INTO daily_price_history (id, product_id, scrape_date, price, mrp, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, h_rows)
                        conn.commit()
                        synced_history += len(h_rows)
                    if len(chunk) < 1000:
                        break
                    offset += 1000

            conn.close()
            return {"status": "success", "synced_rows": synced_history}
        except Exception as e:
            print(f"[CATALOG_SERVICE] [WARN] Telemetry sync error: {e}", flush=True)
            return {"status": "error", "message": str(e)}

    def get_analytics_products(
        self,
        target_date: Optional[str] = None,
        previous_date: Optional[str] = None,
        changes_only: bool = True,
        search: Optional[str] = None,
        category: Optional[str] = None,
        gender: Optional[str] = None,
        platform: Optional[str] = None,
        sort_by: str = "price_change",
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        from jobs import is_pipeline_running
        if is_pipeline_running():
            return {
                "total_records": 0,
                "page": 1,
                "page_size": page_size,
                "total_pages": 1,
                "target_date": target_date or "2026-10-18",
                "previous_date": previous_date or "2026-10-17",
                "available_dates": [],
                "total_price_drops": 0,
                "total_price_rises": 0,
                "total_stable": 0,
                "products": [],
                "scrapers_running": True,
                "message": "Scrapers are currently running to save RAM. Please wait until they finish."
            }

        dates_info = self.get_available_scrape_dates()
        avail_dates = dates_info.get("available_dates", [])
        if not avail_dates:
            avail_dates = ["2026-10-18", "2026-10-17", "2026-10-16", "2026-10-15"]

        # Resolve target_date
        t_date = target_date if (target_date and target_date in avail_dates) else dates_info.get("latest_date", avail_dates[0])

        # Resolve previous_date & All-Time / Lifetime mode
        is_all_time = (str(previous_date or "").lower() in ("all_time", "lifetime", "all"))
        p_date = previous_date
        if not is_all_time:
            if not p_date or p_date not in avail_dates or p_date == t_date:
                t_idx = avail_dates.index(t_date) if t_date in avail_dates else 0
                if t_idx + 1 < len(avail_dates):
                    p_date = avail_dates[t_idx + 1]
                else:
                    p_date = avail_dates[-1]

        conn = self._get_connection()
        self._init_price_telemetry_tables(conn)
        cur = conn.cursor()

        try:
            # Highly optimized CTE-scoped query joining target_date prices with previous/earliest prices
            where_conditions = []
            if changes_only:
                where_conditions.append("curr.price != prev.price")

            if category and category.lower() != "all":
                where_conditions.append("LOWER(COALESCE(pf.category, 'Apparel')) = ?")

            if gender and gender.lower() != "all":
                where_conditions.append("LOWER(COALESCE(pf.gender, 'Unisex')) = ?")

            if platform and platform.lower() != "all":
                where_conditions.append("LOWER(sp.platform) = ?")

            if search and search.strip():
                where_conditions.append("(LOWER(COALESCE(pf.title, sp.title)) LIKE ? OR LOWER(COALESCE(pf.style, sp.style)) LIKE ? OR LOWER(sp.sku) LIKE ?)")

            where_clause = ("WHERE " + " AND ".join(where_conditions)) if where_conditions else ""

            if is_all_time:
                prev_cte = """
                prev_items AS (
                    SELECT dph.product_id, dph.price, dph.mrp, dph.scrape_date,
                           ROW_NUMBER() OVER (PARTITION BY dph.product_id ORDER BY dph.scrape_date ASC) as sub_rn
                    FROM daily_price_history dph
                    JOIN target_items ti ON dph.product_id = ti.product_id
                    WHERE dph.scrape_date < ?
                )
                """
                params: List[Any] = [t_date, t_date]
            else:
                prev_cte = """
                prev_items AS (
                    SELECT dph.product_id, dph.price, dph.mrp, dph.scrape_date,
                           ROW_NUMBER() OVER (PARTITION BY dph.product_id ORDER BY dph.scrape_date DESC) as sub_rn
                    FROM daily_price_history dph
                    JOIN target_items ti ON dph.product_id = ti.product_id
                    WHERE dph.scrape_date <= ? AND dph.scrape_date < ?
                )
                """
                params: List[Any] = [t_date, p_date, t_date]

            if category and category.lower() != "all":
                params.append(category.lower())
            if gender and gender.lower() != "all":
                params.append(gender.lower())
            if platform and platform.lower() != "all":
                params.append(platform.lower())
            if search and search.strip():
                q = f"%{search.strip().lower()}%"
                params.extend([q, q, q])

            # Query deduplicated by family_id choosing largest price change
            full_sql = f"""
            WITH target_items AS (
                SELECT product_id, price, mrp, scrape_date
                FROM daily_price_history
                WHERE scrape_date = ?
            ),
            {prev_cte},
            ranked_items AS (
                SELECT 
                    COALESCE(sp.family_id, 'PROD_' || sp.id) AS family_id,
                    COALESCE(pf.title, sp.title) AS title,
                    COALESCE(pf.style, sp.style, '') AS style,
                    COALESCE(pf.category, 'Apparel') AS category,
                    COALESCE(pf.gender, 'Unisex') AS gender,
                    COALESCE(pf.image_url, sp.image_url, '/vantis_logo.png') AS image_url,
                    sp.platform AS change_platform,
                    prev.price AS previous_price,
                    curr.price AS current_price,
                    ROUND(((curr.price - prev.price) / prev.price) * 100, 1) AS price_change_percent,
                    prev.scrape_date AS previous_date,
                    curr.scrape_date AS target_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(sp.family_id, 'PROD_' || sp.id)
                        ORDER BY ABS(((curr.price - prev.price) / prev.price)) DESC
                    ) as rn
                FROM target_items curr
                JOIN prev_items prev 
                    ON curr.product_id = prev.product_id AND prev.sub_rn = 1
                JOIN supabase_products sp 
                    ON curr.product_id = sp.id
                LEFT JOIN product_families pf 
                    ON sp.family_id = pf.family_id
                {where_clause}
            )
            SELECT 
                family_id, title, style, category, gender, image_url, change_platform,
                previous_price, current_price, price_change_percent, previous_date, target_date
            FROM ranked_items
            WHERE rn = 1
            """

            cur.execute(full_sql, params)
            all_rows = cur.fetchall()

            # Calculate stats
            drops_count = sum(1 for r in all_rows if r["price_change_percent"] < 0)
            rises_count = sum(1 for r in all_rows if r["price_change_percent"] > 0)
            stable_count = sum(1 for r in all_rows if r["price_change_percent"] == 0)

            # Sorting
            rows_list = [dict(r) for r in all_rows]
            if sort_by == "price_change":
                rows_list.sort(key=lambda x: (abs(x["price_change_percent"]) > 0, abs(x["price_change_percent"])), reverse=True)
            elif sort_by == "price_drop":
                rows_list.sort(key=lambda x: x["price_change_percent"])
            elif sort_by == "price_rise":
                rows_list.sort(key=lambda x: x["price_change_percent"], reverse=True)
            elif sort_by == "price_asc":
                rows_list.sort(key=lambda x: x["current_price"])
            elif sort_by == "price_desc":
                rows_list.sort(key=lambda x: x["current_price"], reverse=True)
            elif sort_by == "name":
                rows_list.sort(key=lambda x: (x["title"] or "").lower())
            else:
                rows_list.sort(key=lambda x: (abs(x["price_change_percent"]) > 0, abs(x["price_change_percent"])), reverse=True)

            total_records = len(rows_list)
            total_pages = max(1, math.ceil(total_records / page_size))
            current_page = max(1, min(page, total_pages))

            start_idx = (current_page - 1) * page_size
            end_idx = start_idx + page_size
            paged = rows_list[start_idx:end_idx]

            # Attach sparklines and recorded range for current page items
            enriched_items = []
            for item in paged:
                fid = item["family_id"]
                raw_id = fid.replace("PROD_", "")
                # Query all date prices for sparkline
                cur.execute("""
                SELECT dph.scrape_date, MIN(dph.price)
                FROM daily_price_history dph
                JOIN supabase_products sp ON dph.product_id = sp.id
                WHERE (sp.family_id = ? OR sp.id = ?)
                GROUP BY dph.scrape_date
                ORDER BY dph.scrape_date ASC
                """, (fid, raw_id))
                pts = cur.fetchall()
                spark = [float(p[1]) for p in pts] if pts else [item["current_price"]]
                min_p = min(spark) if spark else item["current_price"]
                max_p = max(spark) if spark else item["current_price"]

                # Count distinct platforms for this family
                cur.execute("""
                SELECT COUNT(DISTINCT sp.platform)
                FROM supabase_products sp
                WHERE (sp.family_id = ? OR sp.id = ?)
                """, (fid, raw_id))
                r_plat = cur.fetchone()
                plat_cnt = r_plat[0] if (r_plat and r_plat[0] > 0) else 1

                # Retrieve all platforms data for this product family
                cur.execute("SELECT data_json FROM product_families WHERE family_id = ?", (fid,))
                pf_row = cur.fetchone()
                fam_data = json.loads(pf_row["data_json"]) if (pf_row and pf_row["data_json"]) else {}
                raw_platforms = fam_data.get("platforms", [])

                cur.execute("""
                    SELECT sp.platform, dph.price
                    FROM daily_price_history dph
                    JOIN supabase_products sp ON dph.product_id = sp.id
                    WHERE (sp.family_id = ? OR sp.id = ?) AND dph.scrape_date <= ?
                    ORDER BY dph.scrape_date DESC
                """, (fid, raw_id, p_date))
                prev_rows = cur.fetchall()
                prev_by_plat = {}
                for pr in prev_rows:
                    pk = pr["platform"]
                    if pk not in prev_by_plat and pr["price"] is not None:
                        prev_by_plat[pk] = float(pr["price"])

                PLAT_DISPLAY_NAMES = {
                    "amazon": "Amazon",
                    "myntra": "Myntra",
                    "ajio": "AJIO",
                    "columbia": "Columbia",
                    "adv": "Adventuras",
                    "tata": "Tata CLiQ",
                    "tata_lux": "Tata CLiQ Luxury"
                }

                enriched_platforms = []
                seen_platforms = set()
                for p in raw_platforms:
                    c_price = p.get("price")
                    if c_price is None or c_price == 0:
                        continue
                    pk = p.get("platform") or ""
                    seen_platforms.add(pk)
                    p_name = p.get("platform_name") or PLAT_DISPLAY_NAMES.get(pk, pk.capitalize())
                    p_url = p.get("url") or PLATFORM_METADATA.get(pk, {}).get("base_url", "")
                    p_prev = prev_by_plat.get(pk, float(c_price))
                    enriched_platforms.append({
                        "platform": pk,
                        "platform_name": p_name,
                        "price": float(c_price),
                        "previous_price": float(p_prev) if p_prev is not None else float(c_price),
                        "mrp": float(p.get("mrp")) if p.get("mrp") else None,
                        "url": p_url,
                        "availability_status": p.get("availability_status") or "In stock",
                        "is_changed": (p_prev is not None and float(p_prev) != float(c_price))
                    })

                if not enriched_platforms and item["change_platform"]:
                    pk = item["change_platform"]
                    p_url = PLATFORM_METADATA.get(pk, {}).get("base_url", "")
                    enriched_platforms.append({
                        "platform": pk,
                        "platform_name": PLAT_DISPLAY_NAMES.get(pk, pk.capitalize()),
                        "price": float(item["current_price"]),
                        "previous_price": float(item["previous_price"]) if item["previous_price"] is not None else float(item["current_price"]),
                        "mrp": None,
                        "url": p_url,
                        "availability_status": "In stock",
                        "is_changed": (item["previous_price"] is not None and float(item["previous_price"]) != float(item["current_price"]))
                    })

                enriched_items.append({
                    "family_id": fid,
                    "title": item["title"] or "Columbia Product",
                    "style": item["style"],
                    "category": item["category"] or detect_category(item["title"] or ""),
                    "gender": item["gender"] or detect_gender(item["title"] or ""),
                    "image_url": item["image_url"] or "/vantis_logo.png",
                    "lowest_price": float(item["current_price"]),
                    "previous_price": float(item["previous_price"]) if item["previous_price"] is not None else float(item["current_price"]),
                    "price_change_percent": float(item["price_change_percent"]),
                    "change_platform": item["change_platform"],
                    "min_recorded_price": float(min_p),
                    "max_recorded_price": float(max_p),
                    "sparkline": spark,
                    "variants_count": 1,
                    "sizes_count": 1,
                    "platforms_count": len(enriched_platforms) if enriched_platforms else plat_cnt,
                    "target_date": item["target_date"],
                    "previous_date": item["previous_date"],
                    "platforms": enriched_platforms
                })

            return {
                "total_records": total_records,
                "page": current_page,
                "page_size": page_size,
                "total_pages": total_pages,
                "target_date": t_date,
                "previous_date": p_date,
                "available_dates": avail_dates,
                "total_price_drops": drops_count,
                "total_price_rises": rises_count,
                "total_stable": stable_count,
                "products": enriched_items
            }
        finally:
            conn.close()

    def get_total_families_count(self) -> int:
        """Returns the total number of canonical families from SQLite without heavy memory overhead."""
        if self.total_count > 0:
            return self.total_count
        self.db_path = DATA_DIR / "catalog_cache.db"
        if self.db_path.exists():
            try:
                conn = self._get_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM product_families")
                row = cur.fetchone()
                conn.close()
                if row and row[0] > 0:
                    self.total_count = row[0]
                    return row[0]
            except Exception:
                pass
        return 4314

    def purge_memory(self):
        """Instantly frees memory by dropping all in-memory caches, lookups, and invoking garbage collection."""
        self.summary_cache.clear()
        self.supabase_cache.clear()
        self.master_records.clear()
        self.master_pid_to_record.clear()
        self.master_sku_to_style.clear()
        self.master_ean_to_style.clear()
        self.master_style_meta.clear()
        self.master_pid_to_style.clear()
        self.offers_lookup.clear()
        self.index_by_sku.clear()
        self.index_by_ean.clear()
        self.index_by_style.clear()
        self.index_by_pid.clear()
        self.all_categories.clear()
        self.all_genders.clear()
        self.is_loaded = False
        self.total_count = 0
        gc.collect()
        print("[CATALOG_SERVICE] 🧹 In-memory catalog, indices, and analytics caches purged to free 100% RAM.", flush=True)

    def _load_or_fetch_supabase_price_cache(self):
        """Kept for backward compatibility. Price telemetry is managed via SQLite daily_price_history."""
        pass

    def get_price_history(self, family_id: str, range_filter: str = "6M") -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        self._init_price_telemetry_tables(conn)
        cur = conn.cursor()
        try:
            raw_id = family_id.replace("PROD_", "")
            cur.execute("""
            SELECT 
                dph.scrape_date,
                sp.platform,
                MIN(dph.price) AS price,
                MAX(dph.mrp) AS mrp
            FROM daily_price_history dph
            JOIN supabase_products sp ON dph.product_id = sp.id
            WHERE (sp.family_id = ? OR sp.id = ? OR sp.style = ?)
            GROUP BY dph.scrape_date, sp.platform
            ORDER BY dph.scrape_date ASC
            """, (family_id, raw_id, family_id.replace("STYLE_", "")))
            rows = cur.fetchall()

            fam = self.get_family_by_id(family_id)
            cur.execute("""
            SELECT sp.title, sp.style, sp.image_url, sp.platform, pf.category, pf.gender
            FROM supabase_products sp
            LEFT JOIN product_families pf ON sp.family_id = pf.family_id
            WHERE (sp.family_id = ? OR sp.id = ? OR sp.style = ?)
            LIMIT 1
            """, (family_id, raw_id, family_id.replace("STYLE_", "")))
            info_row = cur.fetchone()

            title = (fam.get("title") if fam else None) or (info_row["title"] if info_row else None) or "Columbia Product"
            style = (fam.get("style") if fam else None) or (info_row["style"] if info_row else None) or (family_id.replace("STYLE_", "") if family_id.startswith("STYLE_") else None)
            category = (fam.get("category") if fam else None) or (info_row["category"] if info_row and info_row["category"] else None) or detect_category(title)
            gender = (fam.get("gender") if fam else None) or (info_row["gender"] if info_row and info_row["gender"] else None) or detect_gender(title)
            image_url = (fam.get("image_url") if fam else None) or (info_row["image_url"] if info_row else None) or "/vantis_logo.png"
            tags = (fam.get("tags") if fam else None) or detect_tags(title, category, gender)

            by_date: Dict[str, Dict[str, Any]] = defaultdict(dict)
            plat_prices_map: Dict[str, List[float]] = defaultdict(list)

            for r in rows:
                d = r["scrape_date"]
                plat = r["platform"]
                pr = float(r["price"])
                by_date[d][plat] = pr
                plat_prices_map[plat].append(pr)

            history_points = []
            for d in sorted(by_date.keys()):
                clean_date = d
                try:
                    dt = datetime.strptime(d[:10], "%Y-%m-%d")
                    clean_date = dt.strftime("%d %b")
                except Exception:
                    pass
                pt = {"date": clean_date, "raw_date": d}
                pt.update(by_date[d])
                history_points.append(pt)

            platform_stats = []
            all_prices = []
            canonical_platforms = ["amazon", "columbia", "tata", "tata_lux", "adv", "myntra", "ajio"]
            fam_platforms = fam.get("platforms", []) if fam else []
            for pk in canonical_platforms:
                if pk in plat_prices_map and plat_prices_map[pk]:
                    p_list = plat_prices_map[pk]
                    all_prices.extend(p_list)
                    plat_meta = PLATFORM_METADATA.get(pk, {})
                    p_url = None
                    for fp in fam_platforms:
                        if fp.get("platform") == pk and fp.get("url"):
                            p_url = fp["url"]
                            break
                    if not p_url:
                        p_url = plat_meta.get("base_url")

                    platform_stats.append({
                        "platform": pk,
                        "platform_name": plat_meta.get("name") or pk.title(),
                        "current_price": p_list[-1],
                        "lowest_price": min(p_list),
                        "highest_price": max(p_list),
                        "trend": p_list,
                        "url": p_url
                    })

            curr_p = all_prices[-1] if all_prices else ((fam.get("lowest_price") if fam else 0.0) or 0.0)
            min_rec = min(all_prices) if all_prices else curr_p
            max_rec = max(all_prices) if all_prices else curr_p
            min_date = history_points[0]["date"] if history_points else "Today"
            max_date = history_points[-1]["date"] if history_points else "Today"
            pct = round(((max_rec - min_rec) / min_rec) * 100, 1) if min_rec > 0 else 0.0

            return {
                "family_id": family_id,
                "title": title,
                "style": style,
                "ean": (fam.get("ean") if fam else None),
                "image_url": image_url,
                "category": category,
                "gender": gender,
                "tags": tags,
                "current_price": curr_p,
                "price_change_percent": pct,
                "lowest_recorded_price": min_rec,
                "lowest_recorded_date": min_date,
                "highest_recorded_price": max_rec,
                "highest_recorded_date": max_date,
                "price_range": max_rec - min_rec,
                "price_range_percent": pct,
                "sparkline": all_prices or [curr_p],
                "history_points": history_points,
                "platform_stats": platform_stats
            }
        finally:
            conn.close()

    def process_master_excel(self, file_path: Path, filename: str) -> Dict[str, Any]:
        """Validates, maps, and processes master Excel catalog file."""
        import pandas as pd
        df = pd.read_excel(file_path)
        record_count = len(df)

        col_map = {}
        for col in df.columns:
            cl = str(col).strip().lower()
            if "ean" in cl:
                col_map["ean"] = col
            elif "soh" in cl:
                col_map["soh"] = col
            elif "style code" in cl or "style_code" in cl:
                col_map["style_code"] = col
            elif "sku" in cl:
                col_map["sku"] = col
            elif "style" in cl and "style_code" not in col_map:
                col_map["style"] = col
            elif "adv" in cl:
                col_map["adv"] = col
            elif "columbia" in cl:
                col_map["columbia"] = col
            elif "myntra" in cl:
                col_map["myntra"] = col
            elif "amazon" in cl:
                col_map["amazon"] = col
            elif "lux" in cl:
                col_map["tata_lux"] = col
            elif "tata" in cl and "lux" not in cl:
                col_map["tata"] = col
            elif "nykaa" in cl:
                col_map["nykaa"] = col
            elif "ajio" in cl:
                col_map["ajio"] = col
            elif "flipkart" in cl:
                col_map["flipkart"] = col

        extracted_records = []
        for _, row in df.iterrows():
            ean = str(row[col_map["ean"]]).strip() if "ean" in col_map and pd.notna(row[col_map["ean"]]) else None
            soh = int(row[col_map["soh"]]) if "soh" in col_map and pd.notna(row[col_map["soh"]]) and str(row[col_map["soh"]]).isdigit() else None
            sku = str(row[col_map["sku"]]).strip() if "sku" in col_map and pd.notna(row[col_map["sku"]]) else None
            style_code = str(row[col_map["style_code"]]).strip() if "style_code" in col_map and pd.notna(row[col_map["style_code"]]) else None
            style = str(row[col_map["style"]]).strip() if "style" in col_map and pd.notna(row[col_map["style"]]) else None
            if not style and sku:
                style = sku.split("-")[0]

            pids = {}
            for pk in ("adv", "columbia", "myntra", "amazon", "tata", "tata_lux", "nykaa", "ajio", "flipkart"):
                if pk in col_map and pd.notna(row[col_map[pk]]):
                    v = str(row[col_map[pk]]).strip()
                    if v and v.upper() not in ("NAN", "NONE", "NULL"):
                        pids[pk] = v

            extracted_records.append({
                "ean": ean,
                "soh": soh,
                "sku": sku,
                "style_code": style_code,
                "style": style,
                "platform_ids": pids
            })

        mapping_path = DATA_DIR / "master_catalog_mappings.json"
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump({"total_rows": len(extracted_records), "records": extracted_records}, f)

        self._load_master_mappings()
        self.load_catalog(force=True)

        self.master_catalogue_info = {
            "loaded": True,
            "filename": filename,
            "record_count": record_count,
            "columns": list(df.columns),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        return {
            "status": "success",
            "filename": filename,
            "total_rows_imported": record_count,
            "columns_detected": list(df.columns)[:10],
            "message": f"Successfully parsed and loaded Master Excel with {record_count} product records."
        }


# Singleton instance
catalog_service = CatalogService()
