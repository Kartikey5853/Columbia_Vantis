import os
import shutil
import subprocess
import sys
from pathlib import Path

# Configure Windows console encoding
if sys.platform.startswith("win"):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

BASE_DIR = Path(__file__).resolve().parent

def build():
    print("=" * 65)
    print("[BUILD] VANTIS LOCAL SCRAPER - PYINSTALLER BUNDLER")
    print("=" * 65)
    print(f"Working Directory: {BASE_DIR}")

    # Check if pyinstaller is installed
    try:
        import PyInstaller
        print(f"[OK] PyInstaller detected (v{PyInstaller.__version__})")
    except ImportError:
        print("[WARN] PyInstaller not found in current Python environment.")
        print("Installing pyinstaller now via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Ensure required dependencies exist
    try:
        import playwright
        import httpx
        import dotenv
        print("[OK] Core dependencies detected (playwright, httpx, python-dotenv)")
    except ImportError as e:
        print(f"[WARN] Missing dependency: {e}. Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")])

    spec_path = BASE_DIR / "scraper_bundle.spec"
    if not spec_path.exists():
        print(f"[ERROR] Spec file not found at {spec_path}")
        return

    print("\n[BUILD] Starting PyInstaller compilation...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_path),
        "--clean",
        "--noconfirm",
        f"--workpath={BASE_DIR / 'build'}",
        f"--distpath={BASE_DIR / 'dist'}",
    ]

    print(f"Command: {' '.join(cmd)}\n")
    proc = subprocess.run(cmd, cwd=str(BASE_DIR))

    if proc.returncode == 0:
        dist_dir = BASE_DIR / "dist" / "Vantis_Local_Scraper"
        dist_exe = dist_dir / "Vantis_Local_Scraper.exe"

        # Copy scrapers directory directly adjacent to the .exe
        target_scrapers = dist_dir / "scrapers"
        if target_scrapers.exists():
            shutil.rmtree(target_scrapers)
        shutil.copytree(BASE_DIR / "scrapers", target_scrapers)
        print(f"[BUILD] Copied scrapers/ directly into {target_scrapers.resolve()}")

        # Ensure persistent profile and data folders exist
        (dist_dir / "data").mkdir(parents=True, exist_ok=True)
        (dist_dir / "chrome_profile").mkdir(parents=True, exist_ok=True)

        # Copy .env template if not present
        if (BASE_DIR / ".env.example").exists() and not (dist_dir / ".env").exists():
            shutil.copy(BASE_DIR / ".env.example", dist_dir / ".env")
            print("[BUILD] Created default .env in bundle directory.")

        print("\n" + "=" * 65)
        print("[SUCCESS] BUILD COMPLETED SUCCESSFULLY!")
        print("=" * 65)
        print(f"Standalone executable: {dist_exe.resolve()}")
        print("Ready for local scraping!\n")
    else:
        print(f"\n[ERROR] Build failed with exit code {proc.returncode}. Check logs above.")

if __name__ == "__main__":
    build()
