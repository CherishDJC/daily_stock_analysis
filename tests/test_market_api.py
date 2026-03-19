# -*- coding: utf-8 -*-
"""Integration tests for market overview API."""

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


class MarketApiTestCase(unittest.TestCase):
    """Market API tests with auth disabled."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001,AAPL",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        auth._auth_enabled = None
        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=False)
        self.auth_patcher.start()

        self.service = Mock()
        self.service.get_overview.return_value = {
            "trading_date": "2026-03-18",
            "session_state": "open",
            "realtime_enabled": True,
            "updated_at": "2026-03-18T10:15:00+08:00",
            "refresh_interval_seconds": 5,
            "watchlist_total": 3,
            "supported_total": 2,
            "unsupported_codes": ["AAPL"],
            "watchlist": [
                {
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "status": "ok",
                    "error_message": None,
                    "current_price": 1820.0,
                    "change": 12.5,
                    "change_percent": 0.69,
                    "open": 1810.0,
                    "high": 1828.0,
                    "low": 1805.0,
                    "prev_close": 1807.5,
                    "volume": 950000,
                    "amount": 1730000000,
                    "volume_ratio": 1.23,
                    "turnover_rate": 0.62,
                    "amplitude": 1.27,
                    "source": "efinance",
                    "price_position": 0.65,
                },
                {
                    "stock_code": "000001",
                    "stock_name": None,
                    "status": "error",
                    "error_message": "No realtime quote available.",
                    "current_price": None,
                    "change": None,
                    "change_percent": None,
                    "open": None,
                    "high": None,
                    "low": None,
                    "prev_close": None,
                    "volume": None,
                    "amount": None,
                    "volume_ratio": None,
                    "turnover_rate": None,
                    "amplitude": None,
                    "source": None,
                    "price_position": None,
                },
            ],
            "indices": [{"code": "sh000001", "name": "上证指数", "current": 3300.0, "change": 11.0, "change_pct": 0.33}],
            "market_stats": {
                "up_count": 3600,
                "down_count": 1400,
                "flat_count": 120,
                "limit_up_count": 82,
                "limit_down_count": 4,
                "total_amount": 8123.5,
            },
            "top_sectors": [{"name": "半导体", "change_pct": 3.2}],
            "bottom_sectors": [{"name": "煤炭", "change_pct": -1.1}],
            "partial_errors": [{"scope": "watchlist_quote", "target": "000001", "message": "No realtime quote available."}],
        }
        self.service.get_sector_constituents.return_value = {
            "sector_name": "半导体",
            "total_matched": 2,
            "limit": 10,
            "updated_at": "2026-03-18T10:15:30+08:00",
            "constituents": [
                {
                    "stock_code": "600001",
                    "stock_name": "半导体一号",
                    "industry": "半导体",
                    "area": "上海",
                    "status": "ok",
                    "error_message": None,
                    "current_price": 21.5,
                    "change": 0.8,
                    "change_percent": 3.86,
                    "volume_ratio": 1.12,
                    "turnover_rate": 2.31,
                    "amount": 180000000.0,
                    "source": "tencent",
                },
                {
                    "stock_code": "600002",
                    "stock_name": "半导体二号",
                    "industry": "半导体设备",
                    "area": "深圳",
                    "status": "error",
                    "error_message": "No realtime quote available.",
                    "current_price": None,
                    "change": None,
                    "change_percent": None,
                    "volume_ratio": None,
                    "turnover_rate": None,
                    "amount": None,
                    "source": None,
                },
            ],
            "partial_errors": [
                {
                    "scope": "sector_constituents_quote",
                    "target": "600002",
                    "message": "No realtime quote available.",
                }
            ],
        }

        self.service_patcher = patch(
            "api.v1.endpoints.market.get_market_monitor_service",
            return_value=self.service,
        )
        self.service_patcher.start()

        app = create_app(static_dir=Path(self.temp_dir.name) / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.service_patcher.stop()
        self.auth_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_market_overview_returns_snapshot_and_passes_force_refresh(self) -> None:
        response = self.client.get("/api/v1/market/overview?force_refresh=true")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["session_state"], "open")
        self.assertEqual(payload["unsupported_codes"], ["AAPL"])
        self.assertEqual(payload["watchlist"][1]["status"], "error")
        self.assertEqual(payload["partial_errors"][0]["target"], "000001")
        self.service.get_overview.assert_called_once_with(
            force_refresh=True,
            include_watchlist=True,
            include_summary=True,
        )

    def test_market_overview_supports_section_loading_flags(self) -> None:
        response = self.client.get("/api/v1/market/overview?include_summary=false&include_watchlist=true")
        self.assertEqual(response.status_code, 200)
        self.service.get_overview.assert_called_with(
            force_refresh=False,
            include_watchlist=True,
            include_summary=False,
        )

    def test_market_overview_supports_empty_a_share_state(self) -> None:
        self.service.get_overview.return_value = {
            "trading_date": "2026-03-18",
            "session_state": "after_close",
            "realtime_enabled": True,
            "updated_at": "2026-03-18T16:10:00+08:00",
            "refresh_interval_seconds": 0,
            "watchlist_total": 2,
            "supported_total": 0,
            "unsupported_codes": ["AAPL", "HK00700"],
            "watchlist": [],
            "indices": [],
            "market_stats": {
                "up_count": None,
                "down_count": None,
                "flat_count": None,
                "limit_up_count": None,
                "limit_down_count": None,
                "total_amount": None,
            },
            "top_sectors": [],
            "bottom_sectors": [],
            "partial_errors": [],
        }

        response = self.client.get("/api/v1/market/overview")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supported_total"], 0)
        self.assertEqual(payload["watchlist"], [])

    def test_sector_constituents_returns_drill_down_rows(self) -> None:
        response = self.client.get("/api/v1/market/sectors/%E5%8D%8A%E5%AF%BC%E4%BD%93/constituents?limit=5&force_refresh=true")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["sector_name"], "半导体")
        self.assertEqual(payload["total_matched"], 2)
        self.assertEqual(payload["constituents"][0]["stock_code"], "600001")
        self.assertEqual(payload["partial_errors"][0]["target"], "600002")
        self.service.get_sector_constituents.assert_called_once_with(
            sector_name="半导体",
            force_refresh=True,
            limit=5,
        )


class MarketApiAuthTestCase(unittest.TestCase):
    """Market API respects the same auth protection as other system endpoints."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text(
            "STOCK_LIST=600519\nADMIN_AUTH_ENABLED=true\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.data_dir / "test.db")
        Config.reset_instance()

        auth._auth_enabled = None
        auth._session_secret = None
        auth._password_hash_salt = None
        auth._password_hash_stored = None
        auth._rate_limit = {}

        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=True)
        self.data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self.auth_patcher.start()
        self.data_dir_patcher.start()

        self.service_patcher = patch(
            "api.v1.endpoints.market.get_market_monitor_service",
            return_value=Mock(
                get_overview=Mock(
                    return_value={
                        "trading_date": "2026-03-18",
                        "session_state": "open",
                        "realtime_enabled": True,
                        "updated_at": "2026-03-18T10:15:00+08:00",
                        "refresh_interval_seconds": 5,
                        "watchlist_total": 1,
                        "supported_total": 1,
                        "unsupported_codes": [],
                        "watchlist": [],
                        "indices": [],
                        "market_stats": {
                            "up_count": None,
                            "down_count": None,
                            "flat_count": None,
                            "limit_up_count": None,
                            "limit_down_count": None,
                            "total_amount": None,
                        },
                        "top_sectors": [],
                        "bottom_sectors": [],
                        "partial_errors": [],
                    }
                )
            ),
        )
        self.service_patcher.start()

        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.service_patcher.stop()
        self.auth_patcher.stop()
        self.data_dir_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_market_overview_requires_login_when_auth_enabled(self) -> None:
        client_no_cookie = TestClient(create_app(static_dir=self.data_dir / "empty-static"), raise_server_exceptions=False)
        response = client_no_cookie.get("/api/v1/market/overview")
        self.assertEqual(response.status_code, 401)

    def test_sector_constituents_requires_login_when_auth_enabled(self) -> None:
        client_no_cookie = TestClient(create_app(static_dir=self.data_dir / "empty-static"), raise_server_exceptions=False)
        response = client_no_cookie.get("/api/v1/market/sectors/%E5%8D%8A%E5%AF%BC%E4%BD%93/constituents")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
