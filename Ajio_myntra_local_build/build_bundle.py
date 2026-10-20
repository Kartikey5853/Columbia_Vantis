import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def build():
    print("=" * 65)
    print("📦 VANTIS LOCAL SCRAPER - PYINSTALLER BUNDLER")
    print("=" * 65)
    print(f"Working Directory: {BASE_DIR}")

    # Check if pyinstaller is installed
    try:
        import PyInstaller
        print(f"✅ PyInstaller is detected (v{PyInstaller.__version__})")
    except ImportError:
        print("⚠️ PyInstaller not found in current Python environment.")
        print("Installing pyinstaller now via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Ensure required dependencies exist
    try:
        import playwright
        import httpx
        import dotenv
        print("✅ Core dependencies detected (playwright, httpx, python-dotenv)")
    except ImportError as e:
        print(f"⚠️ Missing dependency: {e}. Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")])

    spec_path = BASE_DIR / "scraper_bundle.spec"
    if not spec_path.exists():
        print(f"❌ Error: Spec file not found at {spec_path}")
        return

    print("\n🔨 Starting PyInstaller build process...")
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
        dist_exe = BASE_DIR / "dist" / "Vantis_Local_Scraper" / "Vantis_Local_Scraper.exe"
        print("\n" + "=" * 65)
        print("🎉 BUILD COMPLETED SUCCESSFULLY!")
        print("=" * 65)
        print(f"Executable output: {dist_exe.resolve()}")
        print("\nYou can now run the standalone executable directly or distribute the 'dist/Vantis_Local_Scraper' folder.")
    else:
        print(f"\n❌ Build failed with exit code {proc.returncode}. Check logs above.")

if __name__ == "__main__":
    build()
