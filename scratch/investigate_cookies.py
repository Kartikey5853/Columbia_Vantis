"""
Diagnostic script for inspecting the restored Chrome profile cookie database.
Run with: python scratch/investigate_cookies.py
"""
import asyncio
import os
import sys
import tempfile
import shutil
import subprocess
import sqlite3
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

url = os.getenv("SUPABASE_URL", "").rstrip("/")
key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY", "")
bucket = os.getenv("PROFILE_BUCKET", "browser-profiles")
obj = os.getenv("PROFILE_OBJECT", "myntra-chrome-profile.rar")

headers = {"apikey": key, "Authorization": f"Bearer {key}"}

temp_dir = Path(tempfile.mkdtemp(prefix="investigate_profile_"))
archive_file = temp_dir / obj
extract_dir = temp_dir / "extracted"
extract_dir.mkdir(parents=True, exist_ok=True)

try:
    print("=" * 60)
    print("STEP 1: Inspect archive directory structure & cookie DB presence")
    print("=" * 60)
    print(f"Downloading {bucket}/{obj} from Supabase Storage...")
    with httpx.stream("GET", f"{url}/storage/v1/object/{bucket}/{obj}", headers=headers) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"Download failed: HTTP {r.status_code}")
        with open(archive_file, "wb") as f:
            for chunk in r.iter_bytes(65536):
                f.write(chunk)
    print(f"Archive downloaded ({archive_file.stat().st_size / (1024*1024):.2f} MB)")

    # Extract
    extractor = shutil.which("unrar") or r"C:\Program Files\WinRAR\UnRAR.exe" or shutil.which("unar")
    subprocess.run([extractor, "x", "-o+", "-y", str(archive_file), str(extract_dir) + os.sep], capture_output=True, check=True)

    cookie_files = list(extract_dir.rglob("Cookies"))
    print(f"\nDiscovered {len(cookie_files)} 'Cookies' file(s) in archive:")
    for cf in cookie_files:
        rel = cf.relative_to(extract_dir)
        size = cf.stat().st_size
        print(f"  Path: {rel} | Size: {size} bytes ({size / 1024:.1f} KB)")

    target_cookie_db = cookie_files[0]

    print("\n" + "=" * 60)
    print(f"STEP 2: Read-only SQLite inspection of {target_cookie_db.relative_to(extract_dir)}")
    print("=" * 60)
    uri = f"file:{target_cookie_db.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM cookies")
    total_cookies = cursor.fetchone()[0]
    print(f"Total cookies in database: {total_cookies}")

    cursor.execute("SELECT host_key, COUNT(*) FROM cookies GROUP BY host_key ORDER BY COUNT(*) DESC")
    domain_counts = cursor.fetchall()
    print(f"\nCookie counts grouped by domain ({len(domain_counts)} domains):")
    for domain, count in domain_counts:
        print(f"  {domain:<35} : {count} cookies")

    cursor.execute("""
        SELECT host_key, name, 
               length(value) as val_len, 
               length(encrypted_value) as enc_len, 
               hex(substr(encrypted_value, 1, 3)) as sig
        FROM cookies 
        WHERE host_key LIKE '%myntra%'
        LIMIT 5
    """)
    sample_enc = cursor.fetchall()
    print("\nMyntra cookie storage characteristics (NO values printed):")
    for host, name, v_len, enc_len, sig in sample_enc:
        sig_str = bytes.fromhex(sig).decode("latin1", errors="replace") if sig else "none"
        print(f"  Cookie: {name:<20} | Plaintext len: {v_len} | Encrypted len: {enc_len} | Header: {sig} ('{sig_str}')")

    conn.close()

    print("\n" + "=" * 60)
    print("STEP 3 & 4: User Data Directory, Profile Directory & Playwright Context")
    print("=" * 60)
    local_state_matches = list(extract_dir.rglob("Local State"))
    user_data_dir = local_state_matches[0].parent
    print(f"Detected user_data_dir: {user_data_dir}")

    with open(local_state_matches[0], "r", encoding="utf-8") as f:
        ls = json.load(f)
    os_crypt = ls.get("os_crypt", {})
    enc_key = os_crypt.get("encrypted_key", "")
    print(f"os_crypt encrypted_key starts with DPAPI prefix ('RFBBUEk'): {enc_key.startswith('RFBBUEk')}")

    async def run_browser_check():
        async with async_playwright() as pw:
            args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--profile-directory=Default",
            ]
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True,
                args=args
            )
            all_cookies = await ctx.cookies()
            print(f"\nTotal cookies reported by Playwright context: {len(all_cookies)}")
            await ctx.close()

    asyncio.run(run_browser_check())

finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\nInvestigation temporary directory cleaned up.")
