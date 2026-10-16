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
        "Style",
        "Product Title",
        "Category",
        "Gender",
        "Platforms Active",
        "Lowest Price (₹)",
        "Highest MRP (₹)",
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
        cell.alignment = Alignment(horizontal="center" if col_idx not in (1, 2) else "left", vertical="center", wrap_text=True)
        cell.border = BORDER_THIN
    ws_sum.row_dimensions[1].height = 28

    row_num = 2
    for fam in families:
        plats = {p.get("platform"): p for p in fam.get("platforms") or []}

        style = fam.get("style") or fam.get("sku") or "—"
        title = fam.get("title") or "Columbia Product"
        cat = fam.get("category") or "Apparel"
        gender = fam.get("gender") or "Unisex"
        plat_cnt = fam.get("platforms_count") or len([p for p in fam.get("platforms", []) if p.get("price") is not None])
        low_p = fam.get("lowest_price") or "—"
        high_mrp = fam.get("mrp") or "—"

        row_vals = [style, title, cat, gender, plat_cnt, low_p, high_mrp]

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
            if col_idx in (1, 3, 4, 5):
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx >= 6:
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
            "Style",
            "Product Title",
            "Product ID / ASIN / SKU",
            "Listing URL",
            "Image URL",
            "Selling Price (₹)",
            "MRP (₹)",
            "Stock Status",
            "Sizes Available",
            "Variants Count",
            "Active Offers & Discounts"
        ]
        ws_plat.append(plat_headers)

        for col_idx in range(1, len(plat_headers) + 1):
            cell = ws_plat.cell(row=1, column=col_idx)
            cell.font = HEADER_FONT
            cell.fill = SUBHEADER_FILL
            cell.alignment = Alignment(horizontal="center" if col_idx not in (1, 2) else "left", vertical="center")
            cell.border = BORDER_THIN
        ws_plat.row_dimensions[1].height = 26

        p_row_num = 2
        for fam in families:
            plats = {p.get("platform"): p for p in fam.get("platforms") or []}
            p_data = plats.get(p_key)
            if not p_data or p_data.get("price") is None:
                continue

            style = fam.get("style") or fam.get("sku") or "—"
            title = p_data.get("listing_title") or fam.get("title") or "Columbia Product"
            pid = str(p_data.get("product_id") or "—")
            url = p_data.get("url") or ""
            img = p_data.get("image_url") or fam.get("image_url") or ""
            price = p_data.get("price")
            mrp = p_data.get("mrp") or price
            status = p_data.get("availability_status") or "In stock"
            sizes_text = p_data.get("sizes_summary") or "Standard"
            var_cnt = len(p_data.get("variants") or [])
            offers_list = p_data.get("offers") or []
            offers_str = "; ".join(
                [str(o.get("title") or o.get("code") or "") for o in offers_list if isinstance(o, dict)]
            ) if offers_list else "None"

            p_vals = [
                style, title, pid, url, img,
                price if price is not None else "—",
                mrp if mrp is not None else "—",
                status, sizes_text, var_cnt, offers_str
            ]
            ws_plat.append(p_vals)

            is_even = (p_row_num % 2 == 0)
            for col_idx in range(1, len(p_vals) + 1):
                c = ws_plat.cell(row=p_row_num, column=col_idx)
                c.border = BORDER_THIN
                c.font = Font(name="Segoe UI", size=10)
                if is_even:
                    c.fill = ZEBRA_FILL
                if col_idx in (1, 3, 8, 9, 10):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx in (6, 7):
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
