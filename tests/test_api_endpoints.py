import unittest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from api import app

class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_root_endpoint(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("deploy_trigger", data["endpoints"])
        self.assertIn("daily_reports", data["endpoints"])

    @patch("api.check_and_trigger_scrapers", new_callable=AsyncMock)
    def test_deploy_trigger_post(self, mock_trigger):
        mock_trigger.return_value = {
            "status": "already_completed",
            "message": "All scrapers already completed for today",
            "date": "2026-10-07"
        }
        res = self.client.post("/deploy-trigger?force=true")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "already_completed")

    @patch("api.check_and_trigger_scrapers", new_callable=AsyncMock)
    def test_deploy_trigger_get(self, mock_trigger):
        mock_trigger.return_value = {
            "status": "already_completed",
            "message": "All scrapers already completed for today",
            "date": "2026-10-07"
        }
        res = self.client.get("/deploy-trigger?force=true")
        self.assertEqual(res.status_code, 200)

    @patch("api.check_and_trigger_scrapers", new_callable=AsyncMock)
    def test_deploy_trigger_starts_job(self, mock_trigger):
        mock_trigger.return_value = {
            "status": "started",
            "message": "Scraper job queued: missing ['tata']",
            "job_id": "scrape_job_12345"
        }
        res = self.client.post("/deploy-trigger?force=true")
        self.assertEqual(res.status_code, 202)
        data = res.json()
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["job_id"], "scrape_job_12345")

    @patch("api.get_all_daily_reports", new_callable=AsyncMock)
    def test_get_daily_reports(self, mock_get_reports):
        mock_get_reports.return_value = {
            "business_date": "2026-10-07",
            "reports": {
                "amazon": {
                    "scraper": "amazon",
                    "status": "completed",
                    "products_scraped": 50
                }
            }
        }
        res = self.client.get("/scrape/report")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reports", data)
        self.assertIn("amazon", data["reports"])

    @patch("api.get_daily_run_report", new_callable=AsyncMock)
    def test_get_specific_scraper_report(self, mock_get_report):
        mock_get_report.return_value = {
            "scraper": "tata",
            "status": "completed",
            "total_products": 25,
            "total_variants": 120
        }
        res = self.client.get("/scrape/report/tata")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["scraper"], "tata")
        self.assertEqual(data["status"], "completed")

    @patch("api.get_daily_run_report", new_callable=AsyncMock)
    def test_get_specific_scraper_report_not_found(self, mock_get_report):
        mock_get_report.return_value = None
        res = self.client.get("/scrape/report/nonexistent")
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertIn("error", data)

    @patch("api.stop_current_scraper", new_callable=AsyncMock)
    @patch("api.stop_active_pipeline", new_callable=AsyncMock)
    def test_stop_pipeline_post(self, mock_stop_active, mock_stop_scraper):
        mock_stop_active.return_value = {
            "status": "stopped",
            "message": "Pipeline successfully halted: User test stop",
            "stopped_job": "job_123"
        }
        res = self.client.post("/scrape/stop?reason=User test stop")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "stopped")
        self.assertEqual(data["stopped_job"], "job_123")
        mock_stop_scraper.assert_called_once()
        mock_stop_active.assert_called_once()

    @patch("api.stop_current_scraper", new_callable=AsyncMock)
    @patch("api.stop_active_pipeline", new_callable=AsyncMock)
    def test_stop_pipeline_get(self, mock_stop_active, mock_stop_scraper):
        mock_stop_active.return_value = {
            "status": "stopped",
            "message": "Pipeline successfully halted",
            "stopped_job": None
        }
        res = self.client.get("/scrape/stop")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "stopped")

    @patch("api.reset_daily_scrapers", new_callable=AsyncMock)
    def test_reset_scrapers_post(self, mock_reset):
        mock_reset.return_value = {
            "business_date": "2026-10-07",
            "reset_scrapers": ["columbia", "adv", "amazon", "tata"],
            "details": []
        }
        res = self.client.post("/scrape/reset?scrapers=all")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "reset_completed")
        self.assertIn("Successfully reset scrapers", data["message"])
        mock_reset.assert_called_once()

    @patch("api.reset_daily_scrapers", new_callable=AsyncMock)
    def test_reset_scrapers_get(self, mock_reset):
        mock_reset.return_value = {
            "business_date": "2026-10-07",
            "reset_scrapers": ["amazon"],
            "details": []
        }
        res = self.client.get("/scrape/reset?scrapers=amazon")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "reset_completed")

if __name__ == "__main__":
    unittest.main()
