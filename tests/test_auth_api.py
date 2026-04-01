# -*- coding: utf-8 -*-
"""Integration tests for auth API endpoints and route protection."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AuthApiTestCase(unittest.TestCase):
    """Integration tests for fixed-credential auth mode."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=true\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.data_dir / "test.db")
        Config.reset_instance()

        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=True)
        self.data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self.auth_patcher.start()
        self.data_dir_patcher.start()

        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        self.data_dir_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _login_payload(self, **overrides):
        payload = {
            "username": auth.FIXED_ADMIN_USERNAME,
            "password": auth.FIXED_ADMIN_PASSWORD,
        }
        payload.update(overrides)
        return payload

    def test_auth_status_exposes_fixed_credential_mode(self) -> None:
        response = self.client.get("/api/v1/auth/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["authEnabled"])
        self.assertFalse(data["loggedIn"])
        self.assertTrue(data["passwordSet"])
        self.assertFalse(data["passwordChangeable"])
        self.assertTrue(data["usernameRequired"])
        self.assertEqual(data["fixedUsername"], auth.FIXED_ADMIN_USERNAME)
        self.assertFalse(data["humanVerificationEnabled"])

    def test_login_requires_username(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "", "password": auth.FIXED_ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "username_required")

    def test_login_with_fixed_credentials_succeeds(self) -> None:
        response = self.client.post("/api/v1/auth/login", json=self._login_payload())
        self.assertEqual(response.status_code, 200)
        self.assertIn("dsa_session", response.cookies)
        self.assertTrue(response.json().get("ok"))

    def test_login_wrong_username_returns_401(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json=self._login_payload(username="wrong"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_credentials")

    def test_login_wrong_password_returns_401(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json=self._login_payload(password="wrong"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_credentials")

    @patch("api.v1.endpoints.auth.verify_human_token")
    @patch("api.v1.endpoints.auth.get_human_verification_status")
    def test_login_requires_human_token_when_enabled(self, mock_status, mock_verify) -> None:
        mock_status.return_value = {
            "enabled": True,
            "provider": "turnstile",
            "site_key": "site-key",
        }
        mock_verify.return_value = (False, "请先完成人机验证")
        response = self.client.post("/api/v1/auth/login", json=self._login_payload())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "human_verification_failed")

    @patch("api.v1.endpoints.auth.verify_human_token")
    @patch("api.v1.endpoints.auth.get_human_verification_status")
    def test_login_accepts_valid_human_token(self, mock_status, mock_verify) -> None:
        mock_status.return_value = {
            "enabled": True,
            "provider": "turnstile",
            "site_key": "site-key",
        }
        mock_verify.return_value = (True, None)

        response = self.client.post(
            "/api/v1/auth/login",
            json=self._login_payload(humanToken="turnstile-token"),
        )
        self.assertEqual(response.status_code, 200)
        mock_verify.assert_called_once()

    def test_logout_clears_cookie(self) -> None:
        self.client.post("/api/v1/auth/login", json=self._login_payload())
        self.assertIn("dsa_session", self.client.cookies)
        self.client.post("/api/v1/auth/logout")
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 401)

    def test_logout_rejects_cross_site_origin(self) -> None:
        self.client.post("/api/v1/auth/login", json=self._login_payload())
        response = self.client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://evil.example.com"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "origin_not_allowed")

    def test_change_password_disabled_in_fixed_mode(self) -> None:
        self.client.post("/api/v1/auth/login", json=self._login_payload())
        response = self.client.post(
            "/api/v1/auth/change-password",
            json={
                "currentPassword": auth.FIXED_ADMIN_PASSWORD,
                "newPassword": "newpass6",
                "newPasswordConfirm": "newpass6",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_changeable")

    def test_protected_api_returns_401_without_session(self) -> None:
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 401)

    def test_root_redirects_to_login_without_session(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertIn("/login?redirect=%2F", response.headers["location"])

    def test_docs_redirect_to_login_without_session(self) -> None:
        response = self.client.get("/docs", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertIn("/login?redirect=%2Fdocs", response.headers["location"])

    def test_protected_api_accessible_with_session(self) -> None:
        self.client.post("/api/v1/auth/login", json=self._login_payload())
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 200)

    def test_mutating_api_rejects_cross_site_origin(self) -> None:
        self.client.post("/api/v1/auth/login", json=self._login_payload())
        response = self.client.put(
            "/api/v1/system/config",
            json={"config_version": "v1", "items": [], "reload_now": False},
            headers={"Origin": "https://evil.example.com"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "origin_not_allowed")


if __name__ == "__main__":
    unittest.main()
