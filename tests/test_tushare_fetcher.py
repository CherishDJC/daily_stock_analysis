# -*- coding: utf-8 -*-
"""Tests for TushareFetcher A-share integrations."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

import pandas as pd

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.tushare_fetcher import TushareFetcher


class TushareFetcherBaseInfoTestCase(unittest.TestCase):
    def _make_fetcher(self) -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None), patch.object(
            TushareFetcher, "_determine_priority", return_value=-1
        ):
            fetcher = TushareFetcher(rate_limit_per_minute=9999)
        fetcher._api = MagicMock()
        fetcher._check_rate_limit = MagicMock()
        return fetcher

    def test_get_base_info_merges_basic_company_and_holder_data(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "area": "贵州",
                    "industry": "白酒",
                    "market": "主板",
                    "list_date": "20010827",
                }
            ]
        )
        fetcher._api.stock_company.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "chairman": "张三",
                    "manager": "李四",
                    "website": "https://example.com",
                    "main_business": "白酒生产",
                }
            ]
        )
        fetcher._api.namechange.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "name": "茅台股份",
                    "start_date": "20000101",
                    "end_date": "20010826",
                    "ann_date": "20000101",
                    "change_reason": "上市前",
                }
            ]
        )
        fetcher._api.dividend.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "end_date": "20241231",
                    "ann_date": "20250301",
                    "div_proc": "实施",
                    "cash_div_tax": 30.876,
                }
            ]
        )
        fetcher._api.top10_holders.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20250331",
                    "end_date": "20241231",
                    "holder_name": "贵州茅台集团",
                    "hold_amount": 67890,
                    "hold_ratio": 54.0,
                }
            ]
        )
        fetcher._api.top10_floatholders.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20250331",
                    "end_date": "20241231",
                    "holder_name": "全国社保基金",
                    "hold_amount": 1234,
                    "hold_ratio": 0.98,
                }
            ]
        )

        info = fetcher.get_base_info("600519")

        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "贵州茅台")
        self.assertEqual(info["industry"], "白酒")
        self.assertEqual(info["chairman"], "张三")
        self.assertEqual(info["main_business"], "白酒生产")
        self.assertEqual(info["former_names"], ["茅台股份"])
        self.assertEqual(info["latest_dividend"]["cash_div_tax"], 30.876)
        self.assertEqual(info["top10_holders"][0]["holder_name"], "贵州茅台集团")
        self.assertEqual(info["top10_floatholders"][0]["holder_name"], "全国社保基金")

    def test_get_market_stats_uses_recent_daily_without_trade_cal_permission(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.daily.side_effect = [
            pd.DataFrame(),
            pd.DataFrame(
                [
                    {"pct_chg": 1.2, "amount": 1000},
                    {"pct_chg": -0.5, "amount": 2000},
                    {"pct_chg": 0.0, "amount": 3000},
                ]
                * 50
            ),
        ]

        stats = fetcher.get_market_stats()

        self.assertIsNotNone(stats)
        self.assertEqual(stats["up_count"], 50)
        self.assertEqual(stats["down_count"], 50)
        self.assertEqual(stats["flat_count"], 50)
        self.assertAlmostEqual(stats["total_amount"], 3.0)


class AkshareFetcherSectorFallbackTestCase(unittest.TestCase):
    def test_get_sector_rankings_prefers_working_sina_industry_snapshot(self) -> None:
        fake_df = pd.DataFrame(
            [
                {"板块": "半导体", "涨跌幅": 3.1},
                {"板块": "机器人", "涨跌幅": 2.2},
                {"板块": "煤炭", "涨跌幅": -1.8},
            ]
        )
        fake_akshare = SimpleNamespace(
            stock_sector_spot=MagicMock(return_value=fake_df),
            stock_board_industry_name_em=MagicMock(return_value=pd.DataFrame()),
        )

        with patch("data_provider.akshare_fetcher.get_config", return_value=SimpleNamespace(enable_eastmoney_patch=False)):
            fetcher = AkshareFetcher(sleep_min=0.0, sleep_max=0.0)

        fetcher._set_random_user_agent = MagicMock()
        fetcher._enforce_rate_limit = MagicMock()

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            top, bottom = fetcher.get_sector_rankings(n=2)

        fake_akshare.stock_sector_spot.assert_called_once_with(indicator="行业")
        self.assertEqual(top[0]["name"], "半导体")
        self.assertEqual(bottom[0]["name"], "煤炭")


if __name__ == "__main__":
    unittest.main()
