import unittest
from fastapi.testclient import TestClient
from api import app
from app.services.user_service import user_service

class TestAuthAndUserService(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_kartikey_login_success(self):
        res = self.client.post("/api/auth/login", json={
            "username": "kartikey",
            "password": "kartikey123"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], "kartikey")

    def test_raj_login_success(self):
        res = self.client.post("/api/auth/login", json={
            "username": "raj",
            "password": "raj123"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], "raj")

    def test_invalid_login_rejected(self):
        res = self.client.post("/api/auth/login", json={
            "username": "kartikey",
            "password": "wrong_password"
        })
        self.assertEqual(res.status_code, 401)

    def test_protected_me_endpoint_with_jwt(self):
        login_res = self.client.post("/api/auth/login", json={
            "username": "kartikey",
            "password": "kartikey123"
        })
        token = login_res.json()["access_token"]

        me_res = self.client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        self.assertEqual(me_res.status_code, 200)
        data = me_res.json()
        self.assertEqual(data["username"], "kartikey")
        self.assertTrue("email" not in data or data.get("email") is None)

    def test_reset_password(self):
        login_res = self.client.post("/api/auth/login", json={
            "username": "raj",
            "password": "raj123"
        })
        token = login_res.json()["access_token"]

        reset_res = self.client.post("/api/auth/reset-password", json={
            "new_password": "raj_new_password_2026"
        }, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(reset_res.status_code, 200)

        # Login with new password
        login2 = self.client.post("/api/auth/login", json={
            "username": "raj",
            "password": "raj_new_password_2026"
        })
        self.assertEqual(login2.status_code, 200)

        # Restore default password for idempotency
        user_service.reset_password("raj", "raj123")

    def test_master_data_status_user_scoped(self):
        login_res = self.client.post("/api/auth/login", json={
            "username": "kartikey",
            "password": "kartikey123"
        })
        token = login_res.json()["access_token"]

        res = self.client.get("/api/master-data/status", headers={
            "Authorization": f"Bearer {token}"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["username"], "kartikey")
        self.assertIn("is_configured", data)

if __name__ == "__main__":
    unittest.main()
