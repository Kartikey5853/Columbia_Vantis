import io
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

PLATFORM_ORDER = [
    ("columbia", "Columbia India"),
    ("amazon", "Amazon"),
    ("tata", "Tata CLiQ"),
    ("tata_lux", "Tata CLiQ Luxury"),
    ("adv", "Adventuras"),
    ("myntra", "Myntra"),
    ("ajio", "AJIO"),
]

HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
BORDER_THIN = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="E2E8F0"),
)

def generate_catalog_excel(families: List[Dict[str, Any]]) -> bytes:
    """
    Builds a comprehensive multi-sheet Excel file:
    - Sheet 1: Summary Sheet containing canonical Style, Title, Category, Gender,
               and selling price & MRP across all 7 platforms side-by-side.
    - Sheets 2..8: One dedicated sheet per platform containing Title, Style, URL,
                   Image Link, Price, MRP, Stock, Sizes, Variants, Offers (left to right).
    """
    wb = openpyxl.Workbook()

    # ---------------------------------------------------------
    # 1. SUMMARY SHEET
    # ---------------------------------------------------------
    ws_sum = wb.active
    ws_sum.title = "Summary - All Platforms"
    ws_sum.views.sheetView[0].showGridLines = True

    sum_headers = [
        "SKU",
        "EAN",
        "Style",
        "Product Title",
        "Columbia Price (₹)",
        "Columbia MRP (₹)",
        "Amazon Price (₹)",
        "Amazon MRP (₹)",
        "Tata CLiQ Price (₹)",
        "Tata CLiQ MRP (₹)",
        "Tata Luxury Price (₹)",
        "Tata Luxury MRP (₹)",
        "Adventuras Price (₹)",
        "Adventuras MRP (₹)",
        "Myntra Price (₹)",
        "Myntra MRP (₹)",
        "AJIO Price (₹)",
        "AJIO MRP (₹)",
    ]
    ws_sum.append(sum_headers)

    for col_idx in range(1, len(sum_headers) + 1):
        cell = ws_sum.cell(row=1, column=col_idx)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center" if col_idx not in (1, 2, 4) else "left", vertical="center", wrap_text=True)
        cell.border = BORDER_THIN
    ws_sum.row_dimensions[1].height = 28

    row_num = 2
    for fam in families:
        plats = {p.get("platform"): p for p in fam.get("platforms") or []}

        sku = fam.get("sku") or fam.get("style") or "—"
        ean = fam.get("ean") or "—"
        style = fam.get("style") or (fam.get("family_id", "").replace("STYLE_", "") if fam.get("family_id", "").startswith("STYLE_") else "—")
        title = fam.get("title") or "Columbia Product"

        row_vals = [sku, ean, style, title]

        for p_key, _ in PLATFORM_ORDER:
            p_data = plats.get(p_key) or {}
            p_price = p_data.get("price")
            p_mrp = p_data.get("mrp")
            row_vals.append(p_price if p_price is not None else "—")
            row_vals.append(p_mrp if p_mrp is not None else "—")

        ws_sum.append(row_vals)

        # Styling data row
        is_even = (row_num % 2 == 0)
        for col_idx in range(1, len(row_vals) + 1):
            c = ws_sum.cell(row=row_num, column=col_idx)
            c.border = BORDER_THIN
            c.font = Font(name="Segoe UI", size=10)
            if is_even:
                c.fill = ZEBRA_FILL
            if col_idx in (1, 2, 3):
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx >= 5:
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")
        row_num += 1

    # Auto-adjust column widths for summary sheet
    for col in ws_sum.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_sum.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    # ---------------------------------------------------------
    # 2. PER-PLATFORM SHEETS
    # ---------------------------------------------------------
    for p_key, p_name in PLATFORM_ORDER:
        ws_plat = wb.create_sheet(title=p_name[:31])
        ws_plat.views.sheetView[0].showGridLines = True

        plat_headers = [
            "EAN",
            "SKU",
            "Style",
            "Product ID / ASIN",
            "Selling Price (₹)",
            "MRP (₹)",
            "Product Title",
            "Listing URL",
            "Image URL",
            "Stock Status",
            "Total Stock Units",
            "Sizes Available",
            "Variants Count",
            "Stock Per Variant",
            "Active Offers (Codes & Discounts)"
        ]
        ws_plat.append(plat_headers)

        for col_idx in range(1, len(plat_headers) + 1):
            cell = ws_plat.cell(row=1, column=col_idx)
            cell.font = HEADER_FONT
            cell.fill = SUBHEADER_FILL
            cell.alignment = Alignment(horizontal="center" if col_idx not in (1, 2, 7) else "left", vertical="center")
            cell.border = BORDER_THIN
        ws_plat.row_dimensions[1].height = 26

        p_row_num = 2
        for fam in families:
            plats = {p.get("platform"): p for p in fam.get("platforms") or []}
            p_data = plats.get(p_key)
            if not p_data or p_data.get("price") is None:
                continue

            ean = p_data.get("ean") or fam.get("ean") or "—"
            sku = p_data.get("sku") or fam.get("sku") or fam.get("style") or "—"
            style = fam.get("style") or (fam.get("family_id", "").replace("STYLE_", "") if fam.get("family_id", "").startswith("STYLE_") else "—")
            pid = str(p_data.get("product_id") or "—")
            price = p_data.get("price")
            mrp = p_data.get("mrp") or price
            title = p_data.get("listing_title") or fam.get("title") or "Columbia Product"
            url = p_data.get("url") or ""
            img = p_data.get("image_url") or fam.get("image_url") or ""
            status = p_data.get("availability_status") or "In stock"
            sizes_text = p_data.get("sizes_summary") or "Standard"

            variants_list = p_data.get("variants") or []
            var_cnt = len(variants_list)

            # Sum total stock across variants if numeric
            total_stock_num = 0
            has_numeric_stock = False
            variant_stock_strs = []
            for v in variants_list:
                v_sz = v.get("size") or "One Size"
                v_stk = v.get("stock") if v.get("stock") is not None else v.get("quantity")
                if isinstance(v_stk, (int, float)):
                    total_stock_num += int(v_stk)
                    has_numeric_stock = True
                    variant_stock_strs.append(f"{v_sz}: {int(v_stk)}")
                elif v_stk:
                    variant_stock_strs.append(f"{v_sz}: {v_stk}")
                else:
                    v_avail = "In stock" if v.get("available") is not False else "Out of stock"
                    variant_stock_strs.append(f"{v_sz}: {v_avail}")

            if has_numeric_stock:
                total_stock_display = f"{total_stock_num} units"
            else:
                total_stock_display = p_data.get("stock_text") or status

            stock_per_variant_str = "; ".join(variant_stock_strs) if variant_stock_strs else "—"

            offers_list = p_data.get("offers") or []
            offer_strs = []
            for o in offers_list:
                if isinstance(o, dict):
                    c = o.get("code")
                    t = o.get("title") or o.get("description")
                    if c and t:
                        offer_strs.append(f"[{c}] {t}")
                    elif c:
                        offer_strs.append(f"[{c}]")
                    elif t:
                        offer_strs.append(str(t))
            offers_str = "; ".join(offer_strs) if offer_strs else "None"

            p_vals = [
                ean, sku, style, pid,
                price if price is not None else "—",
                mrp if mrp is not None else "—",
                title, url, img, status,
                total_stock_display, sizes_text, var_cnt,
                stock_per_variant_str, offers_str
            ]
            ws_plat.append(p_vals)

            is_even = (p_row_num % 2 == 0)
            for col_idx in range(1, len(p_vals) + 1):
                c = ws_plat.cell(row=p_row_num, column=col_idx)
                c.border = BORDER_THIN
                c.font = Font(name="Segoe UI", size=10)
                if is_even:
                    c.fill = ZEBRA_FILL
                if col_idx in (1, 2, 3, 4, 10, 11, 12, 13):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx in (5, 6):
                    c.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    c.alignment = Alignment(horizontal="left", vertical="center")
            p_row_num += 1

        for col in ws_plat.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_plat.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
