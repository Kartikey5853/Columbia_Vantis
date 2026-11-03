import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Auth secret
SECRET_KEY = os.getenv("JWT_SECRET", "vantis-columbia-secret-token-key-2026")
TOKEN_EXPIRY_HOURS = 24

# Data directories
NEW_DATA_DIR = BASE_DIR / "new_data"
DATA_DIR = BASE_DIR / "data"
AMAZON_DATA_DIR = BASE_DIR / "amazon_v4" / "data" / "amazon"
JOBS_DATA_DIR = BASE_DIR / "jobs_data"
MASTER_DATA_DIR = BASE_DIR / "master_data_uploads"
MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Supabase URL & keys
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
)
