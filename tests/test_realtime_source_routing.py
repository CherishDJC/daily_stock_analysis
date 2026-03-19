# -*- coding: utf-8 -*-
"""Tests for realtime source routing and market overview fetcher ordering."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from data_provider.base import BaseFetcher, DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


def _make_quote(source: RealtimeSource) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        source=source,
        price=1800.0,
        change_pct=1.2,
        change_amount=21.3,
        open_price=1788.0,
        high=1805.0,
        low=1780.0,
        pre_close=1778.7,
    )


class _NoopFetcher(BaseFetcher):
    name = "NoopFetcher"
    priority = 99

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code: str):
        raise NotImplementedError


class FakeAkshareFetcher(_NoopFetcher):
    name = "AkshareFetcher"
    priority = 1

    def __init__(
        self,
        result_by_source: dict[str, UnifiedRealtimeQuote | None],
        summary_data=None,
        base_info=None,
    ) -> None:
        self.result_by_source = result_by_source
        self.calls: list[str] = []
        self.summary_data = summary_data or []
        self.base_info = base_info
        self.market_stats = None
        self.base_info_calls = 0
        self.stock_list = None
        self.sector_constituents = None

    def get_realtime_quote(self, stock_code: str, source: str = "em"):
        self.calls.append(source)
        return self.result_by_source.get(source)

    def get_main_indices(self, region: str = "cn"):
        return self.summary_data

    def get_market_stats(self):
        return self.market_stats

    def get_base_info(self, stock_code: str):
        self.base_info_calls += 1
        return self.base_info

    def get_stock_list(self):
        return self.stock_list

    def get_sector_constituents(self, sector_name: str, limit: int = 10):
        return self.sector_constituents


class FakeEfinanceFetcher(_NoopFetcher):
    name = "EfinanceFetcher"
    priority = 0

    def __init__(self, quote=None, summary_data=None, base_info=None) -> None:
        self.quote = quote
        self.calls = 0
        self.summary_calls = 0
        self.summary_data = summary_data or []
        self.base_info = base_info
        self.market_stats = None
        self.base_info_calls = 0
        self.stock_list = None

    def get_realtime_quote(self, stock_code: str):
        self.calls += 1
        return self.quote

    def get_main_indices(self, region: str = "cn"):
        self.summary_calls += 1
        return self.summary_data

    def get_market_stats(self):
        return self.market_stats

    def get_base_info(self, stock_code: str):
        self.base_info_calls += 1
        return self.base_info

    def get_stock_list(self):
        return self.stock_list


class FakeTushareFetcher(_NoopFetcher):
    name = "TushareFetcher"
    priority = -1

    def __init__(self, quote=None, summary_data=None, base_info=None) -> None:
        self.quote = quote
        self.calls = 0
        self.summary_calls = 0
        self.summary_data = summary_data or []
        self.base_info = base_info
        self.market_stats = None
        self.base_info_calls = 0
        self.stock_list = None

    def get_realtime_quote(self, stock_code: str):
        self.calls += 1
        return self.quote

    def get_main_indices(self, region: str = "cn"):
        self.summary_calls += 1
        return self.summary_data

    def get_market_stats(self):
        return self.market_stats

    def get_base_info(self, stock_code: str):
        self.base_info_calls += 1
        return self.base_info

    def get_stock_list(self):
        return self.stock_list


class FakeBaostockFetcher(_NoopFetcher):
    name = "BaostockFetcher"
    priority = 3

    def __init__(self, stock_list=None) -> None:
        self.stock_list = stock_list

    def get_stock_list(self):
        return self.stock_list


class FakeReferenceCacheRepo:
    def __init__(self, initial=None) -> None:
        self.store = initial or {}
        self.writes = []

    def get_json(self, namespace: str, cache_key: str):
        return self.store.get((namespace, cache_key))

    def set_json(self, namespace: str, cache_key: str, payload, ttl_seconds: int, source=None) -> None:
        self.store[(namespace, cache_key)] = payload
        self.writes.append((namespace, cache_key, ttl_seconds, source))


class RealtimeSourceRoutingTestCase(unittest.TestCase):
    def test_primary_chain_only_uses_tencent_and_sina(self) -> None:
        akshare = FakeAkshareFetcher({"tencent": None, "sina": None, "em": _make_quote(RealtimeSource.AKSHARE_EM)})
        efinance = FakeEfinanceFetcher(quote=_make_quote(RealtimeSource.EFINANCE))
        tushare = FakeTushareFetcher(quote=_make_quote(RealtimeSource.TUSHARE))
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])
        config = SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="tushare,efinance,akshare_em,tencent,akshare_sina")

        with patch("src.config.get_config", return_value=config):
            quote = manager.get_realtime_quote("600519", use_non_critical_fallback=False)

        self.assertIsNone(quote)
        self.assertEqual(akshare.calls, ["tencent", "sina"])
        self.assertEqual(tushare.calls, 0)
        self.assertEqual(efinance.calls, 0)

    def test_non_critical_fallback_keeps_tushare_before_efinance_and_akshare_em(self) -> None:
        akshare = FakeAkshareFetcher({"tencent": None, "sina": None, "em": _make_quote(RealtimeSource.AKSHARE_EM)})
        efinance = FakeEfinanceFetcher(quote=None)
        tushare = FakeTushareFetcher(quote=_make_quote(RealtimeSource.TUSHARE))
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])
        config = SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="tencent,akshare_sina")

        with patch("src.config.get_config", return_value=config):
            quote = manager.get_realtime_quote("600519", use_non_critical_fallback=True)

        self.assertIsNotNone(quote)
        self.assertEqual(getattr(quote.source, "value", None), "tushare")
        self.assertEqual(akshare.calls[:2], ["tencent", "sina"])
        self.assertEqual(tushare.calls, 1)
        self.assertGreaterEqual(len(akshare.calls), 2)

    def test_market_overview_prefers_akshare_before_higher_priority_fallbacks(self) -> None:
        akshare = FakeAkshareFetcher({}, summary_data=[{"code": "sh000001"}])
        efinance = FakeEfinanceFetcher(summary_data=[{"code": "ef"}])
        tushare = FakeTushareFetcher(summary_data=[{"code": "ts"}])
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])

        result = manager.get_main_indices(region="cn")

        self.assertEqual(result, [{"code": "sh000001"}])
        self.assertEqual(tushare.summary_calls, 0)
        self.assertEqual(efinance.summary_calls, 0)

    def test_market_stats_prefers_tushare_before_akshare(self) -> None:
        akshare = FakeAkshareFetcher({})
        akshare.market_stats = {"up_count": 1}
        efinance = FakeEfinanceFetcher()
        efinance.market_stats = {"up_count": 2}
        tushare = FakeTushareFetcher()
        tushare.market_stats = {"up_count": 3}
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])

        result = manager.get_market_stats()

        self.assertEqual(result, {"up_count": 3})

    def test_base_info_prefers_tushare_when_available(self) -> None:
        akshare = FakeAkshareFetcher({}, base_info={"source": "akshare"})
        efinance = FakeEfinanceFetcher(base_info={"source": "efinance", "name": "贵州茅台"})
        tushare = FakeTushareFetcher(base_info={"source": "tushare", "name": "贵州茅台"})
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare], reference_cache_repo=FakeReferenceCacheRepo())

        result = manager.get_base_info("600519")

        self.assertEqual(result["source"], "tushare")
        self.assertEqual(result["name"], "贵州茅台")

    def test_base_info_can_supplement_missing_name_from_later_fetcher(self) -> None:
        akshare = FakeAkshareFetcher({}, base_info=None)
        efinance = FakeEfinanceFetcher(base_info={"source": "efinance", "name": "贵州茅台", "industry": "白酒"})
        tushare = FakeTushareFetcher(base_info={"source": "tushare", "dividends": [{"cash_div_tax": 30.0}]})
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare], reference_cache_repo=FakeReferenceCacheRepo())

        result = manager.get_base_info("600519")

        self.assertEqual(result["source"], "tushare")
        self.assertEqual(result["name"], "贵州茅台")
        self.assertEqual(result["industry"], "白酒")
        self.assertEqual(result["dividends"][0]["cash_div_tax"], 30.0)

    def test_base_info_uses_reference_cache_before_fetchers(self) -> None:
        cache_repo = FakeReferenceCacheRepo({
            ("base_info", "600519"): {"source": "cache", "name": "贵州茅台"},
        })
        akshare = FakeAkshareFetcher({}, base_info={"source": "akshare"})
        efinance = FakeEfinanceFetcher(base_info={"source": "efinance"})
        tushare = FakeTushareFetcher(base_info={"source": "tushare"})
        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare], reference_cache_repo=cache_repo)

        result = manager.get_base_info("600519")

        self.assertEqual(result["source"], "cache")
        self.assertEqual(tushare.base_info_calls, 0)
        self.assertEqual(efinance.base_info_calls, 0)
        self.assertEqual(akshare.base_info_calls, 0)

    def test_stock_name_uses_reference_cache_before_realtime_quote(self) -> None:
        cache_repo = FakeReferenceCacheRepo({
            ("stock_name", "600519"): "贵州茅台",
        })
        akshare = FakeAkshareFetcher({"tencent": _make_quote(RealtimeSource.AKSHARE_QQ)})
        manager = DataFetcherManager(fetchers=[akshare], reference_cache_repo=cache_repo)

        result = manager.get_stock_name("600519")

        self.assertEqual(result, "贵州茅台")
        self.assertEqual(akshare.calls, [])

    def test_stock_list_ignores_invalid_cached_metadata_and_refetches(self) -> None:
        cache_repo = FakeReferenceCacheRepo({
            ("stock_list", "a_share_active"): [
                {"code": "000001", "name": "上证综合指数", "industry": None, "area": None, "market": None},
            ],
        })
        tushare = FakeTushareFetcher()
        tushare.stock_list = pd.DataFrame(
            [
                {"code": "600519", "name": "贵州茅台", "industry": "白酒", "area": "贵州", "market": "主板"},
                {"code": "000858", "name": "五粮液", "industry": "白酒", "area": "四川", "market": "主板"},
            ]
        )
        baostock = FakeBaostockFetcher(
            stock_list=pd.DataFrame(
                [
                    {"code": "000001", "name": "上证综合指数"},
                ]
            )
        )
        manager = DataFetcherManager(fetchers=[baostock, tushare], reference_cache_repo=cache_repo)

        result = manager.get_stock_list()

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["industry"], "白酒")
        self.assertEqual(cache_repo.writes[-1][0], "stock_list")
        self.assertEqual(cache_repo.writes[-1][3], "TushareFetcher")

    def test_sector_constituents_prefer_akshare_direct_detail(self) -> None:
        akshare = FakeAkshareFetcher({})
        akshare.sector_constituents = pd.DataFrame(
            [
                {"code": "600001", "name": "半导体一号", "industry": "半导体", "current_price": 12.3},
                {"code": "600002", "name": "半导体二号", "industry": "半导体", "current_price": 11.8},
            ]
        )
        manager = DataFetcherManager(fetchers=[akshare])

        result = manager.get_sector_constituents("半导体", limit=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["code"], "600001")


if __name__ == "__main__":
    unittest.main()
