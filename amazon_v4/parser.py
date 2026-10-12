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
        query_dict = {k: v[0] if len(v) == 1 else v for k, v in params.items()}

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
    """Parses a single line from sellers.txt."""
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None

    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urllib.parse.urlparse(cleaned)
        params = urllib.parse.parse_qs(parsed.query)
        seller_id = (params.get("me") or [""])[0].strip()
        if not seller_id:
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


def compute_amazon_payment_offers(price: Optional[float], mrp: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Computes Amazon bank offers, EMI options, and cashback offers dynamically
    based on the selling price and active Amazon promotion rules.
    
    Examples generated:
    1. Instant Bank Discount: SBI Credit Card (10% instant discount up to ₹500/₹1500)
    2. Bank EMI: SBI Credit Card EMI (e.g. ₹1,543 x 3m)
    3. Cashback: Amazon Pay ICICI Bank Credit Card (3% or 5% cashback, e.g. ₹149)
    """
    if not price or price <= 0:
        return []

    offers = []

    # 1. SBI Credit Card Instant Discount (10% up to ₹500 for min spend >= ₹1,000)
    if price >= 1000:
        discount = round(min(500.0, price * 0.10), 2)
        final_buy_price = round(price - discount, 2)
        offers.append({
            "kind": "bank_offer",
            "type": "INSTANT_DISCOUNT",
            "title": f"Buy for ₹{final_buy_price:,.2f}",
            "issuer": "SBI",
            "card_type": "SBI Credit Card",
            "discount_amount": discount,
            "discount_percent": 10.0,
            "offer_price": final_buy_price,
            "minimum_transaction_amount": 1000.0,
            "description": f"SBI Credit Card instant discount -₹{discount:,.2f}. Buy for ₹{final_buy_price:,.2f}",
            "terms_url": "https://www.amazon.in/events/bankoffers"
        })

    # 2. SBI Credit Card EMI (3 Months)
    if price >= 3000:
        discount = round(min(500.0, price * 0.10), 2)
        emi_base = price - discount
        # 3 month standard tenure with nominal rate
        emi_monthly = round((emi_base * 1.03) / 3, 2)
        offers.append({
            "kind": "emi_offer",
            "type": "BANK_EMI",
            "title": f"EMI ₹{emi_monthly:,.2f} x 3m",
            "issuer": "SBI",
            "card_type": "SBI Credit Card EMI",
            "discount_amount": discount,
            "monthly_installment": emi_monthly,
            "tenure_months": 3,
            "minimum_transaction_amount": 3000.0,
            "description": f"SBI Credit Card EMI ₹{emi_monthly:,.2f} x 3m (includes -₹{discount:,.2f} discount)",
            "terms_url": "https://www.amazon.in/gp/help/customer/display.html?nodeId=202054240"
        })

    # 3. Amazon Pay ICICI Bank Credit Card Cashback (3% / 5%)
    cashback_amount = round(price * 0.03, 2)
    offers.append({
        "kind": "cashback",
        "type": "CASHBACK",
        "title": f"Buy for ₹{price:,.2f} + cashback",
        "issuer": "Amazon Pay ICICI Bank",
        "card_type": "Amazon Pay ICICI Bank Credit Card",
        "cashback_amount": cashback_amount,
        "discount_percent": 3.0,
        "description": f"₹{cashback_amount:,.2f} cashback with Amazon Pay ICICI Bank Credit Card",
        "terms_url": "https://www.amazon.in/cbcc/ref=apay_cbcc_pdp"
    })

    return offers


# Zero-overhead in-browser search card evaluation script with stock, prices, and variation extraction
EXTRACT_CARDS_JS = """
() => {
    const cards = document.querySelectorAll('div[data-component-type="s-search-result"]');
    const items = [];
    
    for (const card of cards) {
        const asin = (card.getAttribute('data-asin') || '').trim();
        if (!asin) continue;
        
        // 1. Title
        let title = '';
        const titleEl = card.querySelector('a h2 span');
        if (titleEl) title = titleEl.textContent.trim();
        
        // 2. Selling Price (Price to pay / Actual selling price)
        let price = '';
        const priceOffscreen = card.querySelector('span.a-price:not([data-a-strike="true"]) > span.a-offscreen');
        if (priceOffscreen) {
            price = priceOffscreen.textContent.trim();
        } else {
            const anyPrice = card.querySelector('span.a-price > span.a-offscreen');
            if (anyPrice) price = anyPrice.textContent.trim();
        }
        
        // 3. M.R.P. (List price / Strikethrough price)
        let mrp = '';
        const strikePrice = card.querySelector('span.a-price[data-a-strike="true"] > span.a-offscreen, span.a-text-price > span.a-offscreen');
        if (strikePrice) {
            mrp = strikePrice.textContent.trim();
        }
        
        // 4. Discount % badge (e.g. 33% off)
        let discountPercent = null;
        const discountBadge = card.querySelector('span.a-badge-text, span[aria-label*="% off"], span[aria-label*="discount"]');
        if (discountBadge) {
            const m = discountBadge.textContent.match(/(\\d+)%/);
            if (m) discountPercent = Number(m[1]);
        }
        
        // 5. Stock / Availability / Quantity Left
        let stockText = '';
        let quantity = null;
        let inStock = true;
        
        const cardText = card.innerText || '';
        const stockMatches = cardText.match(/Only\\s+(\\d+)\\s+left\\s+in\\s+stock/i);
        if (stockMatches) {
            quantity = Number(stockMatches[1]);
            stockText = stockMatches[0];
            inStock = true;
        } else if (/Currently\\s+unavailable|Out\\s+of\\s+stock/i.test(cardText)) {
            inStock = false;
            quantity = 0;
            stockText = 'Currently unavailable';
        } else {
            stockText = 'In stock';
            inStock = true;
        }
        
        // 6. Image URL
        let image = '';
        const imgEl = card.querySelector('img.s-image');
        if (imgEl) image = imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '';
        
        // 7. Product URL
        let href = '';
        const linkEl = card.querySelector('a[href*="/dp/"]');
        if (linkEl) {
            href = linkEl.getAttribute('href') || '';
            if (href.startsWith('/')) href = 'https://www.amazon.in' + href;
        }
        
        // 8. Brand
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
        
        // 9. Size Variations
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
        
        // 10. Coupons (e.g. Save ₹200 with coupon)
        const couponEl = card.querySelector('.s-coupon-highlight-color');
        const couponText = couponEl ? couponEl.textContent.trim() : '';
        
        items.push({
            asin,
            title,
            brand,
            price,
            mrp,
            discount_percent: discountPercent,
            stock_text: stockText,
            quantity: quantity,
            in_stock: inStock,
            coupon: couponText,
            image,
            href,
            variations,
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
    Includes actual selling price, M.R.P., stock, quantity, and computed offers.
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
        if mrp_num is None and price_num is not None:
            mrp_num = price_num

        image = item.get("image", "")
        href = item.get("href", "")
        variations = item.get("variations", [])
        is_columbia = bool(item.get("is_columbia", False))
        in_stock = item.get("in_stock", True)
        quantity = item.get("quantity")
        stock_text = item.get("stock_text", "In stock")

        if is_columbia:
            accepted_columbia += 1
        else:
            rejected_non_columbia += 1

        family = [asin] + [v for v in variations if v != asin]

        # Compute Offers for this price
        offers = compute_amazon_payment_offers(price_num, mrp_num)
        coupon = item.get("coupon")
        if coupon:
            offers.insert(0, {
                "kind": "coupon",
                "type": "COUPON",
                "title": coupon,
                "description": coupon,
                "code": "APPLY_ON_PAGE",
                "discount_amount": clean_price(coupon),
                "offer_price": (price_num - clean_price(coupon)) if price_num and clean_price(coupon) else price_num,
                "terms_url": href
            })

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
                "available": in_stock,
                "stock": quantity if quantity is not None else in_stock,
                "quantity": quantity,
                "stock_text": stock_text,
                "image": image,
                "href": href,
                "is_main": True,
                "is_columbia": is_columbia,
                "seller_id": seller_id,
                "seller_name": seller_name,
                "offers": offers,
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
            existing["available"] = in_stock
            existing["stock"] = quantity if quantity is not None else in_stock
            existing["quantity"] = quantity
            existing["stock_text"] = stock_text
            existing["offers"] = offers
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
                    "available": in_stock,
                    "stock": quantity if quantity is not None else in_stock,
                    "quantity": quantity,
                    "stock_text": stock_text,
                    "image": "",
                    "href": f"https://www.amazon.in/dp/{var_asin}",
                    "is_main": False,
                    "is_columbia": is_columbia,
                    "seller_id": seller_id,
                    "seller_name": seller_name,
                    "offers": [],
                }
            else:
                existing_var = products_map[var_asin]
                if len(family) > len(existing_var.get("family", [])):
                    existing_var["family"] = family

    return cards_seen, accepted_columbia, rejected_non_columbia
