# -*- coding: utf-8 -*-
"""Tests for StockService daily history caching behavior."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd

from src.config import Config
from src.repositories.stock_repo import StockRepository
from src.services.stock_service import StockService
from src.storage import DatabaseManager


class StockServiceHistoryCacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_stock_service.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.repo = StockRepository(self.db)
        self.today = date(2026, 3, 18)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _make_daily_df(self, start_date: date, count: int, start_close: float = 100.0) -> pd.DataFrame:
        rows = []
        for offset in range(count):
            current_date = start_date + timedelta(days=offset)
            close = start_close + offset
            rows.append(
                {
                    "date": current_date,
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 1_000_000 + offset,
                    "amount": 10_000_000 + offset * 1_000,
                    "pct_chg": round(offset * 0.5, 2),
                }
            )
        return pd.DataFrame(rows)

    def _make_minute_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "timestamp": "2026-03-18 09:30:00",
                    "open": 38.80,
                    "high": 38.92,
                    "low": 38.75,
                    "close": 38.90,
                    "volume": 10200,
                    "amount": 396780.0,
                    "change_percent": None,
                },
                {
                    "timestamp": "2026-03-18 09:31:00",
                    "open": 38.90,
                    "high": 39.01,
                    "low": 38.88,
                    "close": 38.98,
                    "volume": 8600,
                    "amount": 335228.0,
                    "change_percent": 0.21,
                },
            ]
        )

    def _make_trade_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"timestamp": "09:31:12", "price": 38.98, "volume": 20, "side": "买盘"},
                {"timestamp": "09:31:20", "price": 38.97, "volume": 12, "side": "卖盘"},
            ]
        )

    def test_history_uses_cached_stable_rows_and_only_refreshes_recent_window(self) -> None:
        self.repo.save_dataframe(
            self._make_daily_df(date(2026, 3, 10), 8, start_close=90.0),
            "600519",
            data_source="SeedData",
        )

        recent_df = self._make_daily_df(date(2026, 3, 14), 5, start_close=100.0)
        manager = MagicMock()
        manager.get_daily_data.return_value = (recent_df, "AkshareFetcher")
        manager.get_stock_name.return_value = "贵州茅台"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
            recent_refresh_days=5,
        )

        result = service.get_history_data("600519", days=6)

        manager.get_daily_data.assert_called_once_with(
            stock_code="600519",
            start_date=None,
            end_date=None,
            days=5,
        )
        self.assertEqual(result["stock_name"], "贵州茅台")
        self.assertEqual(len(result["data"]), 6)
        self.assertEqual(result["data"][-1]["date"], "2026-03-18")
        self.assertFalse(self.repo.has_today_data("600519", target_date=self.today))

    def test_history_backfills_db_when_stable_cache_is_missing(self) -> None:
        full_df = self._make_daily_df(date(2026, 3, 13), 6, start_close=120.0)
        manager = MagicMock()
        manager.get_daily_data.return_value = (full_df, "AkshareFetcher")
        manager.get_stock_name.return_value = "贵州茅台"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
            recent_refresh_days=5,
        )

        result = service.get_history_data("600519", days=6)

        manager.get_daily_data.assert_called_once_with(
            stock_code="600519",
            start_date=None,
            end_date=None,
            days=6,
        )
        cached_rows = self.repo.get_latest_until("600519", end_date=self.today - timedelta(days=1), limit=10)
        self.assertEqual(len(cached_rows), 5)
        self.assertEqual(cached_rows[-1].date, date(2026, 3, 17))
        self.assertFalse(self.repo.has_today_data("600519", target_date=self.today))
        self.assertEqual(len(result["data"]), 6)
        self.assertEqual(result["data"][-1]["date"], "2026-03-18")

    def test_history_falls_back_to_cached_rows_when_recent_refresh_fails(self) -> None:
        self.repo.save_dataframe(
            self._make_daily_df(date(2026, 3, 12), 6, start_close=80.0),
            "600519",
            data_source="SeedData",
        )

        manager = MagicMock()
        manager.get_daily_data.side_effect = RuntimeError("timeout")
        manager.get_stock_name.return_value = "贵州茅台"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
            recent_refresh_days=5,
        )

        result = service.get_history_data("600519", days=6)

        manager.get_daily_data.assert_called_once_with(
            stock_code="600519",
            start_date=None,
            end_date=None,
            days=5,
        )
        self.assertEqual(len(result["data"]), 6)
        self.assertEqual(result["data"][-1]["date"], "2026-03-17")

    def test_intraday_returns_minute_bars_and_recent_trades(self) -> None:
        manager = MagicMock()
        manager.get_minute_data.return_value = (self._make_minute_df(), "AkshareFetcher")
        manager.get_intraday_trades.return_value = (self._make_trade_df(), "AkshareFetcher")
        manager.get_stock_name.return_value = "世纪恒通"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
        )

        result = service.get_intraday_data("301428", interval="1", limit=120)

        manager.get_minute_data.assert_called_once_with(
            stock_code="301428",
            interval="1",
            limit=120,
        )
        manager.get_intraday_trades.assert_called_once_with(stock_code="301428", limit=10)
        self.assertEqual(result["stock_name"], "世纪恒通")
        self.assertEqual(result["source"], "AkshareFetcher")
        self.assertEqual(len(result["bars"]), 2)
        self.assertEqual(result["bars"][1]["change_percent"], 0.21)
        self.assertEqual(result["trades"][0]["side"], "买盘")

    def test_intraday_degrades_when_trade_feed_fails(self) -> None:
        manager = MagicMock()
        manager.get_minute_data.return_value = (self._make_minute_df(), "AkshareFetcher")
        manager.get_intraday_trades.side_effect = RuntimeError("RemoteDisconnected")
        manager.get_stock_name.return_value = "世纪恒通"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
        )

        result = service.get_intraday_data("301428", interval="5", limit=80)

        self.assertEqual(result["interval"], "5")
        self.assertEqual(len(result["bars"]), 2)
        self.assertEqual(result["trades"], [])


if __name__ == "__main__":
    unittest.main()
