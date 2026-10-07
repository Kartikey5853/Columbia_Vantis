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

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def check_tables_via_rest(supabase_url: str, supabase_key: str) -> dict:
    """Check existence of tables and report column via Supabase PostgREST API."""
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
            except Exception:
                results[t] = False

        # Check optional report column on scrape_runs
        try:
            res_rep = client.get(f"{supabase_url}/rest/v1/scrape_runs?select=report&limit=1", headers=headers)
            results["scrape_runs.report"] = res_rep.status_code == 200
        except Exception:
            results["scrape_runs.report"] = False

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

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"[ERROR] No migration files found in: {MIGRATIONS_DIR}")
        sys.exit(1)

    combined_sql = "\n\n".join(f.read_text(encoding="utf-8") for f in migration_files)

    # If direct DATABASE_URL is provided, attempt direct postgres execution
    if db_url:
        print("Attempting direct PostgreSQL migration execution via DATABASE_URL...")
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(combined_sql)
            conn.close()
            print("[SUCCESS] Executed migrations directly against PostgreSQL database!")
        except ImportError:
            print("psycopg2 not installed; attempting via other driver or REST verification...")
        except Exception as e:
            print(f"[WARNING] Direct PostgreSQL execution failed: {e}")

    # Verify tables via REST
    status = check_tables_via_rest(supabase_url, supabase_key)
    missing = [t for t, exists in status.items() if not exists and not t.endswith(".report")]

    print("\nDatabase Schema Status:")
    for t, exists in status.items():
        icon = "✓" if exists else ("⚠️ (optional, fallback active)" if t.endswith(".report") else "✗")
        print(f"   {icon} {t}")

    if not missing:
        print("\n[SUCCESS] Core tables are present and active in Supabase!")
        if not status.get("scrape_runs.report"):
            print("[NOTE] To enable native JSONB reports, run 002_add_report_to_scrape_runs.sql in Supabase SQL editor.")
            print("       (Automatic JSON fallback to last_error is currently active and fully supported).")
        return True
    else:
        print(f"\n[INFO] Missing core tables in Supabase REST API: {', '.join(missing)}")
        print("\n" + "=" * 60)
        print("ACTION REQUIRED: Execute migrations in Supabase SQL Editor")
        print("=" * 60)
        print("1. Open your Supabase Dashboard: https://supabase.com/dashboard/project/_/sql")
        print("2. Navigate to 'SQL Editor'")
        for mf in migration_files:
            print(f"3. Run contents of: {mf.resolve()}")
        print("4. Re-run this script: python apply_migrations.py")
        print("=" * 60 + "\n")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
