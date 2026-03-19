# -*- coding: utf-8 -*-
"""
===================================
实时看盘聚合服务
===================================

职责：
1. 聚合 A 股自选股实时行情、指数、市场宽度和板块排行
2. 对外提供轻量内存缓存，减少高频重复请求
3. 在局部抓取失败时返回可降级的快照结构
"""

from __future__ import annotations

import copy
import concurrent.futures
import logging
import math
import re
import threading
import time
from datetime import datetime, time as dt_time
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from data_provider import DataFetcherManager
from src.config import Config, get_config
from src.core.trading_calendar import get_market_for_stock, is_market_open

logger = logging.getLogger(__name__)

_CN_TZ = ZoneInfo("Asia/Shanghai")


class MarketMonitorService:
    """Aggregate realtime market monitor data for the Web monitor page."""

    _instance: Optional["MarketMonitorService"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        manager_factory: Optional[Callable[[], DataFetcherManager]] = None,
        config_provider: Optional[Callable[[], Config]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        cache_ttl_seconds: float = 3.0,
        sector_cache_ttl_seconds: float = 15.0,
        quote_workers: int = 4,
        task_timeout_seconds: float = 8.0,
    ) -> None:
        self._manager_factory = manager_factory or DataFetcherManager
        self._config_provider = config_provider or get_config
        self._now_provider = now_provider or (lambda: datetime.now(_CN_TZ))
        self._monotonic = monotonic or time.monotonic
        self._cache_ttl_seconds = cache_ttl_seconds
        self._sector_cache_ttl_seconds = max(1.0, sector_cache_ttl_seconds)
        self._quote_workers = max(1, quote_workers)
        self._task_timeout_seconds = max(0.1, task_timeout_seconds)

        self._cache_lock = threading.RLock()
        self._cached_overviews: Dict[str, Dict[str, Any]] = {}
        self._cached_at: Dict[str, float] = {}
        self._inflight_events: Dict[str, threading.Event] = {}
        self._cached_sector_constituents: Dict[str, Dict[str, Any]] = {}
        self._sector_cached_at: Dict[str, float] = {}
        self._sector_inflight_events: Dict[str, threading.Event] = {}

    @classmethod
    def get_instance(cls) -> "MarketMonitorService":
        """Get process-wide singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _build_cache_key(include_watchlist: bool, include_summary: bool) -> str:
        return f"watchlist:{int(include_watchlist)}|summary:{int(include_summary)}"

    def get_overview(
        self,
        force_refresh: bool = False,
        include_watchlist: bool = True,
        include_summary: bool = True,
    ) -> Dict[str, Any]:
        """Return cached overview or build a fresh snapshot."""
        cache_key = self._build_cache_key(include_watchlist, include_summary)
        while True:
            with self._cache_lock:
                if not force_refresh and self._is_cache_fresh_locked(cache_key):
                    return copy.deepcopy(self._cached_overviews[cache_key])

                if cache_key not in self._inflight_events:
                    owner_event = threading.Event()
                    self._inflight_events[cache_key] = owner_event
                    break

                wait_event = self._inflight_events[cache_key]

            wait_event.wait(timeout=max(self._cache_ttl_seconds * 5, 10.0))

            with self._cache_lock:
                if self._is_cache_fresh_locked(cache_key):
                    return copy.deepcopy(self._cached_overviews[cache_key])

                if cache_key not in self._inflight_events:
                    force_refresh = False
                    continue

        try:
            overview = self._build_overview(
                include_watchlist=include_watchlist,
                include_summary=include_summary,
            )
        except Exception:
            logger.exception("Failed to build market overview snapshot")
            with self._cache_lock:
                owner_event = self._inflight_events.pop(cache_key, owner_event)
                owner_event.set()
            raise

        with self._cache_lock:
            self._cached_overviews[cache_key] = overview
            self._cached_at[cache_key] = self._monotonic()
            owner_event = self._inflight_events.pop(cache_key, owner_event)
            owner_event.set()

        return copy.deepcopy(overview)

    def _is_cache_fresh_locked(self, cache_key: str) -> bool:
        if cache_key not in self._cached_overviews:
            return False
        cached_at = self._cached_at.get(cache_key, 0.0)
        return (self._monotonic() - cached_at) < self._cache_ttl_seconds

    def _is_sector_cache_fresh_locked(self, cache_key: str) -> bool:
        if cache_key not in self._cached_sector_constituents:
            return False
        cached_at = self._sector_cached_at.get(cache_key, 0.0)
        return (self._monotonic() - cached_at) < self._sector_cache_ttl_seconds

    @staticmethod
    def _empty_market_stats() -> Dict[str, Optional[float]]:
        return {
            "up_count": None,
            "down_count": None,
            "flat_count": None,
            "limit_up_count": None,
            "limit_down_count": None,
            "total_amount": None,
        }

    def get_sector_constituents(
        self,
        sector_name: str,
        force_refresh: bool = False,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Return related A-share stock rows for a selected sector."""
        normalized_sector_name = str(sector_name or "").strip()
        safe_limit = max(1, min(int(limit), 10))
        cache_key = f"{normalized_sector_name}|{safe_limit}"

        while True:
            with self._cache_lock:
                if not force_refresh and self._is_sector_cache_fresh_locked(cache_key):
                    return copy.deepcopy(self._cached_sector_constituents[cache_key])

                if cache_key not in self._sector_inflight_events:
                    owner_event = threading.Event()
                    self._sector_inflight_events[cache_key] = owner_event
                    break

                wait_event = self._sector_inflight_events[cache_key]

            wait_event.wait(timeout=max(self._sector_cache_ttl_seconds * 3, 10.0))

            with self._cache_lock:
                if self._is_sector_cache_fresh_locked(cache_key):
                    return copy.deepcopy(self._cached_sector_constituents[cache_key])

                if cache_key not in self._sector_inflight_events:
                    force_refresh = False
                    continue

        try:
            payload = self._build_sector_constituents(normalized_sector_name, safe_limit)
        except Exception:
            logger.exception("Failed to build sector constituent snapshot for %s", normalized_sector_name)
            with self._cache_lock:
                owner_event = self._sector_inflight_events.pop(cache_key, owner_event)
                owner_event.set()
            raise

        with self._cache_lock:
            self._cached_sector_constituents[cache_key] = payload
            self._sector_cached_at[cache_key] = self._monotonic()
            owner_event = self._sector_inflight_events.pop(cache_key, owner_event)
            owner_event.set()

        return copy.deepcopy(payload)

    def _build_overview(
        self,
        include_watchlist: bool = True,
        include_summary: bool = True,
    ) -> Dict[str, Any]:
        config = self._config_provider()
        manager = self._manager_factory()
        current_dt = self._now_provider().astimezone(_CN_TZ)
        trading_date = current_dt.date().isoformat()
        session_state = self._resolve_session_state(current_dt)
        refresh_interval_seconds = 5 if session_state == "open" else 0

        raw_codes = [str(code).strip().upper() for code in getattr(config, "stock_list", []) if str(code).strip()]
        supported_codes, unsupported_codes = self._split_watchlist(raw_codes)

        partial_errors: List[Dict[str, str]] = []
        realtime_enabled = bool(getattr(config, "enable_realtime_quote", True))
        watchlist: List[Dict[str, Any]] = []
        indices: List[Dict[str, Any]] = []
        market_stats: Dict[str, Optional[float]] = self._empty_market_stats()
        top_sectors: List[Dict[str, Any]] = []
        bottom_sectors: List[Dict[str, Any]] = []

        if include_watchlist:
            watchlist = self._build_watchlist(
                manager=manager,
                supported_codes=supported_codes,
                realtime_enabled=realtime_enabled,
                partial_errors=partial_errors,
            )

        if include_summary:
            indices, market_stats, top_sectors, bottom_sectors = self._build_market_summary(
                partial_errors=partial_errors,
            )

        return {
            "trading_date": trading_date,
            "session_state": session_state,
            "realtime_enabled": realtime_enabled,
            "updated_at": self._now_provider().astimezone(_CN_TZ).isoformat(),
            "refresh_interval_seconds": refresh_interval_seconds,
            "watchlist_total": len(raw_codes),
            "supported_total": len(supported_codes),
            "unsupported_codes": unsupported_codes,
            "watchlist": watchlist,
            "indices": indices,
            "market_stats": market_stats,
            "top_sectors": top_sectors,
            "bottom_sectors": bottom_sectors,
            "partial_errors": partial_errors,
        }

    @staticmethod
    def _split_watchlist(raw_codes: List[str]) -> tuple[List[str], List[str]]:
        supported_codes: List[str] = []
        unsupported_codes: List[str] = []
        seen: set[str] = set()

        for code in raw_codes:
            if code in seen:
                continue
            seen.add(code)
            if get_market_for_stock(code) == "cn":
                supported_codes.append(code)
            else:
                unsupported_codes.append(code)

        return supported_codes, unsupported_codes

    def _build_watchlist(
        self,
        manager: DataFetcherManager,
        supported_codes: List[str],
        realtime_enabled: bool,
        partial_errors: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        watchlist: List[Dict[str, Any]] = []

        if not supported_codes:
            return watchlist

        if realtime_enabled:
            try:
                manager.prefetch_realtime_quotes(supported_codes)
            except Exception as exc:
                partial_errors.append(
                    {
                        "scope": "watchlist_prefetch",
                        "target": "watchlist",
                        "message": str(exc),
                    }
                )
        else:
            partial_errors.append(
                {
                    "scope": "watchlist_config",
                    "target": "ENABLE_REALTIME_QUOTE",
                    "message": "Realtime quote is disabled by configuration.",
                }
            )

        for code in supported_codes:
            if not realtime_enabled:
                watchlist.append(
                    {
                        "stock_code": code,
                        "stock_name": None,
                        "status": "error",
                        "error_message": "Realtime quote is disabled by configuration.",
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
                    }
                )
                continue

        if not realtime_enabled:
            return watchlist

        return self._fetch_watchlist_quotes_parallel(
            manager=manager,
            supported_codes=supported_codes,
            partial_errors=partial_errors,
        )

    @staticmethod
    def _build_error_item(code: str, message: str) -> Dict[str, Any]:
        return {
            "stock_code": code,
            "stock_name": None,
            "status": "error",
            "error_message": message,
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
        }

    @staticmethod
    def _compute_price_position(
        current_price: Optional[float],
        low: Optional[float],
        high: Optional[float],
    ) -> Optional[float]:
        if current_price is None or low is None or high is None:
            return None
        if high < low:
            return None
        if high == low:
            return 0.5
        position = (current_price - low) / (high - low)
        return max(0.0, min(1.0, position))

    def _fetch_watchlist_quotes_parallel(
        self,
        manager: DataFetcherManager,
        supported_codes: List[str],
        partial_errors: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not supported_codes:
            return []

        workers = min(self._quote_workers, len(supported_codes))
        batch_count = max(1, math.ceil(len(supported_codes) / max(workers, 1)))
        batch_timeout_seconds = self._task_timeout_seconds * batch_count
        futures: Dict[concurrent.futures.Future, tuple[int, str]] = {}
        results: List[Optional[Dict[str, Any]]] = [None] * len(supported_codes)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="monitor_quote")
        try:
            for index, code in enumerate(supported_codes):
                futures[executor.submit(self._fetch_single_watchlist_item, manager, code)] = (index, code)

            done, not_done = concurrent.futures.wait(
                futures.keys(),
                timeout=batch_timeout_seconds,
            )

            for future in done:
                index, code = futures[future]
                try:
                    result = future.result()
                    results[index] = result
                    if result.get("status") == "error":
                        partial_errors.append(
                            {
                                "scope": "watchlist_quote",
                                "target": code,
                                "message": result.get("error_message") or "No realtime quote available.",
                            }
                        )
                except Exception as exc:
                    partial_errors.append(
                        {
                            "scope": "watchlist_quote",
                            "target": code,
                            "message": str(exc),
                        }
                    )
                    results[index] = self._build_error_item(code, str(exc))

            for future in not_done:
                index, code = futures[future]
                partial_errors.append(
                        {
                            "scope": "watchlist_quote",
                            "target": code,
                            "message": f"Quote request timed out after {batch_timeout_seconds:.1f}s.",
                        }
                    )
                results[index] = self._build_error_item(
                    code,
                    f"Quote request timed out after {batch_timeout_seconds:.1f}s.",
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return [item for item in results if item is not None]

    def _build_market_summary(
        self,
        partial_errors: List[Dict[str, str]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Optional[float]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        empty_indices: List[Dict[str, Any]] = []
        empty_stats: Dict[str, Optional[float]] = {
            "up_count": None,
            "down_count": None,
            "flat_count": None,
            "limit_up_count": None,
            "limit_down_count": None,
            "total_amount": None,
        }
        empty_sectors: List[Dict[str, Any]] = []

        tasks = {
            "indices": self._fetch_indices_snapshot,
            "market_stats": self._fetch_market_stats_snapshot,
            "sector_rankings": self._fetch_sector_rankings_snapshot,
        }
        results: Dict[str, Any] = {
            "indices": empty_indices,
            "market_stats": empty_stats,
            "sector_rankings": (empty_sectors, empty_sectors),
        }

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="monitor_summary")
        try:
            future_map = {
                executor.submit(task): name
                for name, task in tasks.items()
            }

            done, not_done = concurrent.futures.wait(
                future_map.keys(),
                timeout=self._task_timeout_seconds,
            )

            for future in done:
                name = future_map[future]
                try:
                    value = future.result()
                    results[name] = value
                    if name == "indices" and not value:
                        partial_errors.append(
                            {
                                "scope": "indices",
                                "target": "cn",
                                "message": "No A-share index snapshot available.",
                            }
                        )
                    if name == "market_stats" and not any(v is not None for v in value.values()):
                        partial_errors.append(
                            {
                                "scope": "market_stats",
                                "target": "cn",
                                "message": "No A-share market breadth data available.",
                            }
                        )
                    if name == "sector_rankings" and not value[0] and not value[1]:
                        partial_errors.append(
                            {
                                "scope": "sector_rankings",
                                "target": "cn",
                                "message": "No A-share sector ranking data available.",
                            }
                        )
                except Exception as exc:
                    partial_errors.append(
                        {
                            "scope": name,
                            "target": "cn",
                            "message": str(exc),
                        }
                    )

            for future in not_done:
                name = future_map[future]
                partial_errors.append(
                    {
                        "scope": name,
                        "target": "cn",
                        "message": f"Request timed out after {self._task_timeout_seconds:.1f}s.",
                    }
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        top_sectors, bottom_sectors = results["sector_rankings"]
        return results["indices"], results["market_stats"], top_sectors, bottom_sectors

    def _fetch_indices_snapshot(self) -> List[Dict[str, Any]]:
        manager = self._manager_factory()
        try:
            indices = manager.get_main_indices(region="cn") or []
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        if not indices:
            logger.warning("No A-share index snapshot available for market monitor")
            return []

        normalized: List[Dict[str, Any]] = []
        for item in indices:
            normalized.append(
                {
                    "code": str(item.get("code") or ""),
                    "name": str(item.get("name") or ""),
                    "current": item.get("current"),
                    "change": item.get("change"),
                    "change_pct": item.get("change_pct"),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "prev_close": item.get("prev_close"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "amplitude": item.get("amplitude"),
                }
            )
        return normalized

    def _fetch_market_stats_snapshot(self) -> Dict[str, Optional[float]]:
        try:
            manager = self._manager_factory()
            stats = manager.get_market_stats() or {}
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        if not stats:
            logger.warning("No A-share market breadth data available for market monitor")

        return {
            "up_count": stats.get("up_count"),
            "down_count": stats.get("down_count"),
            "flat_count": stats.get("flat_count"),
            "limit_up_count": stats.get("limit_up_count"),
            "limit_down_count": stats.get("limit_down_count"),
            "total_amount": stats.get("total_amount"),
        }

    def _fetch_sector_rankings_snapshot(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            manager = self._manager_factory()
            top_sectors, bottom_sectors = manager.get_sector_rankings(n=5)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        if not top_sectors and not bottom_sectors:
            logger.warning("No A-share sector ranking data available for market monitor")

        normalized_top = [
            {"name": str(item.get("name") or ""), "change_pct": item.get("change_pct")}
            for item in (top_sectors or [])
        ]
        normalized_bottom = [
            {"name": str(item.get("name") or ""), "change_pct": item.get("change_pct")}
            for item in (bottom_sectors or [])
        ]
        return normalized_top, normalized_bottom

    def _build_sector_constituents(self, sector_name: str, limit: int) -> Dict[str, Any]:
        manager = self._manager_factory()
        partial_errors: List[Dict[str, str]] = []
        direct_rows = manager.get_sector_constituents(sector_name=sector_name, limit=limit)
        if direct_rows is not None and not direct_rows.empty:
            total_matched = len(direct_rows)
            constituents = self._build_sector_constituents_from_snapshot(direct_rows.head(limit))
            return {
                "sector_name": sector_name,
                "total_matched": total_matched,
                "limit": limit,
                "updated_at": self._now_provider().astimezone(_CN_TZ).isoformat(),
                "constituents": constituents,
                "partial_errors": partial_errors,
            }

        stock_list = manager.get_stock_list()
        if stock_list is None or stock_list.empty:
            partial_errors.append(
                {
                    "scope": "sector_constituents",
                    "target": sector_name,
                    "message": "No A-share stock list metadata available.",
                }
            )
            return {
                "sector_name": sector_name,
                "total_matched": 0,
                "limit": limit,
                "updated_at": self._now_provider().astimezone(_CN_TZ).isoformat(),
                "constituents": [],
                "partial_errors": partial_errors,
            }

        matched_rows = self._match_sector_stocks(stock_list, sector_name)
        total_matched = len(matched_rows)
        selected_rows = matched_rows.head(limit)
        constituents = self._fetch_sector_constituents_parallel(
            manager=manager,
            rows=selected_rows.to_dict("records"),
            partial_errors=partial_errors,
        )

        return {
            "sector_name": sector_name,
            "total_matched": total_matched,
            "limit": limit,
            "updated_at": self._now_provider().astimezone(_CN_TZ).isoformat(),
            "constituents": constituents,
            "partial_errors": partial_errors,
        }

    @staticmethod
    def _build_sector_constituents_from_snapshot(rows: pd.DataFrame) -> List[Dict[str, Any]]:
        """Convert direct sector detail rows into API payload items."""
        if rows is None or rows.empty:
            return []

        normalized = rows.copy()
        for column in [
            "code",
            "name",
            "industry",
            "area",
            "status",
            "error_message",
            "current_price",
            "change",
            "change_percent",
            "volume_ratio",
            "turnover_rate",
            "amount",
            "source",
        ]:
            if column not in normalized.columns:
                normalized[column] = None

        results: List[Dict[str, Any]] = []
        for _, row in normalized.iterrows():
            results.append(
                {
                    "stock_code": str(row.get("code") or ""),
                    "stock_name": row.get("name"),
                    "industry": row.get("industry"),
                    "area": row.get("area"),
                    "status": row.get("status") or "ok",
                    "error_message": row.get("error_message"),
                    "current_price": row.get("current_price"),
                    "change": row.get("change"),
                    "change_percent": row.get("change_percent"),
                    "volume_ratio": row.get("volume_ratio"),
                    "turnover_rate": row.get("turnover_rate"),
                    "amount": row.get("amount"),
                    "source": row.get("source"),
                }
            )
        return results

    @staticmethod
    def _normalize_sector_name(value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", "", text)
        for suffix in ("行业", "板块"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
        return text

    def _match_sector_stocks(self, stock_list: pd.DataFrame, sector_name: str) -> pd.DataFrame:
        if stock_list is None or stock_list.empty:
            return pd.DataFrame(columns=["code", "name", "industry", "area", "market"])

        normalized = stock_list.copy()
        for column in ["code", "name", "industry", "area", "market"]:
            if column not in normalized.columns:
                normalized[column] = None

        normalized["industry"] = normalized["industry"].fillna("").astype(str)
        normalized["industry_match_key"] = normalized["industry"].map(self._normalize_sector_name)
        normalized["sector_match_key"] = self._normalize_sector_name(sector_name)

        match_key = normalized["sector_match_key"].iloc[0] if not normalized.empty else ""
        if not match_key:
            return normalized.iloc[0:0]

        exact = normalized["industry_match_key"] == match_key
        contains = normalized["industry_match_key"].str.contains(re.escape(match_key), na=False)
        reverse_contains = normalized["industry_match_key"].map(lambda value: bool(value) and value in match_key)
        matched = normalized[exact | contains | reverse_contains].copy()
        if matched.empty:
            return matched

        matched["match_rank"] = 1
        matched.loc[exact[matched.index], "match_rank"] = 0
        return matched.sort_values(["match_rank", "industry", "code"]).drop(columns=["match_rank"]).reset_index(drop=True)

    def _fetch_sector_constituents_parallel(
        self,
        manager: DataFetcherManager,
        rows: List[Dict[str, Any]],
        partial_errors: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []

        workers = min(self._quote_workers, len(rows))
        batch_count = max(1, math.ceil(len(rows) / max(workers, 1)))
        batch_timeout_seconds = self._task_timeout_seconds * batch_count
        futures: Dict[concurrent.futures.Future, tuple[int, Dict[str, Any]]] = {}
        results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sector_detail")
        try:
            for index, row in enumerate(rows):
                futures[executor.submit(self._fetch_single_sector_constituent, manager, row)] = (index, row)

            done, not_done = concurrent.futures.wait(
                futures.keys(),
                timeout=batch_timeout_seconds,
            )

            for future in done:
                index, row = futures[future]
                code = str(row.get("code") or "")
                try:
                    result = future.result()
                    results[index] = result
                    if result.get("status") == "error":
                        partial_errors.append(
                            {
                                "scope": "sector_constituents_quote",
                                "target": code,
                                "message": result.get("error_message") or "No realtime quote available.",
                            }
                        )
                except Exception as exc:
                    partial_errors.append(
                        {
                            "scope": "sector_constituents_quote",
                            "target": code,
                            "message": str(exc),
                        }
                    )
                    results[index] = self._build_sector_constituent_error_item(row, str(exc))

            for future in not_done:
                index, row = futures[future]
                code = str(row.get("code") or "")
                timeout_message = f"Quote request timed out after {batch_timeout_seconds:.1f}s."
                partial_errors.append(
                    {
                        "scope": "sector_constituents_quote",
                        "target": code,
                        "message": timeout_message,
                    }
                )
                results[index] = self._build_sector_constituent_error_item(row, timeout_message)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        ordered = [item for item in results if item is not None]
        return sorted(
            ordered,
            key=lambda item: (
                item.get("status") == "error",
                -(item.get("change_percent") if isinstance(item.get("change_percent"), (int, float)) else -10_000),
                str(item.get("stock_code") or ""),
            ),
        )

    @staticmethod
    def _build_sector_constituent_error_item(row: Dict[str, Any], message: str) -> Dict[str, Any]:
        return {
            "stock_code": str(row.get("code") or ""),
            "stock_name": row.get("name"),
            "industry": row.get("industry"),
            "area": row.get("area"),
            "status": "error",
            "error_message": message,
            "current_price": None,
            "change": None,
            "change_percent": None,
            "volume_ratio": None,
            "turnover_rate": None,
            "amount": None,
            "source": None,
        }

    @classmethod
    def _fetch_single_sector_constituent(
        cls,
        manager: DataFetcherManager,
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        code = str(row.get("code") or "")
        quote = manager.get_realtime_quote(code, use_non_critical_fallback=False)
        if quote is None or not quote.has_basic_data():
            return cls._build_sector_constituent_error_item(row, "No realtime quote available.")

        return {
            "stock_code": code,
            "stock_name": getattr(quote, "name", None) or row.get("name"),
            "industry": row.get("industry"),
            "area": row.get("area"),
            "status": "ok",
            "error_message": None,
            "current_price": getattr(quote, "price", None),
            "change": getattr(quote, "change_amount", None),
            "change_percent": getattr(quote, "change_pct", None),
            "volume_ratio": getattr(quote, "volume_ratio", None),
            "turnover_rate": getattr(quote, "turnover_rate", None),
            "amount": getattr(quote, "amount", None),
            "source": getattr(getattr(quote, "source", None), "value", None),
        }

    @classmethod
    def _fetch_single_watchlist_item(
        cls,
        manager: DataFetcherManager,
        code: str,
    ) -> Dict[str, Any]:
        quote = manager.get_realtime_quote(code, use_non_critical_fallback=False)
        if quote is None or not quote.has_basic_data():
            return cls._build_error_item(code, "No realtime quote available.")

        return {
            "stock_code": code,
            "stock_name": getattr(quote, "name", None) or None,
            "status": "ok",
            "error_message": None,
            "current_price": getattr(quote, "price", None),
            "change": getattr(quote, "change_amount", None),
            "change_percent": getattr(quote, "change_pct", None),
            "open": getattr(quote, "open_price", None),
            "high": getattr(quote, "high", None),
            "low": getattr(quote, "low", None),
            "prev_close": getattr(quote, "pre_close", None),
            "volume": getattr(quote, "volume", None),
            "amount": getattr(quote, "amount", None),
            "volume_ratio": getattr(quote, "volume_ratio", None),
            "turnover_rate": getattr(quote, "turnover_rate", None),
            "amplitude": getattr(quote, "amplitude", None),
            "source": getattr(getattr(quote, "source", None), "value", None),
            "price_position": cls._compute_price_position(
                current_price=getattr(quote, "price", None),
                low=getattr(quote, "low", None),
                high=getattr(quote, "high", None),
            ),
        }

    @staticmethod
    def _resolve_session_state(current_dt: datetime) -> str:
        trading_date = current_dt.date()
        if not is_market_open("cn", trading_date):
            return "non_trading_day"

        current_time = current_dt.timetz().replace(tzinfo=None)
        if current_time < dt_time(9, 30):
            return "pre_open"
        if current_time < dt_time(11, 30):
            return "open"
        if current_time < dt_time(13, 0):
            return "midday_break"
        if current_time < dt_time(15, 0):
            return "open"
        return "after_close"


def get_market_monitor_service() -> MarketMonitorService:
    """Return the market monitor singleton."""
    return MarketMonitorService.get_instance()
