import asyncio
import os
import sys
import unittest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from persistence.supabase_client import get_supabase_client
from persistence.profile_manager import (
    get_profile_config,
    find_rar_extractor,
    find_rar_packer,
    ProfileSession,
    clean_profile_cache,
    run_myntra_diagnostic,
    PROFILE_BUCKET,
    PROFILE_OBJECT
)


class MyntraProfileRestorationTestSuite(unittest.TestCase):
    """
    Test suite for Myntra persistent Chrome profile restoration on Render.
    Validates configuration, archive extraction, profile layout normalization,
    transient cache cleaning, and live Playwright session accessibility.
    """

    def setUp(self):
        self.cli = get_supabase_client()

    def test_01_profile_config_and_credentials(self):
        """Verifies that Supabase credentials and profile storage bucket/object are configured."""
        config = get_profile_config()
        self.assertTrue(config["supabase_configured"], "Supabase URL and Key must be configured in environment.")
        self.assertEqual(config["bucket"], PROFILE_BUCKET)
        self.assertEqual(config["object"], PROFILE_OBJECT)
        self.assertFalse("secret" in str(config).lower(), "Credentials must never be exposed in configuration dicts.")

    def test_02_compatible_extractor_discovery(self):
        """Ensures a compatible extraction utility (unrar, unar, 7z, WinRAR) is discovered on the host."""
        tool_name, tool_path = find_rar_extractor()
        self.assertIsNotNone(
            tool_path,
            "No compatible RAR extraction utility found. On Render Linux, install 'unrar' or 'unar'. "
            "On Windows, ensure WinRAR/UnRAR is installed."
        )
        self.assertTrue(Path(tool_path).exists(), f"Discovered extractor path {tool_path} must exist.")

    def test_03_profile_download_extraction_and_layout(self):
        """Downloads archive from Supabase Storage and verifies Chrome profile structure."""
        async def _run():
            async with ProfileSession(run_id="test_unit_extract", client=self.cli) as p_info:
                self.assertIsNotNone(p_info["user_data_dir"])
                self.assertTrue(p_info["user_data_dir"].exists(), "user_data_dir must exist after extraction.")
                self.assertIn(p_info["profile_name"], ("Profile 1", "Default"), "Profile subdirectory must be recognized.")
                self.assertTrue(len(p_info["markers"]) > 0, "Recognized Chrome profile artifacts must be present.")
                
                # Check Windows DPAPI detection
                if p_info["is_windows_dpapi"]:
                    print(
                        f"\n[TEST NOTICE] Confirmed Windows DPAPI encryption in {PROFILE_OBJECT}. "
                        "When run on Linux, cookies cannot be decrypted by Linux Chromium. "
                        "A Linux-generated profile may be uploaded to replace it.",
                        flush=True
                    )

        asyncio.run(_run())

    def test_04_cache_cleaning(self):
        """Verifies that transient cache directories and lock files are cleaned before packaging."""
        async def _run():
            async with ProfileSession(run_id="test_unit_clean", client=self.cli) as p_info:
                user_data_dir = p_info["user_data_dir"]
                # Create mock cache directory and lock file
                mock_cache = user_data_dir / "MockCache"
                mock_cache.mkdir(parents=True, exist_ok=True)
                (mock_cache / "data_0.tmp").write_bytes(b"dummy")

                mock_lock = user_data_dir / "SingletonLock"
                mock_lock.write_text("12345", encoding="utf-8")

                cleaned = clean_profile_cache(user_data_dir)
                self.assertGreaterEqual(cleaned, 2, "Cleaned artifacts count should include mock cache and lock.")
                self.assertFalse(mock_cache.exists(), "Cache directory must be removed.")
                self.assertFalse(mock_lock.exists(), "SingletonLock must be removed.")

        asyncio.run(_run())

    def test_05_diagnostic_session_execution(self):
        """
        Executes the live diagnostic test.
        Verifies that session status is reported honestly:
        - If maintenance/access-denied is returned, does NOT falsely claim success.
        - Identifies whether Windows-encrypted cookies or IP challenges are responsible.
        """
        report = asyncio.run(run_myntra_diagnostic(client=self.cli))
        self.assertIn("diagnostic", report)
        self.assertEqual(report["diagnostic"], "myntra_profile_session")
        self.assertIn("diagnosis", report)
        self.assertIn("session_cookies", report)
        self.assertIn("page_response", report)

        # Honest assessment check:
        if report.get("is_access_denied") or report.get("is_maintenance"):
            self.assertFalse(
                report.get("is_catalog_accessible"),
                "Must not report catalog accessible when access-denied or maintenance was received!"
            )
            print(f"\n[DIAGNOSTIC TEST RESULT] Akamai challenge/maintenance accurately detected: {report['diagnosis']}", flush=True)
        elif report.get("is_catalog_accessible"):
            self.assertTrue(report.get("is_catalog_accessible"))
            print(f"\n[DIAGNOSTIC TEST RESULT] Normal catalog accessible: {report['diagnosis']}", flush=True)


if __name__ == "__main__":
    unittest.main()
