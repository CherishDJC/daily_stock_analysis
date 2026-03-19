# -*- coding: utf-8 -*-
"""Integration tests for stock intraday API."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config


class StocksApiTestCase(unittest.TestCase):
    """Stocks API tests with auth disabled."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "STOCK_LIST=301428\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        auth._auth_enabled = None
        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=False)
        self.auth_patcher.start()

        self.service = Mock()
        self.service.get_intraday_data.return_value = {
            "stock_code": "301428",
            "stock_name": "世纪恒通",
            "interval": "1",
            "source": "AkshareFetcher",
            "trades_source": "AkshareFetcher",
            "updated_at": "2026-03-19T11:31:00+08:00",
            "bars": [
                {
                    "timestamp": "2026-03-19 11:30:00",
                    "open": 38.88,
                    "high": 39.03,
                    "low": 38.82,
                    "close": 39.01,
                    "volume": 56900,
                    "amount": 2218526.0,
                    "change_percent": 0.21,
                }
            ],
            "trades": [
                {
                    "timestamp": "11:30:51",
                    "price": 39.01,
                    "volume": 67.0,
                    "side": "买盘",
                }
            ],
        }

        self.service_patcher = patch("api.v1.endpoints.stocks.StockService", return_value=self.service)
        self.service_patcher.start()

        app = create_app(static_dir=Path(self.temp_dir.name) / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.service_patcher.stop()
        self.auth_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_stock_intraday_returns_minute_bars_and_trades(self) -> None:
        response = self.client.get("/api/v1/stocks/301428/intraday?interval=5&limit=180&include_trades=true")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["stock_code"], "301428")
        self.assertEqual(payload["interval"], "1")
        self.assertEqual(payload["bars"][0]["close"], 39.01)
        self.assertEqual(payload["trades"][0]["side"], "买盘")
        self.service.get_intraday_data.assert_called_once_with(
            stock_code="301428",
            interval="5",
            limit=180,
            include_trades=True,
        )

    def test_stock_intraday_rejects_unsupported_interval(self) -> None:
        response = self.client.get("/api/v1/stocks/301428/intraday?interval=2")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
