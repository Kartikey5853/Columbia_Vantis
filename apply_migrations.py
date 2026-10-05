import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

MIGRATION_FILE = Path(__file__).parent / "migrations" / "001_initial_schema.sql"


def check_tables_via_rest(supabase_url: str, supabase_key: str) -> dict:
    """Check existence of tables via Supabase PostgREST API."""
    tables = [
        "scrapers",
        "products",
        "price_history",
        "scrape_runs",
        "scrape_listing_pages",
        "scrape_product_progress",
    ]
    results = {}
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}

    with httpx.Client(timeout=10.0) as client:
        for t in tables:
            try:
                res = client.get(f"{supabase_url}/rest/v1/{t}?select=count", headers=headers)
                results[t] = res.status_code != 404
            except Exception as e:
                results[t] = False
    return results


def run_migration():
    print("=" * 60)
    print("Supabase Schema Migration Tool")
    print("=" * 60)

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY")
    db_url = os.getenv("DATABASE_URL")

    if not supabase_url or not supabase_key:
        print("[ERROR] SUPABASE_URL and SUPABASE_KEY/SUPABASE_SECRET_KEY must be set in .env")
        sys.exit(1)

    if not MIGRATION_FILE.exists():
        print(f"[ERROR] Migration file not found: {MIGRATION_FILE}")
        sys.exit(1)

    sql_content = MIGRATION_FILE.read_text(encoding="utf-8")

    # If direct DATABASE_URL is provided, attempt direct postgres execution
    if db_url:
        print("Attempting direct PostgreSQL migration execution via DATABASE_URL...")
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(sql_content)
            conn.close()
            print("[SUCCESS] Executed migration directly against PostgreSQL database!")
        except ImportError:
            print("psycopg2 not installed; attempting via other driver or REST verification...")
        except Exception as e:
            print(f"[WARNING] Direct PostgreSQL execution failed: {e}")

    # Verify tables via REST
    status = check_tables_via_rest(supabase_url, supabase_key)
    missing = [t for t, exists in status.items() if not exists]

    if not missing:
        print("[SUCCESS] All required tables are present and active in Supabase:")
        for t in status:
            print(f"   ✓ {t}")
        print("\nDatabase is fully migrated and ready!")
        return True
    else:
        print(f"[INFO] Tables not yet detected in Supabase REST API: {', '.join(missing)}")
        print("\n" + "=" * 60)
        print("ACTION REQUIRED: Execute the migration in Supabase SQL Editor")
        print("=" * 60)
        print("1. Open your Supabase Dashboard: https://supabase.com/dashboard/project/_/sql")
        print("2. Navigate to 'SQL Editor'")
        print(f"3. Copy the contents of: {MIGRATION_FILE.resolve()}")
        print("4. Paste into the SQL editor and click 'RUN'.")
        print("5. Re-run this script: python apply_migrations.py")
        print("=" * 60 + "\n")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
