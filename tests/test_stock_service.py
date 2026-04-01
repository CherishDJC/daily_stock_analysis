# -*- coding: utf-8 -*-
"""Tests for StockService daily history caching behavior."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

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

    def _make_fund_flow_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "日期": "2026-03-17",
                    "收盘价": 38.12,
                    "涨跌幅": -0.52,
                    "主力净流入-净额": -12345678,
                    "主力净流入-净占比": -4.31,
                    "超大单净流入-净额": -5234567,
                    "超大单净流入-净占比": -1.92,
                    "大单净流入-净额": -7111111,
                    "大单净流入-净占比": -2.39,
                    "中单净流入-净额": 3456789,
                    "中单净流入-净占比": 1.43,
                    "小单净流入-净额": 8888889,
                    "小单净流入-净占比": 2.88,
                },
                {
                    "日期": "2026-03-18",
                    "收盘价": 39.01,
                    "涨跌幅": 2.34,
                    "主力净流入-净额": 23456789,
                    "主力净流入-净占比": 6.78,
                    "超大单净流入-净额": 13456789,
                    "超大单净流入-净占比": 3.82,
                    "大单净流入-净额": 10000000,
                    "大单净流入-净占比": 2.96,
                    "中单净流入-净额": -7654321,
                    "中单净流入-净占比": -2.21,
                    "小单净流入-净额": -15802468,
                    "小单净流入-净占比": -4.57,
                },
            ]
        )

    def _make_board_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"板块名称": "机器人概念", "板块代码": "BK001"},
                {"板块名称": "人工智能", "板块代码": "BK002"},
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

    def test_fund_flow_returns_recent_rows(self) -> None:
        manager = MagicMock()
        manager.get_stock_name.return_value = "世纪恒通"

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
        )

        fake_akshare = MagicMock()
        fake_akshare.stock_individual_fund_flow.return_value = self._make_fund_flow_df()

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            result = service.get_fund_flow_data("301428", limit=1)

        fake_akshare.stock_individual_fund_flow.assert_called_once_with(stock="301428", market="sz")
        self.assertEqual(result["stock_name"], "世纪恒通")
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["date"], "2026-03-18")
        self.assertEqual(result["data"][0]["main_net_inflow"], 23456789.0)

    def test_stock_meta_returns_basic_info_and_boards(self) -> None:
        manager = MagicMock()
        manager.get_stock_name.return_value = "机器人"
        manager.get_base_info.return_value = {
            "source": "tushare",
            "industry": "专用设备",
            "market": "创业板",
            "area": "辽宁",
            "list_date": "20091030",
            "fullname": "沈阳新松机器人自动化股份有限公司",
            "website": "https://example.com",
            "main_business": "机器人与自动化装备",
            "employees": "1234",
            "pe_ratio": "88.12",
            "pb_ratio": "4.56",
            "total_mv": "12300000000",
            "circ_mv": "9800000000",
        }
        manager.get_belong_board.return_value = self._make_board_df()

        service = StockService(
            repo=self.repo,
            manager_factory=lambda: manager,
            today_provider=lambda: self.today,
        )

        result = service.get_stock_meta_data("300024")

        self.assertEqual(result["stock_name"], "机器人")
        self.assertEqual(result["industry"], "专用设备")
        self.assertEqual(result["list_date"], "2009-10-30")
        self.assertEqual(result["employees"], 1234)
        self.assertEqual(result["pe_ratio"], 88.12)
        self.assertEqual(result["belong_boards"], ["机器人概念", "人工智能"])


if __name__ == "__main__":
    unittest.main()
