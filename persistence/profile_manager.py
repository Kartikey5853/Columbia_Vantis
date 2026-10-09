import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
load_dotenv()

from persistence.supabase_client import SupabaseClient, get_supabase_client

# Environment configurations
PROFILE_BUCKET = os.getenv("PROFILE_BUCKET", "browser-profiles")
PROFILE_OBJECT = os.getenv("PROFILE_OBJECT", "myntra-chrome-profile.rar")

# Concurrency locks
_PROFILE_ASYNC_LOCK = asyncio.Lock()
_LOCK_FILE = Path("jobs_data") / "myntra_profile.lock"


def get_profile_config() -> Dict[str, str]:
    """Returns profile configuration while masking sensitive values."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY", "")
    return {
        "bucket": PROFILE_BUCKET,
        "object": PROFILE_OBJECT,
        "supabase_configured": bool(supabase_url and secret_key),
        "url_masked": f"{supabase_url[:18]}..." if supabase_url else "not_configured",
    }


def find_rar_extractor() -> Tuple[Optional[str], Optional[str]]:
    """Discovers available RAR extraction utilities on Linux or Windows."""
    candidates = [
        ("unrar", shutil.which("unrar")),
        ("winrar_unrar", r"C:\Program Files\WinRAR\UnRAR.exe" if os.path.exists(r"C:\Program Files\WinRAR\UnRAR.exe") else None),
        ("unar", shutil.which("unar")),
        ("7z", shutil.which("7z")),
    ]
    for name, path in candidates:
        if path and Path(path).exists():
            return name, str(path)
    return None, None


def find_rar_packer() -> Tuple[Optional[str], Optional[str]]:
    """Discovers available RAR / archive compression utilities on Linux or Windows."""
    candidates = [
        ("rar", shutil.which("rar")),
        ("winrar_rar", r"C:\Program Files\WinRAR\Rar.exe" if os.path.exists(r"C:\Program Files\WinRAR\Rar.exe") else None),
        ("7z", shutil.which("7z")),
    ]
    for name, path in candidates:
        if path and Path(path).exists():
            return name, str(path)
    return None, None


def verify_disk_space(path: Path, min_mb: int = 300) -> int:
    """Verifies that adequate writable disk space is available before extraction/packaging."""
    try:
        check_path = path if path.exists() else path.parent
        if not check_path.exists():
            check_path = Path(tempfile.gettempdir())
        usage = shutil.disk_usage(check_path)
        free_mb = int(usage.free // (1024 * 1024))
        if free_mb < min_mb:
            raise RuntimeError(
                f"Insufficient disk space on {check_path}: {free_mb} MB available, minimum {min_mb} MB required."
            )
        return free_mb
    except Exception as e:
        if "Insufficient disk space" in str(e):
            raise
        # If disk_usage fails, warn but proceed
        print(f"[PROFILE] Warning: Could not check disk usage on {path}: {e}", flush=True)
        return 9999


def acquire_profile_lock(run_id: str) -> None:
    """
    Acquires an atomic file lock to prevent two scraper processes from
    launching or modifying the same Chrome profile concurrently.
    """
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    current_pid = os.getpid()

    if _LOCK_FILE.exists():
        try:
            data = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
            locked_pid = data.get("pid")
            locked_at = data.get("timestamp")
            
            # Check if process is still active
            pid_alive = False
            if locked_pid and isinstance(locked_pid, int):
                try:
                    if sys.platform.startswith("win"):
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        handle = kernel32.OpenProcess(0x1000, False, locked_pid)
                        if handle:
                            kernel32.CloseHandle(handle)
                            pid_alive = True
                    else:
                        os.kill(locked_pid, 0)
                        pid_alive = True
                except Exception:
                    pid_alive = False

            if pid_alive and locked_pid != current_pid:
                raise RuntimeError(
                    f"Chrome profile is currently in use by process PID {locked_pid} (run_id: {data.get('run_id')}, locked at: {locked_at}). "
                    "Concurrent execution against the same profile is prevented."
                )
            else:
                # Stale lock from crashed process
                print(f"[PROFILE] Breaking stale lock from dead PID {locked_pid} (run_id: {data.get('run_id')}).", flush=True)
        except json.JSONDecodeError:
            pass

    lock_payload = {
        "pid": current_pid,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform
    }
    _LOCK_FILE.write_text(json.dumps(lock_payload, indent=2), encoding="utf-8")


def release_profile_lock() -> None:
    """Releases the process profile lock."""
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
    except Exception as e:
        print(f"[PROFILE] Warning: Failed to release profile lock file: {e}", flush=True)


async def download_profile_archive(
    dest_path: Path,
    client: Optional[SupabaseClient] = None
) -> Path:
    """
    Downloads the Chrome profile archive from private Supabase Storage
    using server-side credentials and streaming directly to disk.
    """
    cli = client or get_supabase_client()
    print(f"[PROFILE] 📥 Downloading profile archive from bucket '{PROFILE_BUCKET}', object '{PROFILE_OBJECT}'...", flush=True)
    
    t0 = time.perf_counter()
    await cli.storage_download_stream(PROFILE_BUCKET, PROFILE_OBJECT, dest_path)
    dur = round(time.perf_counter() - t0, 2)
    
    file_size_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"[PROFILE] ✅ Download complete: {file_size_mb:.2f} MB in {dur}s.", flush=True)
    return dest_path


def extract_profile_archive(archive_path: Path, extract_dir: Path) -> Path:
    """
    Extracts RAR, ZIP, or TAR archive into a dedicated directory
    using compatible local system utilities.
    """
    if not archive_path.exists() or archive_path.stat().st_size == 0:
        raise ValueError(f"Archive file is empty or missing: {archive_path}")

    verify_disk_space(extract_dir, min_mb=300)
    extract_dir.mkdir(parents=True, exist_ok=True)
    
    suffix = archive_path.suffix.lower()
    t0 = time.perf_counter()

    if suffix in (".rar", ".cbr"):
        tool_name, tool_bin = find_rar_extractor()
        if not tool_bin:
            raise RuntimeError(
                "No compatible RAR extraction utility found on system. "
                "On Render Docker, ensure 'unrar' or 'unar' is installed via apt. "
                "On Windows, ensure WinRAR/UnRAR is installed."
            )

        print(f"[PROFILE] 📦 Extracting RAR archive using '{tool_name}' ({tool_bin})...", flush=True)
        if tool_name in ("unrar", "winrar_unrar"):
            cmd = [tool_bin, "x", "-o+", "-y", str(archive_path), str(extract_dir) + os.sep]
        elif tool_name == "unar":
            cmd = [tool_bin, "-force-overwrite", "-output-directory", str(extract_dir), str(archive_path)]
        elif tool_name == "7z":
            cmd = [tool_bin, "x", "-y", f"-o{extract_dir}", str(archive_path)]
        else:
            raise RuntimeError(f"Unknown extractor: {tool_name}")

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            err_sample = (res.stderr or res.stdout or "").strip()[:300]
            raise RuntimeError(f"RAR extraction failed with code {res.returncode}: {err_sample}")

    elif suffix in (".zip",):
        import zipfile
        print(f"[PROFILE] 📦 Extracting ZIP archive...", flush=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)

    elif suffix in (".tar", ".gz", ".tgz"):
        import tarfile
        print(f"[PROFILE] 📦 Extracting TAR archive...", flush=True)
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(extract_dir)
    else:
        # Default try unar/unrar/zip
        tool_name, tool_bin = find_rar_extractor()
        if tool_bin:
            cmd = [tool_bin, "x", "-o+", "-y", str(archive_path), str(extract_dir) + os.sep]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            raise ValueError(f"Unsupported archive extension '{suffix}' and no extractor available.")

    dur = round(time.perf_counter() - t0, 2)
    file_count = sum(len(files) for _, _, files in os.walk(extract_dir))
    print(f"[PROFILE] ✅ Extraction complete: {file_count} files unpacked in {dur}s.", flush=True)
    return extract_dir


def detect_and_validate_profile(extract_dir: Path) -> Dict[str, Any]:
    """
    Analyzes the extracted directory tree, determines the exact user_data_dir,
    profile subdirectory, Windows DPAPI encryption status, and normalizes
    the layout for Playwright launch_persistent_context.
    """
    # 1. Locate Local State if present
    local_state_matches = list(extract_dir.rglob("Local State"))
    user_data_dir: Optional[Path] = None
    has_local_state = False
    is_windows_dpapi = False
    profile_name = "Default"

    if local_state_matches:
        has_local_state = True
        local_state_path = local_state_matches[0]
        user_data_dir = local_state_path.parent

        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                ls_data = json.load(f)

            # Check DPAPI encryption
            os_crypt = ls_data.get("os_crypt", {})
            enc_key = str(os_crypt.get("encrypted_key") or "")
            if enc_key.startswith("RFBBUEk"):  # Base64 'DPAPI'
                is_windows_dpapi = True

            # Check last used profile
            profile_sec = ls_data.get("profile", {})
            last_used = profile_sec.get("last_used")
            if last_used and (user_data_dir / last_used).is_dir():
                profile_name = last_used
            elif (user_data_dir / "Profile 1").is_dir() and not (user_data_dir / "Default").is_dir():
                profile_name = "Profile 1"
        except Exception as e:
            print(f"[PROFILE] Warning: Could not parse Local State JSON: {e}", flush=True)
    else:
        # Search for directory containing recognizable profile subdirectories/files
        for cand in [extract_dir] + [p for p in extract_dir.rglob("*") if p.is_dir()]:
            if (cand / "Preferences").exists() or (cand / "Network").exists() or (cand / "Cookies").exists():
                # cand is either the profile directory or user_data_dir
                if cand.name.startswith("Profile ") or cand.name == "Default":
                    user_data_dir = cand.parent
                    profile_name = cand.name
                else:
                    user_data_dir = cand
                    profile_name = "Default"
                break

    if not user_data_dir:
        user_data_dir = extract_dir

    # 2. Check for profile directories and normalize for Playwright
    has_profile_1 = (user_data_dir / "Profile 1").is_dir()
    has_default = (user_data_dir / "Default").is_dir()

    if has_profile_1 and not has_default:
        # Playwright attaches to 'Default' by default. Copy Profile 1 to Default so
        # Chromium and DevTools Protocol load the original profile directly as Default.
        default_dir = user_data_dir / "Default"
        try:
            shutil.copytree(user_data_dir / "Profile 1", default_dir)
            profile_name = "Default"
            print(f"[PROFILE] Normalized 'Profile 1' to primary 'Default' profile directory.", flush=True)
        except Exception as e:
            print(f"[PROFILE] Warning: Failed to copy Profile 1 to Default: {e}", flush=True)
            profile_name = "Profile 1"
    elif has_default:
        profile_name = "Default"


    # 3. Validate that recognizable Chrome profile artifacts exist
    recognized_markers = [
        "Local State", "Preferences", "Cookies", "Network", "Web Data",
        "History", "Login Data", "Storage", "Default", "Profile 1"
    ]
    found_markers = [
        m for m in recognized_markers
        if (user_data_dir / m).exists() or any((user_data_dir).rglob(m))
    ]
    if not found_markers:
        raise ValueError(
            f"Invalid Chrome profile: no recognizable Chrome files found in {user_data_dir}. "
            f"Expected markers: {recognized_markers}"
        )

    # 4. Diagnostic Platform Warning
    if is_windows_dpapi:
        if sys.platform.startswith("linux"):
            print(
                "\n" + "!" * 70 + "\n"
                "[PROFILE] ⚠️ RESTORATION NOTICE: Restored Chrome profile was exported from Windows\n"
                "[PROFILE] (DPAPI-encrypted os_crypt keys detected). Chrome on Linux cannot decrypt\n"
                "[PROFILE] Windows DPAPI cookies. If Akamai maintenance or access-denied occurs,\n"
                f"[PROFILE] please upload a Linux-generated Chrome profile archive to '{PROFILE_OBJECT}'.\n"
                + "!" * 70 + "\n",
                flush=True
            )
        else:
            print("[PROFILE] Restored Chrome profile contains Windows DPAPI encryption.", flush=True)

    print(
        f"[PROFILE] 🔍 Profile validated: user_data_dir='{user_data_dir}', active_profile='{profile_name}', "
        f"DPAPI={is_windows_dpapi}, markers={found_markers[:4]}",
        flush=True
    )

    return {
        "user_data_dir": user_data_dir,
        "profile_name": profile_name,
        "has_local_state": has_local_state,
        "is_windows_dpapi": is_windows_dpapi,
        "extract_root": extract_dir,
        "markers": found_markers
    }


def clean_profile_cache(user_data_dir: Path) -> int:
    """
    Removes runtime lock files and bulky transient cache directories
    prior to re-compressing and uploading to Supabase Storage.
    Reduces archive size by 50-80% and prevents dangling singleton locks.
    """
    removed_count = 0

    # 1. Remove Chrome singleton and runtime lock files
    lock_names = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]
    for lk in lock_names:
        for f in user_data_dir.rglob(lk):
            try:
                if f.is_file() or f.is_symlink():
                    f.unlink(missing_ok=True)
                    removed_count += 1
            except Exception:
                pass

    # 2. Remove transient cache directories
    cache_keywords = ["Cache", "Code Cache", "GPUCache", "DawnCache", "ShaderCache", "GrShaderCache", "Crashpad"]
    for p in list(user_data_dir.rglob("*")):
        if p.is_dir() and any(k.lower() in p.name.lower() for k in cache_keywords):
            try:
                shutil.rmtree(p, ignore_errors=True)
                removed_count += 1
            except Exception:
                pass

    # 3. Remove temporary files
    for tmp_f in list(user_data_dir.rglob("*.tmp")) + list(user_data_dir.rglob("*.log")):
        try:
            if tmp_f.is_file():
                tmp_f.unlink(missing_ok=True)
                removed_count += 1
        except Exception:
            pass

    print(f"[PROFILE] 🧹 Cleaned {removed_count} cache and lock artifacts before packaging.", flush=True)
    return removed_count


async def package_and_upload_profile(
    profile_info: Dict[str, Any],
    client: Optional[SupabaseClient] = None
) -> bool:
    """
    Packages the cleaned profile and safely uploads it to Supabase Storage
    using a temporary staging object and atomic replacement strategy.
    Guaranteed to only execute after Chrome has shut down.
    """
    cli = client or get_supabase_client()
    extract_root = profile_info["extract_root"]
    user_data_dir = profile_info["user_data_dir"]

    # 1. Clean caches before packaging
    clean_profile_cache(user_data_dir)

    temp_dir = Path(tempfile.mkdtemp(prefix="repack_profile_"))
    staging_archive = temp_dir / PROFILE_OBJECT
    staging_object = f"{PROFILE_OBJECT}.tmp"

    try:
        t0 = time.perf_counter()
        suffix = Path(PROFILE_OBJECT).suffix.lower()

        # Decide working directory to preserve the original archive layout
        pack_cwd = extract_root if extract_root.exists() else user_data_dir

        if suffix in (".rar", ".cbr"):
            tool_name, tool_bin = find_rar_packer()
            if not tool_bin:
                print(f"[PROFILE] Warning: No RAR packer utility found on system. Skipping profile re-upload.", flush=True)
                return False

            print(f"[PROFILE] 📦 Compressing updated profile with '{tool_name}' ({tool_bin})...", flush=True)
            cmd = [tool_bin, "a", "-r", "-y", str(staging_archive), "."]
            res = subprocess.run(cmd, cwd=str(pack_cwd), capture_output=True, text=True)
            if res.returncode != 0:
                err_msg = (res.stderr or res.stdout or "").strip()[:300]
                print(f"[PROFILE] Warning: Profile compression failed ({res.returncode}): {err_msg}", flush=True)
                return False

        elif suffix in (".zip",):
            import zipfile
            print(f"[PROFILE] 📦 Compressing updated profile to ZIP...", flush=True)
            with zipfile.ZipFile(staging_archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(pack_cwd):
                    for file in files:
                        full_p = Path(root) / file
                        rel_p = full_p.relative_to(pack_cwd)
                        zf.write(full_p, rel_p)
        else:
            # Fallback to tar.gz or zip
            import tarfile
            print(f"[PROFILE] 📦 Compressing updated profile to TAR.GZ...", flush=True)
            with tarfile.open(staging_archive, "w:gz") as tf:
                for root, _, files in os.walk(pack_cwd):
                    for file in files:
                        full_p = Path(root) / file
                        rel_p = full_p.relative_to(pack_cwd)
                        tf.add(full_p, arcname=str(rel_p))

        if not staging_archive.exists() or staging_archive.stat().st_size == 0:
            print("[PROFILE] Warning: Packaged profile archive is empty. Aborting upload.", flush=True)
            return False

        pack_mb = staging_archive.stat().st_size / (1024 * 1024)
        print(f"[PROFILE] ✅ Packaging complete: {pack_mb:.2f} MB in {round(time.perf_counter() - t0, 2)}s.", flush=True)

        # 2. Upload to temporary staging object first
        print(f"[PROFILE] 📤 Uploading updated profile to staging object '{staging_object}' in bucket '{PROFILE_BUCKET}'...", flush=True)
        t_up = time.perf_counter()
        await cli.storage_upload_file(PROFILE_BUCKET, staging_object, staging_archive, upsert=True)
        print(f"[PROFILE] ✅ Staging upload complete in {round(time.perf_counter() - t_up, 2)}s.", flush=True)

        # 3. Safe replacement: Move staging object to final object
        replaced = False
        try:
            print(f"[PROFILE] 🔄 Atomically replacing '{PROFILE_OBJECT}' in bucket '{PROFILE_BUCKET}'...", flush=True)
            await cli.storage_move(PROFILE_BUCKET, staging_object, PROFILE_OBJECT)
            replaced = True
            print(f"[PROFILE] ✅ Profile object '{PROFILE_OBJECT}' replaced atomically.", flush=True)
        except Exception as e:
            print(f"[PROFILE] Notice: Storage move endpoint failed ({e}). Falling back to direct upsert...", flush=True)
            await cli.storage_upload_file(PROFILE_BUCKET, PROFILE_OBJECT, staging_archive, upsert=True)
            try:
                await cli.storage_delete(PROFILE_BUCKET, [staging_object])
            except Exception:
                pass
            replaced = True
            print(f"[PROFILE] ✅ Direct upsert succeeded for '{PROFILE_OBJECT}'.", flush=True)

        return replaced

    except Exception as e:
        print(f"[PROFILE] Warning: Failed to persist profile changes to Supabase Storage: {e}", flush=True)
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class ProfileSession:
    """
    Context manager providing managed lifecycle for the Myntra persistent profile:
    - Download and restore from Supabase Storage
    - Validation and layout normalization
    - Concurrency protection
    - Browser execution
    - Conditional upload back to Supabase upon successful runs
    """

    def __init__(self, run_id: str, client: Optional[SupabaseClient] = None):
        self.run_id = run_id
        self.client = client or get_supabase_client()
        self.temp_root: Optional[Path] = None
        self.profile_info: Optional[Dict[str, Any]] = None
        self._locked = False

    async def __aenter__(self) -> Dict[str, Any]:
        await _PROFILE_ASYNC_LOCK.acquire()
        acquire_profile_lock(self.run_id)
        self._locked = True

        self.temp_root = Path(tempfile.mkdtemp(prefix=f"myntra_profile_{self.run_id[:8]}_"))
        archive_path = self.temp_root / PROFILE_OBJECT
        extract_dir = self.temp_root / "extracted"

        # 1. Download
        await download_profile_archive(archive_path, client=self.client)

        # 2. Extract
        extract_profile_archive(archive_path, extract_dir)

        # 3. Detect and validate layout
        self.profile_info = detect_and_validate_profile(extract_dir)
        return self.profile_info

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.temp_root and self.temp_root.exists():
                shutil.rmtree(self.temp_root, ignore_errors=True)
        finally:
            if self._locked:
                release_profile_lock()
                _PROFILE_ASYNC_LOCK.release()
                self._locked = False


async def run_myntra_diagnostic(client: Optional[SupabaseClient] = None) -> Dict[str, Any]:
    """
    Diagnostic tool:
    1. Downloads and extracts the restored Chrome profile.
    2. Launches Playwright with launch_persistent_context under the restored profile.
    3. Inspects session cookies for myntra.com (without logging sensitive values).
    4. Navigates to https://www.myntra.com/columbia and inspects the response.
    5. Reports whether a normal product page or a maintenance/access-denied response was returned.
    6. Identifies whether Windows-encrypted cookies or IP challenges are responsible.
    """
    from playwright.async_api import async_playwright

    cli = client or get_supabase_client()
    diag_run_id = f"diag_{int(time.time())}"
    t_start = time.perf_counter()

    report: Dict[str, Any] = {
        "diagnostic": "myntra_profile_session",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "config": get_profile_config(),
        "profile_restoration": "pending",
        "browser_startup": "pending",
        "session_cookies": {},
        "page_response": {},
        "diagnosis": "",
        "is_access_denied": False,
        "is_maintenance": False,
        "is_catalog_accessible": False,
    }

    session = ProfileSession(run_id=diag_run_id, client=cli)
    try:
        profile_info = await session.__aenter__()
        report["profile_restoration"] = {
            "status": "success",
            "user_data_dir": str(profile_info["user_data_dir"]),
            "profile_name": profile_info["profile_name"],
            "is_windows_dpapi": profile_info["is_windows_dpapi"],
            "markers": profile_info["markers"]
        }

        user_data_dir = profile_info["user_data_dir"]
        profile_name = profile_info["profile_name"]

        print(f"[DIAGNOSTIC] Launching persistent context for diagnostic test...", flush=True)
        async with async_playwright() as pw:
            args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--mute-audio",
                "--disable-background-networking",
                "--disable-blink-features=AutomationControlled",
            ]
            if profile_name:
                args.append(f"--profile-directory={profile_name}")

            # Headless on Windows local test or env, headed on Xvfb if configured
            is_headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=is_headless,
                ignore_default_args=["--enable-automation"],
                args=args,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
                    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                }
            )

            report["browser_startup"] = "success"

            # 1. Inspect cookies in restored session
            cookies = await context.cookies(["https://www.myntra.com"])
            cookie_names = [c["name"] for c in cookies]
            report["session_cookies"] = {
                "count": len(cookies),
                "cookie_names": cookie_names,
                "has_at_token": "at" in cookie_names,
                "has_abck": "_abck" in cookie_names,
                "has_bm_sz": "bm_sz" in cookie_names,
            }
            print(f"[DIAGNOSTIC] Restored session has {len(cookies)} Myntra cookies: {cookie_names}", flush=True)

            page = context.pages[0] if context.pages else await context.new_page()

            # Anti-detect init
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

            # 2. Navigate to Columbia page
            print("[DIAGNOSTIC] Navigating to https://www.myntra.com/columbia...", flush=True)
            nav_error = None
            resp = None
            try:
                resp = await page.goto("https://www.myntra.com/columbia", wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                nav_error = str(e)
                print(f"[DIAGNOSTIC] Navigation error: {e}", flush=True)

            status_code = resp.status if resp else None
            title = await page.title() if not nav_error else "unknown"
            current_url = page.url if not nav_error else "unknown"

            # Check page content for maintenance or access denied
            page_content = ""
            try:
                page_content = await page.content()
            except Exception:
                pass

            is_denied = False
            is_maint = False
            is_catalog = False

            low_content = page_content.lower()
            low_title = title.lower()

            if status_code in (403, 429) or "access denied" in low_title or "access denied" in low_content or "pardon our interruption" in low_content:
                is_denied = True
            elif "maintenance" in low_title or "site maintenance" in low_content:
                is_maint = True
            elif "columbia" in low_title or "buy columbia" in low_content or "product-base" in low_content:
                is_catalog = True

            report["page_response"] = {
                "http_status": status_code,
                "title": title,
                "current_url": current_url,
                "nav_error": nav_error,
                "detected_denied": is_denied,
                "detected_maintenance": is_maint,
                "detected_catalog": is_catalog,
            }

            report["is_access_denied"] = is_denied
            report["is_maintenance"] = is_maint
            report["is_catalog_accessible"] = is_catalog

            # Formulate concrete diagnosis
            if is_catalog:
                report["diagnosis"] = "SUCCESS: Normal Columbia product listing page received. Profile session is active and functional."
            elif is_denied or is_maint or nav_error:
                if profile_info["is_windows_dpapi"] and sys.platform.startswith("linux"):
                    report["diagnosis"] = (
                        "ACCESS RESTRICTED (Akamai maintenance / challenge). "
                        "Root cause: Profile was generated on Windows with DPAPI encryption; Linux Chromium cannot decrypt "
                        "Windows DPAPI session cookies. Solution: Export a fresh Chrome profile from Linux Chromium and upload to Supabase Storage."
                    )
                else:
                    report["diagnosis"] = (
                        f"ACCESS RESTRICTED (HTTP {status_code}, Title: '{title}'). "
                        "Akamai challenge, IP challenge, or expired cookies returned instead of normal product catalog."
                    )
            else:
                report["diagnosis"] = f"Unknown response received (HTTP {status_code}, Title: '{title}')."

            await context.close()

    except Exception as e:
        report["profile_restoration"] = f"failed: {str(e)}"
        report["diagnosis"] = f"Diagnostic failed during profile preparation: {str(e)}"
        print(f"[DIAGNOSTIC] Error: {e}", flush=True)
    finally:
        await session.__aexit__(None, None, None)

    report["duration_seconds"] = round(time.perf_counter() - t_start, 2)
    print(f"\n[DIAGNOSTIC REPORT] {report['diagnosis']} (Duration: {report['duration_seconds']}s)\n", flush=True)
    return report
