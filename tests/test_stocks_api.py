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
        self.service.get_fund_flow_data.return_value = {
            "stock_code": "301428",
            "stock_name": "世纪恒通",
            "source": "AkShare",
            "updated_at": "2026-03-19T11:35:00+08:00",
            "data": [
                {
                    "date": "2026-03-18",
                    "close": 39.01,
                    "change_percent": 2.34,
                    "main_net_inflow": 23456789.0,
                    "main_net_inflow_ratio": 6.78,
                    "super_large_net_inflow": 13456789.0,
                    "super_large_net_inflow_ratio": 3.82,
                    "large_net_inflow": 10000000.0,
                    "large_net_inflow_ratio": 2.96,
                    "medium_net_inflow": -7654321.0,
                    "medium_net_inflow_ratio": -2.21,
                    "small_net_inflow": -15802468.0,
                    "small_net_inflow_ratio": -4.57,
                }
            ],
        }
        self.service.get_stock_meta_data.return_value = {
            "stock_code": "301428",
            "stock_name": "世纪恒通",
            "source": "tushare",
            "updated_at": "2026-03-19T11:35:00+08:00",
            "industry": "软件服务",
            "market": "创业板",
            "area": "贵州",
            "list_date": "20230119",
            "full_name": "世纪恒通科技股份有限公司",
            "website": "https://example.com",
            "main_business": "数字信息服务",
            "employees": 666,
            "pe_ratio": 25.6,
            "pb_ratio": 3.2,
            "total_market_value": 5_600_000_000.0,
            "circulating_market_value": 4_300_000_000.0,
            "belong_boards": ["人工智能", "数据要素"],
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

    def test_stock_fund_flow_returns_recent_rows(self) -> None:
        response = self.client.get("/api/v1/stocks/301428/fund-flow?limit=5")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["stock_code"], "301428")
        self.assertEqual(payload["source"], "AkShare")
        self.assertEqual(payload["data"][0]["main_net_inflow"], 23456789.0)
        self.service.get_fund_flow_data.assert_called_once_with(
            stock_code="301428",
            limit=5,
        )

    def test_stock_meta_returns_basic_info(self) -> None:
        response = self.client.get("/api/v1/stocks/301428/meta")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["stock_code"], "301428")
        self.assertEqual(payload["industry"], "软件服务")
        self.assertEqual(payload["belong_boards"], ["人工智能", "数据要素"])
        self.service.get_stock_meta_data.assert_called_once_with(stock_code="301428")


if __name__ == "__main__":
    unittest.main()
