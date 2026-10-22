import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple


@dataclass
class SellerTarget:
    seller_id: str
    name: str
    base_url: str

    def get_page_url(self, page_no: int) -> str:
        """Constructs URL for a given page number preserving original query params."""
        parsed = urllib.parse.urlparse(self.base_url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        # Flatten query dict
        query_dict = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
        # Ensure essential merchant params
        query_dict["i"] = "merchant-items"
        query_dict["me"] = self.seller_id
        if "s" not in query_dict:
            query_dict["s"] = "popularity-rank"
        if "fs" not in query_dict:
            query_dict["fs"] = "true"

        if page_no > 1:
            query_dict["page"] = str(page_no)
        else:
            query_dict.pop("page", None)

        encoded_query = urllib.parse.urlencode(query_dict, doseq=True)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or "www.amazon.in"
        path = parsed.path or "/s"
        return urllib.parse.urlunparse((scheme, netloc, path, "", encoded_query, ""))


def clean_price(price_str: Optional[str]) -> Optional[float]:
    """Cleans currency string (e.g. '₹13,999.00', '1,499') into float."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(price_str).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def parse_seller_entry(line: str) -> Optional[SellerTarget]:
    """
    Parses a single line from sellers.txt.
    Supports:
    - Full URL: https://www.amazon.in/s?i=merchant-items&me=AUEEW31YCNC4K&s=popularity-rank&fs=true
    - ID with name: AUEEW31YCNC4K:Chogori
    - Raw ID: AUEEW31YCNC4K
    """
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None

    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urllib.parse.urlparse(cleaned)
        params = urllib.parse.parse_qs(parsed.query)
        seller_id = (params.get("me") or [""])[0].strip()
        if not seller_id:
            # Fallback regex search for me=XXXX in the url
            m = re.search(r"[?&]me=([A-Z0-9]+)", cleaned)
            if m:
                seller_id = m.group(1)

        if not seller_id:
            return None

        KNOWN_SELLER_NAMES = {
            "A1WYWER0W24N8S": "Cocoblu",
            "AUEEW31YCNC4K": "Chogori",
            "A28E8JCZPT1G5K": "Columbia India",
        }
        seller_name = KNOWN_SELLER_NAMES.get(seller_id, seller_id)
        return SellerTarget(seller_id=seller_id, name=seller_name, base_url=cleaned)

    # Key:Name or Raw Key
    if ":" in cleaned:
        parts = cleaned.split(":", 1)
        seller_id = parts[0].strip()
        seller_name = parts[1].strip() or seller_id
    else:
        seller_id = cleaned
        seller_name = cleaned

    default_url = (
        f"https://www.amazon.in/s?i=merchant-items"
        f"&me={seller_id}"
        f"&s=popularity-rank"
        f"&fs=true"
    )
    return SellerTarget(seller_id=seller_id, name=seller_name, base_url=default_url)


def load_sellers_from_file(file_path: Path) -> List[SellerTarget]:
    """Reads sellers configuration file and returns a list of unique SellerTargets."""
    if not file_path.exists():
        return []
    targets: List[SellerTarget] = []
    seen_ids = set()

    for line in file_path.read_text(encoding="utf-8").splitlines():
        target = parse_seller_entry(line)
        if target and target.seller_id not in seen_ids:
            targets.append(target)
            seen_ids.add(target.seller_id)
    return targets


# Ultra-fast, zero-overhead browser evaluation script
EXTRACT_CARDS_JS = r"""
() => {
    const cards = document.querySelectorAll('div[data-component-type="s-search-result"]');
    const items = [];
    
    for (const card of cards) {
        const asin = (card.getAttribute('data-asin') || '').trim();
        if (!asin) continue;
        
        let title = '';
        const titleEl = card.querySelector('a h2 span');
        if (titleEl) title = titleEl.textContent.trim();
        
        // Prices
        let price = '';
        let mrp = '';
        const priceOffscreen = card.querySelector('span.a-price:not([data-a-strike="true"]) > span.a-offscreen');
        if (priceOffscreen) {
            price = priceOffscreen.textContent.trim();
        } else {
            const anyPrice = card.querySelector('span.a-price > span.a-offscreen');
            if (anyPrice) price = anyPrice.textContent.trim();
        }
        
        const strikePrice = card.querySelector('span.a-price[data-a-strike="true"] > span.a-offscreen, span.a-text-price > span.a-offscreen');
        if (strikePrice) {
            mrp = strikePrice.textContent.trim();
        }
        
        // Image
        let image = '';
        const imgEl = card.querySelector('img.s-image');
        if (imgEl) image = imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '';
        
        // Href
        let href = '';
        const linkEl = card.querySelector('a[href*="/dp/"]');
        if (linkEl) {
            href = linkEl.getAttribute('href') || '';
            if (href.startsWith('/')) href = 'https://www.amazon.in' + href;
        }
        
        // Brand
        let brand = '';
        if (href) {
            const parts = href.split('/').filter(Boolean);
            const dpIdx = parts.indexOf('dp');
            if (dpIdx > 0) {
                const slug = parts[dpIdx - 1];
                brand = slug.split('-')[0].toLowerCase();
            }
        }
        if (!brand && title) {
            brand = title.split(' ')[0].toLowerCase();
        }
        
        // Size Variations
        let variations = [];
        const varEl = card.querySelector('[data-puis-atcb-add-action-sizevariation]');
        if (varEl) {
            const rawAttr = varEl.getAttribute('data-puis-atcb-add-action-sizevariation');
            if (rawAttr) {
                try {
                    const parsedData = JSON.parse(rawAttr);
                    if (Array.isArray(parsedData.variations)) {
                        variations = parsedData.variations;
                    }
                } catch (e) {}
            }
        }

        // Genuine Coupons & Promotional Deals & EMI
        let offers = [];
        const couponEl = card.querySelector('span[class*="coupon"], span.s-coupon-unclipped, span[data-action="coupon"]');
        if (couponEl) {
            const cText = couponEl.textContent.trim();
            if (cText && cText.length > 2) {
                offers.push({
                    kind: 'coupon',
                    code: 'AMZ_COUPON',
                    title: cText,
                    description: cText,
                    issuer: 'Amazon'
                });
            }
        }

        // Text-based EMI & Bank / Cashback offers from card text
        const cardText = (card.innerText || card.textContent || '');
        if (cardText.includes('No Cost EMI')) {
            offers.push({
                kind: 'emi',
                title: 'No Cost EMI Available',
                description: 'No Cost EMI available on select bank cards.',
                issuer: 'Amazon Partner Banks'
            });
        }
        const emiMatch = cardText.match(/EMI starts at ₹\s*([0-9,]+)/i);
        if (emiMatch) {
            offers.push({
                kind: 'emi',
                title: `EMI starts at ₹${emiMatch[1]}/mo`,
                description: `Standard EMI options starting from ₹${emiMatch[1]} per month.`,
                issuer: 'All Major Banks'
            });
        }
        if (cardText.includes('cashback') || cardText.includes('Cashback')) {
            const cbMatch = cardText.match(/([0-9]+%?\s*cashback[^\r\n.]+)/i);
            offers.push({
                kind: 'card',
                title: cbMatch ? cbMatch[1].trim() : 'Amazon Card Cashback',
                description: cbMatch ? cbMatch[1].trim() : 'Cashback on select bank cards.',
                issuer: 'Amazon Pay'
            });
        }
        
        items.push({
            asin,
            title,
            brand,
            price,
            mrp,
            image,
            href,
            variations,
            offers,
            is_columbia: brand === 'columbia' || title.toLowerCase().includes('columbia')
        });
    }
    
    // Pagination status
    const nextBtn = document.querySelector('a.s-pagination-next');
    const hasNext = nextBtn !== null && !nextBtn.classList.contains('s-pagination-disabled');
    
    // Detection markers
    const bodyText = document.body ? document.body.innerText : '';
    const noResults = bodyText.includes('No results for your search query.') || bodyText.includes('No results for');
    const isBot = bodyText.includes('Robot Check') || bodyText.includes('Enter the characters you see');
    const is503 = document.title.includes('503') || bodyText.includes("It's rush hour and traffic is piling up") || bodyText.includes('Service Unavailable');
    
    return {
        items,
        hasNext,
        noResults,
        isBot,
        is503
    };
}
"""


def merge_extracted_items(
    products_map: Dict[str, Dict[str, Any]],
    extracted_items: List[Dict[str, Any]],
    seller_id: str,
    seller_name: str,
) -> Tuple[int, int, int]:
    """
    Merges items extracted from cards on a page into the master products dictionary.
    Returns: (cards_seen, accepted_columbia, rejected_non_columbia)
    """
    cards_seen = 0
    accepted_columbia = 0
    rejected_non_columbia = 0

    for item in extracted_items:
        cards_seen += 1
        asin = item["asin"]
        title = item.get("title", "")
        brand = item.get("brand", "")
        price_raw = item.get("price", "")
        mrp_raw = item.get("mrp", "")
        price_num = clean_price(price_raw)
        mrp_num = clean_price(mrp_raw)
        image = item.get("image", "")
        href = item.get("href", "")
        variations = item.get("variations", [])
        is_columbia = bool(item.get("is_columbia", False))

        if is_columbia:
            accepted_columbia += 1
        else:
            rejected_non_columbia += 1

        family = [asin] + [v for v in variations if v != asin]

        # 1. Main Product
        if asin not in products_map:
            products_map[asin] = {
                "asin": asin,
                "brand": brand,
                "family": family,
                "title": title,
                "price": price_raw,
                "price_numeric": price_num,
                "mrp": mrp_raw,
                "mrp_numeric": mrp_num,
                "image": image,
                "href": href,
                "is_main": True,
                "is_columbia": is_columbia,
                "seller_id": seller_id,
                "seller_name": seller_name,
            }
        else:
            existing = products_map[asin]
            if title:
                existing["title"] = title
            if price_raw:
                existing["price"] = price_raw
                existing["price_numeric"] = price_num
            if mrp_raw:
                existing["mrp"] = mrp_raw
                existing["mrp_numeric"] = mrp_num
            if image:
                existing["image"] = image
            if href:
                existing["href"] = href
            if brand:
                existing["brand"] = brand
            existing["is_main"] = True
            existing["is_columbia"] = existing["is_columbia"] or is_columbia
            if len(family) > len(existing.get("family", [])):
                existing["family"] = family

        # 2. Add variation ASINs if not yet in map
        for var_asin in variations:
            if var_asin not in products_map:
                products_map[var_asin] = {
                    "asin": var_asin,
                    "brand": brand,
                    "family": family,
                    "title": "",
                    "price": "",
                    "price_numeric": None,
                    "mrp": "",
                    "mrp_numeric": None,
                    "image": "",
                    "href": f"https://www.amazon.in/dp/{var_asin}",
                    "is_main": False,
                    "is_columbia": is_columbia,
                    "seller_id": seller_id,
                    "seller_name": seller_name,
                }
            else:
                existing_var = products_map[var_asin]
                if len(family) > len(existing_var.get("family", [])):
                    existing_var["family"] = family

    return cards_seen, accepted_columbia, rejected_non_columbia
