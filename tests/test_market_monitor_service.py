# -*- coding: utf-8 -*-
"""Unit tests for MarketMonitorService."""

from __future__ import annotations

import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.services.market_monitor_service import MarketMonitorService


class FakeClock:
    """Mutable clock for cache TTL tests."""

    def __init__(self, current_dt: datetime, monotonic_value: float = 100.0) -> None:
        self.current_dt = current_dt
        self.monotonic_value = monotonic_value

    def now(self) -> datetime:
        return self.current_dt

    def monotonic(self) -> float:
        return self.monotonic_value


def _make_quote(code: str, name: str, price: float = 100.0) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name=name,
        source=RealtimeSource.EFINANCE,
        price=price,
        change_pct=1.5,
        change_amount=1.48,
        volume=1200000,
        amount=980000000,
        volume_ratio=1.21,
        turnover_rate=0.67,
        amplitude=2.35,
        open_price=98.4,
        high=101.2,
        low=97.8,
        pre_close=98.52,
    )


class MarketMonitorServiceTestCase(unittest.TestCase):
    """Tests for service aggregation, degradation, and caching."""

    def setUp(self) -> None:
        self.clock = FakeClock(datetime(2026, 3, 18, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai")))

    def test_mixed_watchlist_only_keeps_a_share_codes_and_preserves_error_rows(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519", "AAPL", "000001", "HK00700"],
            enable_realtime_quote=True,
        )
        manager = MagicMock()
        manager.prefetch_realtime_quotes.return_value = 2
        manager.get_realtime_quote.side_effect = [
            _make_quote("600519", "贵州茅台", 1820.0),
            None,
        ]
        manager.get_main_indices.return_value = [{"code": "sh000001", "name": "上证指数", "current": 3300.0}]
        manager.get_market_stats.return_value = {
            "up_count": 3600,
            "down_count": 1400,
            "flat_count": 120,
            "limit_up_count": 82,
            "limit_down_count": 4,
            "total_amount": 8123.5,
        }
        manager.get_sector_rankings.return_value = (
            [{"name": "半导体", "change_pct": 3.2}],
            [{"name": "煤炭", "change_pct": -1.1}],
        )

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        with patch("src.services.market_monitor_service.is_market_open", return_value=True):
            overview = service.get_overview()

        self.assertEqual(overview["watchlist_total"], 4)
        self.assertEqual(overview["supported_total"], 2)
        self.assertEqual(overview["unsupported_codes"], ["AAPL", "HK00700"])
        self.assertEqual([item["stock_code"] for item in overview["watchlist"]], ["600519", "000001"])
        self.assertEqual(overview["watchlist"][0]["status"], "ok")
        self.assertEqual(overview["watchlist"][1]["status"], "error")
        self.assertIn("000001", {item["target"] for item in overview["partial_errors"]})
        manager.prefetch_realtime_quotes.assert_called_once_with(["600519", "000001"])
        manager.get_realtime_quote.assert_any_call("600519", use_non_critical_fallback=False)
        manager.get_realtime_quote.assert_any_call("000001", use_non_critical_fallback=False)

    def test_realtime_disabled_returns_error_rows_without_quote_fetch(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519", "000001"],
            enable_realtime_quote=False,
        )
        manager = MagicMock()
        manager.get_main_indices.return_value = []
        manager.get_market_stats.return_value = {}
        manager.get_sector_rankings.return_value = ([], [])

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        with patch("src.services.market_monitor_service.is_market_open", return_value=True):
            overview = service.get_overview()

        self.assertFalse(overview["realtime_enabled"])
        self.assertEqual(len(overview["watchlist"]), 2)
        self.assertTrue(all(item["status"] == "error" for item in overview["watchlist"]))
        self.assertIn("ENABLE_REALTIME_QUOTE", {item["target"] for item in overview["partial_errors"]})
        manager.get_realtime_quote.assert_not_called()

    def test_cache_ttl_and_force_refresh_control_manager_reuse(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519"],
            enable_realtime_quote=True,
        )

        factory_calls = {"count": 0}

        def manager_factory() -> MagicMock:
            factory_calls["count"] += 1
            manager = MagicMock()
            manager.prefetch_realtime_quotes.return_value = 1
            manager.get_realtime_quote.return_value = _make_quote("600519", "贵州茅台", 1800.0 + factory_calls["count"])
            manager.get_main_indices.return_value = [{"code": "sh000001", "name": "上证指数", "current": 3300.0}]
            manager.get_market_stats.return_value = {
                "up_count": 1,
                "down_count": 1,
                "flat_count": 0,
                "limit_up_count": 0,
                "limit_down_count": 0,
                "total_amount": 100.0,
            }
            manager.get_sector_rankings.return_value = ([], [])
            return manager

        service = MarketMonitorService(
            manager_factory=manager_factory,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        with patch("src.services.market_monitor_service.is_market_open", return_value=True):
            first = service.get_overview()
            second = service.get_overview()
            self.clock.monotonic_value += 4.0
            third = service.get_overview()
            forced = service.get_overview(force_refresh=True)

        self.assertEqual(factory_calls["count"], 12)
        self.assertEqual(first["watchlist"][0]["current_price"], second["watchlist"][0]["current_price"])
        self.assertNotEqual(second["watchlist"][0]["current_price"], third["watchlist"][0]["current_price"])
        self.assertNotEqual(third["watchlist"][0]["current_price"], forced["watchlist"][0]["current_price"])

    def test_watchlist_only_request_skips_summary_fetches(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519"],
            enable_realtime_quote=True,
        )
        manager = MagicMock()
        manager.prefetch_realtime_quotes.return_value = 1
        manager.get_realtime_quote.return_value = _make_quote("600519", "贵州茅台", 1820.0)

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        with patch("src.services.market_monitor_service.is_market_open", return_value=True):
            overview = service.get_overview(include_summary=False)

        self.assertEqual(len(overview["watchlist"]), 1)
        self.assertEqual(overview["indices"], [])
        self.assertEqual(overview["top_sectors"], [])
        self.assertEqual(overview["bottom_sectors"], [])
        self.assertEqual(
            overview["market_stats"],
            {
                "up_count": None,
                "down_count": None,
                "flat_count": None,
                "limit_up_count": None,
                "limit_down_count": None,
                "total_amount": None,
            },
        )
        manager.get_main_indices.assert_not_called()
        manager.get_market_stats.assert_not_called()
        manager.get_sector_rankings.assert_not_called()

    def test_watchlist_timeout_scales_with_batches_instead_of_truncating_tail_items(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519", "000001", "000002", "000003", "000004", "000005", "000006", "000007"],
            enable_realtime_quote=True,
        )

        class SlowManager:
            def prefetch_realtime_quotes(self, codes):
                return len(codes)

            def get_realtime_quote(self, code, use_non_critical_fallback=False):
                time.sleep(4.5)
                return _make_quote(code, f"股票{code}", 10.0)

            def get_main_indices(self, region="cn"):
                return []

            def get_market_stats(self):
                return {}

            def get_sector_rankings(self, n=5):
                return ([], [])

        service = MarketMonitorService(
            manager_factory=lambda: SlowManager(),
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=0.0,
            quote_workers=4,
            task_timeout_seconds=8.0,
        )

        with patch("src.services.market_monitor_service.is_market_open", return_value=True):
            overview = service.get_overview(force_refresh=True, include_summary=False)

        self.assertEqual(len(overview["watchlist"]), 8)
        self.assertTrue(all(item["status"] == "ok" for item in overview["watchlist"]))

    def test_sector_constituents_match_related_stocks_and_keep_quote_errors(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519"],
            enable_realtime_quote=True,
        )
        manager = MagicMock()
        manager.get_stock_list.return_value = pd.DataFrame(
            [
                {"code": "600001", "name": "新能源一号", "industry": "新能源车", "area": "上海", "market": "主板"},
                {"code": "600002", "name": "新能源二号", "industry": "新能源车", "area": "深圳", "market": "主板"},
                {"code": "600003", "name": "光伏一号", "industry": "光伏设备", "area": "苏州", "market": "主板"},
            ]
        )
        manager.get_realtime_quote.side_effect = [
            _make_quote("600001", "新能源一号", 21.5),
            None,
        ]

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        payload = service.get_sector_constituents("新能源车", force_refresh=True, limit=10)

        self.assertEqual(payload["sector_name"], "新能源车")
        self.assertEqual(payload["total_matched"], 2)
        self.assertEqual(len(payload["constituents"]), 2)
        self.assertEqual(payload["constituents"][0]["stock_code"], "600001")
        self.assertEqual(payload["constituents"][0]["status"], "ok")
        self.assertEqual(payload["constituents"][1]["stock_code"], "600002")
        self.assertEqual(payload["constituents"][1]["status"], "error")
        self.assertEqual(payload["partial_errors"][0]["scope"], "sector_constituents_quote")
        manager.get_realtime_quote.assert_any_call("600001", use_non_critical_fallback=False)
        manager.get_realtime_quote.assert_any_call("600002", use_non_critical_fallback=False)

    def test_sector_constituents_limit_truncates_results(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519"],
            enable_realtime_quote=True,
        )
        manager = MagicMock()
        manager.get_stock_list.return_value = pd.DataFrame(
            [
                {"code": "600001", "name": "半导体一号", "industry": "半导体", "area": "上海", "market": "主板"},
                {"code": "600002", "name": "半导体二号", "industry": "半导体设备", "area": "深圳", "market": "主板"},
                {"code": "600003", "name": "半导体三号", "industry": "半导体材料", "area": "苏州", "market": "主板"},
            ]
        )
        manager.get_realtime_quote.side_effect = [
            _make_quote("600001", "半导体一号", 10.0),
            _make_quote("600002", "半导体二号", 12.0),
        ]

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        payload = service.get_sector_constituents("半导体", force_refresh=True, limit=2)

        self.assertEqual(payload["total_matched"], 3)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(len(payload["constituents"]), 2)
        self.assertEqual(manager.get_realtime_quote.call_count, 2)

    def test_sector_constituents_prefer_direct_sector_snapshot_when_available(self) -> None:
        config = SimpleNamespace(
            stock_list=["600519"],
            enable_realtime_quote=True,
        )
        manager = MagicMock()
        manager.get_sector_constituents.return_value = pd.DataFrame(
            [
                {
                    "code": "600111",
                    "name": "电子一号",
                    "industry": "电子设备",
                    "area": None,
                    "status": "ok",
                    "error_message": None,
                    "current_price": 18.6,
                    "change": 0.8,
                    "change_percent": 4.49,
                    "volume_ratio": None,
                    "turnover_rate": 3.2,
                    "amount": 123000000.0,
                    "source": "akshare_sector_detail",
                }
            ]
        )

        service = MarketMonitorService(
            manager_factory=lambda: manager,
            config_provider=lambda: config,
            now_provider=self.clock.now,
            monotonic=self.clock.monotonic,
            cache_ttl_seconds=3.0,
        )

        payload = service.get_sector_constituents("电子设备", force_refresh=True, limit=10)

        self.assertEqual(payload["total_matched"], 1)
        self.assertEqual(payload["constituents"][0]["stock_code"], "600111")
        self.assertEqual(payload["constituents"][0]["source"], "akshare_sector_detail")
        manager.get_stock_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
