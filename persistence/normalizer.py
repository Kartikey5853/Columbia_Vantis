import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_sku_and_style(sku: Optional[str], fallback_title: str = "", fallback_id: str = "") -> Tuple[Optional[str], Optional[str]]:
    """
    Normalizes SKU and Style Code according to Columbia standard.
    Pattern: XXXXX-XXX where XXXXX is the style code (e.g. 2005101, WE8479, 1987111, BL0828, AM1572).
    Returns (style_code, normalized_sku). Keeps both.
    - Style: XXXXX (the first 5-7 chars)
    - SKU: XXXXX-XXX (style + 3-char color code, stripped of variant size noise)
    """
    clean_raw = str(sku or "").strip().upper()
    style = None
    norm_sku = None

    if clean_raw:
        is_marketplace_id = clean_raw.startswith("MP0") or (clean_raw.startswith("B0") and len(clean_raw) == 10)
        if not is_marketplace_id:
            sep = "-" if "-" in clean_raw else ("_" if "_" in clean_raw else ("/" if "/" in clean_raw else None))
            if sep:
                parts = [p.strip() for p in clean_raw.split(sep) if p.strip()]
                if len(parts) >= 2:
                    style = parts[0]
                    norm_sku = f"{parts[0]}-{parts[1]}"
                elif len(parts) == 1:
                    style = parts[0]
                    norm_sku = parts[0]
            else:
                m = re.match(r"^([A-Z]{2}\d{4})", clean_raw)
                if m:
                    style = m.group(1)
                    norm_sku = clean_raw
                else:
                    m7 = re.match(r"^(\d{7})", clean_raw)
                    if m7:
                        style = m7.group(1)
                        norm_sku = clean_raw
                    else:
                        m5 = re.match(r"^(\d{5})", clean_raw)
                        if m5:
                            style = m5.group(1)
                            norm_sku = clean_raw
                        else:
                            norm_sku = clean_raw

    # Fallback extraction from title or ID if style was not found
    if not style:
        text = f"{fallback_title} {fallback_id}".upper()
        m_code = re.search(r"\b([A-Z]{2}\d{4})\b", text)
        if m_code:
            style = m_code.group(1)
        else:
            m_num = re.search(r"\b(\d{7})\b", text)
            if m_num:
                style = m_num.group(1)
            else:
                m_num5 = re.search(r"\b(\d{5})\b", text)
                if m_num5:
                    style = m_num5.group(1)

    if not norm_sku and style:
        norm_sku = style

    return (style, norm_sku if norm_sku else (clean_raw if clean_raw else None))


def normalize_size(raw_size: Optional[str]) -> str:
    """
    Normalizes size across all platforms into a unified standard system.
    Strips 'UK ', 'US ', 'EU ', 'Size: ', 'IND ' and normalizes apparel & footwear.
    Returns empty string "" if the size is missing, None, or a placeholder (e.g. Default Title, OS, OneSize, Standard).
    """
    if not raw_size:
        return ""

    s = str(raw_size).strip()
    if not s:
        return ""

    # Check for placeholder / fake sizes when product has no real sizes
    FAKE_SIZE_MARKERS = {
        "DEFAULT TITLE", "DEFAULT", "STANDARD", "REGULAR", "ONESIZE", "ONE SIZE",
        "ONE-SIZE", "FREE SIZE", "FREESIZE", "OS", "O/S", "NA", "N/A", "NONE",
        "NO SIZE", "NOSIZE", "ALL", "UNIVERSAL", "0", "0.0"
    }
    s_upper = s.upper()
    if s_upper in FAKE_SIZE_MARKERS:
        return ""

    # Remove common prefix noise
    s_clean = re.sub(r"^(UK|US|EU|IND|IN|SIZE|SZ|EUR)[\s:\-\._]*", "", s_upper, flags=re.IGNORECASE).strip()
    s_clean = re.sub(r"[\s:\-\._]*(UK|US|EU|IND|IN)$", "", s_clean, flags=re.IGNORECASE).strip()

    if not s_clean or s_clean in FAKE_SIZE_MARKERS:
        return ""

    # Check for apparel mappings
    apparel_map = {
        "XXS": "XXS",
        "XS": "XS",
        "S": "S",
        "M": "M",
        "L": "L",
        "XL": "XL",
        "XXL": "XXL",
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
    }
    if s_clean in apparel_map:
        return apparel_map[s_clean]

    # Handle composite sizes like "M / 40" -> "M" or "8 / 42" -> "8"
    if "/" in s_clean:
        part = s_clean.split("/")[0].strip()
        if part in apparel_map:
            return apparel_map[part]
        if re.match(r"^\d+(\.\d+)?$", part):
            try:
                f_val = float(part)
                return str(int(f_val)) if f_val.is_integer() else str(f_val)
            except ValueError:
                return part

    # Clean footwear float formats like 8.0 -> 8
    try:
        f_val = float(s_clean)
        if f_val.is_integer():
            return str(int(f_val))
        return str(f_val)
    except ValueError:
        pass

    # Reject if it looks like a color or non-size text (e.g. length > 12 chars without digits)
    if len(s_clean) > 12 and not re.search(r"\d", s_clean):
        return ""

    return s_clean


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
