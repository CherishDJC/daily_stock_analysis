# -*- coding: utf-8 -*-
"""Regression tests for screener tools."""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.tools import screener_tools


def _build_quotes(count: int) -> pd.DataFrame:
    rows = []
    for idx in range(count):
        code = f"{idx + 1:06d}"
        rows.append(
            {
                "code": code,
                "name": f"股票{idx + 1}",
                "price": 10 + idx * 0.1,
                "change_pct": 1.5,
                "volume_ratio": 1.2,
                "turnover_rate": 2.0,
                "pe_ratio": 20.0,
                "total_mv": 5e10,
                "amount": 1e8 - idx,
                "quote_source": "unit-test",
            }
        )
    return pd.DataFrame(rows)


class TestScreenerTools(unittest.TestCase):
    """Test screener tool internals."""

    def test_compute_ma_filter_calculates_volume_ratio(self):
        """Volume ratio should be derived from the fetched history frame."""
        raw_df = pd.DataFrame(
            {
                "日期": pd.date_range("2026-01-01", periods=20, freq="D"),
                "收盘": list(range(1, 21)),
                "成交量": [100] * 19 + [200],
            }
        )
        fake_akshare = types.SimpleNamespace(stock_zh_a_hist=lambda **kwargs: raw_df)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            result = screener_tools._compute_ma_filter("600519")

        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "600519")
        self.assertEqual(result["volume_ratio"], 1.67)

    def test_handle_full_scan_skips_metadata_loading_without_sector_filter(self):
        """Metadata lookup should not block the critical path when sectors are not requested."""
        quotes_df = _build_quotes(3)
        manager = MagicMock()
        manager.get_stock_list.side_effect = AssertionError("get_stock_list should not be called")

        with patch.object(screener_tools, "_get_fetcher_manager", return_value=manager), \
             patch.object(screener_tools, "_load_full_market_quotes", return_value=quotes_df), \
             patch.object(screener_tools, "_compute_ma_filter", return_value=None):
            result = screener_tools._handle_full_scan(json.dumps({}), top_n=3, max_candidates=3)

        self.assertEqual(result["result_count"], 3)
        self.assertEqual(len(result["results"]), 3)

    def test_handle_full_scan_caps_technical_scan_budget(self):
        """The expensive MA pass should inspect a bounded number of candidates."""
        quotes_df = _build_quotes(300)

        def _fake_ma_result(code: str):
            return {
                "code": code,
                "ma5": 10.0,
                "ma10": 9.8,
                "ma20": 9.5,
                "current_price": 10.2,
                "ma_bullish": True,
                "bias_ma5": 2.0,
                "volume_ratio": 1.1,
            }

        with patch.object(screener_tools, "_get_fetcher_manager", return_value=MagicMock()), \
             patch.object(screener_tools, "_load_full_market_quotes", return_value=quotes_df), \
             patch.object(screener_tools, "_load_stock_metadata", return_value=pd.DataFrame()), \
             patch.object(screener_tools, "_compute_ma_filter", side_effect=_fake_ma_result) as mock_compute:
            result = screener_tools._handle_full_scan(json.dumps({}), top_n=15, max_candidates=120)

        self.assertEqual(result["technical_scan_count"], 120)
        self.assertEqual(mock_compute.call_count, 120)


if __name__ == "__main__":
    unittest.main()
