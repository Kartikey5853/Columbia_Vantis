import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from persistence.product_store import get_all_canonical_products
from persistence.supabase_client import get_supabase_client, SupabaseClient

DATA_DIR = Path("data")


def validate_export_payload(payload: Dict[str, Any]) -> bool:
    """Validates that the export payload adheres to expected structure and is not empty/corrupted."""
    if not isinstance(payload, dict):
        return False
    if "source" not in payload or "products" not in payload:
        return False
    if not isinstance(payload["products"], list):
        return False
    return True


async def export_canonical_backup(
    scraper_name: str,
    client: Optional[SupabaseClient] = None
) -> Path:
    """
    Pulls canonical product state from Supabase and atomically writes to rolling local backup:
    1. Pulls canonical product state from Supabase.
    2. Builds JSON payload.
    3. Validates the generated JSON structure.
    4. Copies existing valid JSON to .backup.json.
    5. Writes new data to a temporary file.
    6. Validates the temporary file.
    7. Atomically replaces the main JSON file.
    """
    cli = client or get_supabase_client()
    norm_name = scraper_name.strip().lower()
    source_folder = DATA_DIR / norm_name
    source_folder.mkdir(parents=True, exist_ok=True)

    main_file = source_folder / f"{norm_name}_data.json"
    backup_file = source_folder / f"{norm_name}_data.backup.json"
    temp_file = source_folder / f"{norm_name}_data.tmp.json"

    # 1. Pull canonical products from Supabase
    products = await get_all_canonical_products(norm_name, cli)

    # 2. Build payload
    payload = {
        "schema_version": 1,
        "source": norm_name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_products": len(products),
        "products": products
    }

    # 3. Validate generated payload
    if not validate_export_payload(payload):
        raise ValueError(f"Invalid export payload generated for {norm_name}")

    # 4. If existing valid file exists, copy to rolling .backup.json
    if main_file.exists():
        try:
            if main_file.stat().st_size > 100:
                shutil.copy2(main_file, backup_file)
        except Exception as e:
            print(f"[EXPORTER] Warning: existing main file could not be backed up: {e}", flush=True)

    # 5. Write new data directly to temporary file (streamed, low RAM)
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # 6. Validate written temporary file
    if not temp_file.exists() or temp_file.stat().st_size < 100:
        if temp_file.exists():
            temp_file.unlink()
        raise RuntimeError("Export validation failed: temporary file is empty or corrupted")

    # 7. Atomically replace main file
    if os.name == "nt":
        # Windows replace handles atomic overwrite if supported or safe rename
        if main_file.exists():
            temp_backup = source_folder / f"{norm_name}_data.old.tmp"
            try:
                os.replace(main_file, temp_backup)
                os.replace(temp_file, main_file)
                if temp_backup.exists():
                    temp_backup.unlink()
            except Exception:
                if temp_backup.exists() and not main_file.exists():
                    os.replace(temp_backup, main_file)
                raise
        else:
            os.replace(temp_file, main_file)
    else:
        os.replace(temp_file, main_file)

    num_prods = len(products)
    del products
    del payload
    import gc
    gc.collect()

    print(f"[EXPORTER] Atomically exported {num_prods} {norm_name} products to {main_file.resolve()}", flush=True)
    return main_file
