# -*- coding: utf-8 -*-
"""Tests for human verification helpers."""

import io
import json
import os
import unittest
from unittest.mock import patch

from src.services.human_verification_service import (
    get_human_verification_status,
    verify_human_token,
)


class HumanVerificationServiceTestCase(unittest.TestCase):
    """Human verification service behavior."""

    @patch.dict(os.environ, {}, clear=True)
    def test_status_disabled_without_env(self) -> None:
        status = get_human_verification_status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["provider"])

    @patch.dict(
        os.environ,
        {
            "HUMAN_VERIFY_ENABLED": "true",
            "HUMAN_VERIFY_PROVIDER": "turnstile",
            "TURNSTILE_SITE_KEY": "site-key",
            "TURNSTILE_SECRET_KEY": "secret-key",
        },
        clear=True,
    )
    def test_status_enabled_with_turnstile_keys(self) -> None:
        status = get_human_verification_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["provider"], "turnstile")
        self.assertEqual(status["site_key"], "site-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_verify_skips_when_disabled(self) -> None:
        ok, err = verify_human_token("")
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch.dict(
        os.environ,
        {
            "HUMAN_VERIFY_ENABLED": "true",
            "HUMAN_VERIFY_PROVIDER": "turnstile",
            "TURNSTILE_SITE_KEY": "site-key",
            "TURNSTILE_SECRET_KEY": "secret-key",
        },
        clear=True,
    )
    def test_verify_turnstile_success(self) -> None:
        fake_response = io.BytesIO(json.dumps({"success": True}).encode("utf-8"))
        fake_response.__enter__ = lambda self=fake_response: self
        fake_response.__exit__ = lambda *args: False

        with patch("urllib.request.urlopen", return_value=fake_response):
            ok, err = verify_human_token("token", remote_ip="127.0.0.1")

        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch.dict(
        os.environ,
        {
            "HUMAN_VERIFY_ENABLED": "true",
            "HUMAN_VERIFY_PROVIDER": "turnstile",
            "TURNSTILE_SITE_KEY": "site-key",
            "TURNSTILE_SECRET_KEY": "secret-key",
        },
        clear=True,
    )
    def test_verify_turnstile_rejects_invalid_token(self) -> None:
        fake_response = io.BytesIO(json.dumps({"success": False, "error-codes": ["invalid-input-response"]}).encode("utf-8"))
        fake_response.__enter__ = lambda self=fake_response: self
        fake_response.__exit__ = lambda *args: False

        with patch("urllib.request.urlopen", return_value=fake_response):
            ok, err = verify_human_token("bad-token", remote_ip="127.0.0.1")

        self.assertFalse(ok)
        self.assertIn("未通过", err or "")


if __name__ == "__main__":
    unittest.main()
