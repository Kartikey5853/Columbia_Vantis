import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_sku_and_style(sku: Optional[str], fallback_title: str = "", fallback_id: str = "") -> Tuple[Optional[str], Optional[str]]:
    """
    Normalizes SKU and Style Code according to Columbia standard.
    Pattern: XXXXX-XXX where XXXXX is the style code (e.g. 2005101, WE8479, 1987111, BL0828).
    Returns (style_code, full_sku). Keeps both.
    """
    clean_sku = str(sku or "").strip().upper()
    style = None

    if clean_sku:
        # Check standard hyphenated pattern XXXXX-XXX
        if "-" in clean_sku:
            parts = clean_sku.split("-")
            style = parts[0].strip()
        elif "_" in clean_sku:
            parts = clean_sku.split("_")
            style = parts[0].strip()
        elif "/" in clean_sku:
            parts = clean_sku.split("/")
            style = parts[0].strip()
        else:
            # Check alphanumeric Columbia pattern: 2 letters + 4 digits (e.g. WE8479, BL0828, FL6087, AE0861)
            m = re.match(r"^([A-Z]{2}\d{4})", clean_sku)
            if m:
                style = m.group(1)
            else:
                # 7-digit Columbia style code (e.g. 2005101, 1987111)
                m7 = re.match(r"^(\d{7})", clean_sku)
                if m7:
                    style = m7.group(1)
                else:
                    # 5-digit style pattern
                    m5 = re.match(r"^(\d{5})", clean_sku)
                    if m5:
                        style = m5.group(1)
                    else:
                        style = clean_sku[:7] if len(clean_sku) >= 7 else clean_sku

    # If no SKU was provided, extract from title or fallback identifier
    if not style:
        text = f"{fallback_title} {fallback_id}".upper()
        # Look for 2 letters + 4 digits
        m_code = re.search(r"\b([A-Z]{2}\d{4})\b", text)
        if m_code:
            style = m_code.group(1)
        else:
            # Look for 7 digits
            m_num = re.search(r"\b(\d{7})\b", text)
            if m_num:
                style = m_num.group(1)

    return (style, clean_sku if clean_sku else None)


def normalize_size(raw_size: Optional[str]) -> str:
    """
    Normalizes size across all platforms into a unified standard system.
    Strips 'UK ', 'US ', 'EU ', 'Size: ', 'IND ' and normalizes apparel & footwear.
    """
    if not raw_size:
        return "ONESIZE"

    s = str(raw_size).strip().upper()

    # Remove common prefix noise
    s = re.sub(r"^(UK|US|EU|IND|IN|SIZE|SZ|EUR)[\s:\-\._]*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"[\s:\-\._]*(UK|US|EU|IND|IN)$", "", s, flags=re.IGNORECASE).strip()

    # Check for apparel mappings
    apparel_map = {
        "SMALL": "S",
        "MEDIUM": "M",
        "LARGE": "L",
        "X-LARGE": "XL",
        "EXTRA LARGE": "XL",
        "XX-LARGE": "XXL",
        "EXTRA EXTRA LARGE": "XXL",
        "2XL": "XXL",
        "3XL": "3XL",
        "XXXL": "3XL",
        "4XL": "4XL",
        "XXXXL": "4XL",
        "FREE SIZE": "ONESIZE",
        "ONE SIZE": "ONESIZE",
        "OS": "ONESIZE",
        "O/S": "ONESIZE",
        "REGULAR": "ONESIZE",
        "STANDARD": "ONESIZE",
    }
    if s in apparel_map:
        return apparel_map[s]

    # Handle composite sizes like "M / 40" -> "M" or "8 / 42" -> "8"
    if "/" in s:
        part = s.split("/")[0].strip()
        if part in apparel_map:
            return apparel_map[part]
        if re.match(r"^\d+(\.\d+)?$", part):
            return part

    # Clean footwear float formats like 8.0 -> 8
    try:
        f_val = float(s)
        if f_val.is_integer():
            return str(int(f_val))
        return str(f_val)
    except ValueError:
        pass

    return s if s else "ONESIZE"


def normalize_offer(raw_offer: Dict[str, Any], platform: str = "") -> Dict[str, Any]:
    """
    Normalizes bank/card/coupon offers into a standardized, deduplicated schema.
    """
    code = (raw_offer.get("code") or raw_offer.get("coupon_code") or "").strip().upper()
    title = (raw_offer.get("title") or raw_offer.get("description") or "").strip()
    kind = (raw_offer.get("kind") or raw_offer.get("type") or "discount").strip().lower()

    # Discount percent
    pct = raw_offer.get("discount_percent") or raw_offer.get("discount_percentage") or raw_offer.get("discount")
    try:
        pct_val = float(pct) if pct is not None else None
    except (ValueError, TypeError):
        pct_val = None

    # Max discount
    max_d = raw_offer.get("maximum_discount") or raw_offer.get("max_discount")
    try:
        max_d_val = float(max_d) if max_d is not None else None
    except (ValueError, TypeError):
        max_d_val = None

    # Min purchase
    min_p = raw_offer.get("minimum_transaction_amount") or raw_offer.get("min_purchase") or raw_offer.get("min_order_value")
    try:
        min_p_val = float(min_p) if min_p is not None else None
    except (ValueError, TypeError):
        min_p_val = None

    # Extract discount pct from title if missing (e.g. "10% Instant Discount")
    if pct_val is None and title:
        m = re.search(r"(\d+)%\s*(OFF|DISCOUNT|INSTANT)", title, re.IGNORECASE)
        if m:
            pct_val = float(m.group(1))

    # Clean issuer / card network
    issuer = raw_offer.get("issuer")
    if not issuer and title:
        for bank in ("HDFC", "ICICI", "AXIS", "SBI", "KOTAK", "BOB", "HSBC", "AMEX", "SNAPMINT", "SIMPL"):
            if bank in title.upper():
                issuer = bank
                break

    return {
        "platform": platform,
        "code": code if code else None,
        "title": title if title else (f"{int(pct_val)}% Discount" if pct_val else "Special Offer"),
        "kind": kind,
        "discount_percent": pct_val,
        "maximum_discount": max_d_val,
        "minimum_purchase": min_p_val,
        "issuer": issuer,
        "valid_until": raw_offer.get("valid_until") or raw_offer.get("validity")
    }
