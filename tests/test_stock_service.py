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


if __name__ == "__main__":
    unittest.main()
