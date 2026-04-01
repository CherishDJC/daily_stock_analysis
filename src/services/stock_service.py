# -*- coding: utf-8 -*-
"""
===================================
股票数据服务层
===================================

职责：
1. 封装股票数据获取逻辑
2. 提供实时行情和历史数据接口
"""

import logging
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Dict, Any, Tuple

import pandas as pd

from src.repositories.stock_repo import StockRepository

logger = logging.getLogger(__name__)


class StockService:
    """
    股票数据服务

    封装股票数据获取的业务逻辑
    """

    def __init__(
        self,
        repo: Optional[StockRepository] = None,
        manager_factory: Optional[Callable[[], Any]] = None,
        today_provider: Optional[Callable[[], date]] = None,
        recent_refresh_days: int = 5,
    ):
        """初始化股票数据服务"""
        self.repo = repo or StockRepository()
        self._manager_factory = manager_factory
        self._today_provider = today_provider or date.today
        self._recent_refresh_days = max(1, recent_refresh_days)

    def get_realtime_quote(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票实时行情

        Args:
            stock_code: 股票代码

        Returns:
            实时行情数据字典
        """
        try:
            # 调用数据获取器获取实时行情
            from data_provider.base import DataFetcherManager

            manager = DataFetcherManager()
            quote = manager.get_realtime_quote(stock_code)

            if quote is None:
                logger.warning(f"获取 {stock_code} 实时行情失败")
                return None

            # UnifiedRealtimeQuote 是 dataclass，使用 getattr 安全访问字段
            # 字段映射: UnifiedRealtimeQuote -> API 响应
            # - code -> stock_code
            # - name -> stock_name
            # - price -> current_price
            # - change_amount -> change
            # - change_pct -> change_percent
            # - open_price -> open
            # - high -> high
            # - low -> low
            # - pre_close -> prev_close
            # - volume -> volume
            # - amount -> amount
            return {
                "stock_code": getattr(quote, "code", stock_code),
                "stock_name": getattr(quote, "name", None),
                "current_price": getattr(quote, "price", 0.0) or 0.0,
                "change": getattr(quote, "change_amount", None),
                "change_percent": getattr(quote, "change_pct", None),
                "open": getattr(quote, "open_price", None),
                "high": getattr(quote, "high", None),
                "low": getattr(quote, "low", None),
                "prev_close": getattr(quote, "pre_close", None),
                "volume": getattr(quote, "volume", None),
                "amount": getattr(quote, "amount", None),
                "update_time": datetime.now().isoformat(),
            }

        except ImportError:
            logger.warning("DataFetcherManager 未找到，使用占位数据")
            return self._get_placeholder_quote(stock_code)
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}", exc_info=True)
            return None

    def get_history_data(
        self,
        stock_code: str,
        period: str = "daily",
        days: int = 30
    ) -> Dict[str, Any]:
        """
        获取股票历史行情

        Args:
            stock_code: 股票代码
            period: K 线周期 (daily/weekly/monthly)
            days: 获取天数

        Returns:
            历史行情数据字典

        Raises:
            ValueError: 当 period 不是 daily 时抛出（weekly/monthly 暂未实现）
        """
        # 验证 period 参数，只支持 daily
        if period != "daily":
            raise ValueError(
                f"暂不支持 '{period}' 周期，目前仅支持 'daily'。"
                "weekly/monthly 聚合功能将在后续版本实现。"
            )

        try:
            # 调用数据获取器获取历史数据
            manager = self._create_manager()
            df, source = self._get_cached_daily_history(manager, stock_code, days)

            if df is None or df.empty:
                logger.warning(f"获取 {stock_code} 历史数据失败")
                return {"stock_code": stock_code, "period": period, "data": []}

            # 获取股票名称
            try:
                stock_name = manager.get_stock_name(stock_code)
            except Exception as e:
                logger.warning("获取 %s 股票名称失败，回退为代码: %s", stock_code, e)
                stock_name = stock_code

            # 转换为响应格式
            data = []
            for _, row in df.iterrows():
                date_val = row.get("date")
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                else:
                    date_str = str(date_val)

                data.append({
                    "date": date_str,
                    "open": self._to_float(row.get("open"), default=0.0),
                    "high": self._to_float(row.get("high"), default=0.0),
                    "low": self._to_float(row.get("low"), default=0.0),
                    "close": self._to_float(row.get("close"), default=0.0),
                    "volume": self._to_float(row.get("volume")),
                    "amount": self._to_float(row.get("amount")),
                    "change_percent": self._to_float(row.get("pct_chg")),
                })

            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "period": period,
                "data": data,
            }

        except ImportError:
            logger.warning("DataFetcherManager 未找到，返回空数据")
            return {"stock_code": stock_code, "period": period, "data": []}
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}", exc_info=True)
            return {"stock_code": stock_code, "period": period, "data": []}

    def get_intraday_data(
        self,
        stock_code: str,
        interval: str = "1",
        limit: int = 240,
        include_trades: bool = True,
    ) -> Dict[str, Any]:
        """
        Get intraday minute bars and recent trades.

        Args:
            stock_code: 股票代码
            interval: 分钟周期，支持 1/5/15/30/60
            limit: 返回最近多少根分钟K
            include_trades: 是否附带最近逐笔成交

        Returns:
            分钟级行情响应字典
        """
        if interval not in {"1", "5", "15", "30", "60"}:
            raise ValueError(f"暂不支持 '{interval}' 分钟周期，仅支持 1/5/15/30/60。")

        try:
            manager = self._create_manager()
            bars_df, source = manager.get_minute_data(
                stock_code=stock_code,
                interval=interval,
                limit=limit,
            )

            try:
                stock_name = manager.get_stock_name(stock_code)
            except Exception as e:
                logger.warning("获取 %s 股票名称失败，回退为代码: %s", stock_code, e)
                stock_name = stock_code

            bars = []
            if bars_df is not None and not bars_df.empty:
                for _, row in bars_df.iterrows():
                    bars.append(
                        {
                            "timestamp": str(row.get("timestamp")),
                            "open": self._to_float(row.get("open"), default=0.0) or 0.0,
                            "high": self._to_float(row.get("high"), default=0.0) or 0.0,
                            "low": self._to_float(row.get("low"), default=0.0) or 0.0,
                            "close": self._to_float(row.get("close"), default=0.0) or 0.0,
                            "volume": self._to_float(row.get("volume")),
                            "amount": self._to_float(row.get("amount")),
                            "change_percent": self._to_float(row.get("change_percent")),
                        }
                    )

            trades = []
            trades_source: Optional[str] = None
            if include_trades:
                try:
                    trade_df, trades_source = manager.get_intraday_trades(stock_code=stock_code, limit=10)
                    if trade_df is not None and not trade_df.empty:
                        for _, row in trade_df.iterrows():
                            trades.append(
                                {
                                    "timestamp": str(row.get("timestamp")),
                                    "price": self._to_float(row.get("price"), default=0.0) or 0.0,
                                    "volume": self._to_float(row.get("volume")),
                                    "side": row.get("side"),
                                }
                            )
                except Exception as e:
                    logger.warning("获取 %s 逐笔成交失败，降级为空列表: %s", stock_code, e)

            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "interval": interval,
                "source": source,
                "trades_source": trades_source,
                "updated_at": datetime.now().isoformat(),
                "bars": bars,
                "trades": trades,
            }

        except ImportError:
            logger.warning("DataFetcherManager 未找到，返回空分钟数据")
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "interval": interval,
                "source": None,
                "trades_source": None,
                "updated_at": datetime.now().isoformat(),
                "bars": [],
                "trades": [],
            }
        except Exception as e:
            logger.error(f"获取分钟数据失败: {e}", exc_info=True)
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "interval": interval,
                "source": None,
                "trades_source": None,
                "updated_at": datetime.now().isoformat(),
                "bars": [],
                "trades": [],
            }

    def get_fund_flow_data(
        self,
        stock_code: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        获取个股主力资金流向明细。

        Args:
            stock_code: 股票代码
            limit: 返回最近多少条记录

        Returns:
            资金流明细响应字典
        """
        try:
            import akshare as ak

            market = self._resolve_cn_market(stock_code)
            raw_df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            if raw_df is None or raw_df.empty:
                return {
                    "stock_code": stock_code,
                    "stock_name": stock_code,
                    "source": "AkShare",
                    "updated_at": datetime.now().isoformat(),
                    "data": [],
                }

            try:
                stock_name = self._create_manager().get_stock_name(stock_code)
            except Exception as e:
                logger.warning("获取 %s 股票名称失败，回退为代码: %s", stock_code, e)
                stock_name = stock_code

            normalized = raw_df.copy()
            if "日期" in normalized.columns:
                normalized["日期"] = pd.to_datetime(normalized["日期"], errors="coerce")
                normalized = normalized.dropna(subset=["日期"]).sort_values("日期", ascending=False)
            normalized = normalized.head(limit)

            data = []
            for _, row in normalized.iterrows():
                trade_date = row.get("日期")
                if hasattr(trade_date, "strftime"):
                    date_str = trade_date.strftime("%Y-%m-%d")
                else:
                    date_str = str(trade_date)

                data.append(
                    {
                        "date": date_str,
                        "close": self._to_float(row.get("收盘价")),
                        "change_percent": self._to_float(row.get("涨跌幅")),
                        "main_net_inflow": self._to_float(row.get("主力净流入-净额")),
                        "main_net_inflow_ratio": self._to_float(row.get("主力净流入-净占比")),
                        "super_large_net_inflow": self._to_float(row.get("超大单净流入-净额")),
                        "super_large_net_inflow_ratio": self._to_float(row.get("超大单净流入-净占比")),
                        "large_net_inflow": self._to_float(row.get("大单净流入-净额")),
                        "large_net_inflow_ratio": self._to_float(row.get("大单净流入-净占比")),
                        "medium_net_inflow": self._to_float(row.get("中单净流入-净额")),
                        "medium_net_inflow_ratio": self._to_float(row.get("中单净流入-净占比")),
                        "small_net_inflow": self._to_float(row.get("小单净流入-净额")),
                        "small_net_inflow_ratio": self._to_float(row.get("小单净流入-净占比")),
                    }
                )

            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "source": "AkShare",
                "updated_at": datetime.now().isoformat(),
                "data": data,
            }
        except ImportError:
            logger.warning("AkShare 未安装，返回空资金流数据")
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "source": None,
                "updated_at": datetime.now().isoformat(),
                "data": [],
            }
        except Exception as e:
            logger.error(f"获取资金流向失败: {e}", exc_info=True)
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "source": None,
                "updated_at": datetime.now().isoformat(),
                "data": [],
            }

    def get_stock_meta_data(self, stock_code: str) -> Dict[str, Any]:
        """
        获取股票基础信息与所属板块摘要。

        Args:
            stock_code: 股票代码

        Returns:
            基础信息响应字典
        """
        manager = self._create_manager()

        try:
            stock_name = manager.get_stock_name(stock_code)
        except Exception as e:
            logger.warning("获取 %s 股票名称失败，回退为代码: %s", stock_code, e)
            stock_name = stock_code

        info: Dict[str, Any] = {}
        boards: list[str] = []
        source: Optional[str] = None

        try:
            raw_info = manager.get_base_info(stock_code) or {}
            if isinstance(raw_info, dict):
                info = raw_info
                source = str(raw_info.get("source") or source or "").strip() or None
        except Exception as e:
            logger.warning("获取 %s 基础信息失败，降级为空: %s", stock_code, e)

        try:
            board_df = manager.get_belong_board(stock_code)
            if board_df is not None and not board_df.empty:
                boards = self._extract_board_names(board_df)
        except Exception as e:
            logger.warning("获取 %s 所属板块失败，降级为空: %s", stock_code, e)

        return {
            "stock_code": stock_code,
            "stock_name": self._first_non_empty(
                stock_name,
                info.get("name"),
                info.get("股票名称"),
            ) or stock_code,
            "source": source,
            "updated_at": datetime.now().isoformat(),
            "industry": self._first_non_empty(info.get("industry"), info.get("行业"), info.get("所属行业")),
            "market": self._first_non_empty(info.get("market"), info.get("市场"), info.get("exchange"), info.get("交易所")),
            "area": self._first_non_empty(info.get("area"), info.get("地域"), info.get("province"), info.get("省份")),
            "list_date": self._normalize_date_value(
                self._first_non_empty(info.get("list_date"), info.get("上市日期"), info.get("found_date"), info.get("setup_date"))
            ),
            "full_name": self._first_non_empty(info.get("fullname"), info.get("full_name"), info.get("公司名称"), info.get("name")),
            "website": self._first_non_empty(info.get("website"), info.get("公司网站")),
            "main_business": self._first_non_empty(info.get("main_business"), info.get("主营业务"), info.get("business_scope")),
            "employees": self._to_int(info.get("employees"), default=None),
            "pe_ratio": self._to_float(self._first_non_empty(info.get("pe_ratio"), info.get("市盈率"), info.get("市盈率(动态)"))),
            "pb_ratio": self._to_float(self._first_non_empty(info.get("pb_ratio"), info.get("市净率"), info.get("市净率MRQ"))),
            "total_market_value": self._to_float(self._first_non_empty(info.get("total_mv"), info.get("总市值"))),
            "circulating_market_value": self._to_float(self._first_non_empty(info.get("circ_mv"), info.get("流通市值"))),
            "belong_boards": boards,
        }

    def _create_manager(self):
        """Create a data fetcher manager lazily to keep import costs local."""
        if self._manager_factory is not None:
            return self._manager_factory()

        from data_provider.base import DataFetcherManager

        return DataFetcherManager()

    def _get_cached_daily_history(self, manager, stock_code: str, days: int) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Return history with DB-first stable bars and a small recent network refresh.

        Stable daily bars from yesterday backwards are read from local DB first.
        Only the recent volatile window or missing historical gaps trigger network calls.
        """
        today = self._today_provider()
        stable_end_date = today - timedelta(days=1)
        cached_stable_df = self._get_cached_rows_dataframe(stock_code, stable_end_date, days)
        recent_df = pd.DataFrame()
        source: Optional[str] = None

        try:
            if len(cached_stable_df) < max(days - 1, 0):
                recent_df, source = self._fetch_daily_dataframe(manager, stock_code, days)
                self._persist_stable_history(stock_code, recent_df, source, stable_end_date)
            else:
                recent_window_days = min(days, self._recent_refresh_days)
                recent_df, source = self._fetch_daily_dataframe(manager, stock_code, recent_window_days)
                stable_target = days - 1 if self._frame_contains_date(recent_df, today) else days
                if len(cached_stable_df) < stable_target:
                    recent_df, source = self._fetch_daily_dataframe(manager, stock_code, days)
                    self._persist_stable_history(stock_code, recent_df, source, stable_end_date)
        except Exception as e:
            logger.warning("获取 %s 最近日线失败，回退到本地缓存: %s", stock_code, e)

        merged = self._merge_history_frames(cached_stable_df, recent_df, days)
        if merged.empty:
            return cached_stable_df.tail(days).reset_index(drop=True), source
        return merged, source

    def _get_cached_rows_dataframe(self, stock_code: str, end_date: date, limit: int) -> pd.DataFrame:
        rows = self.repo.get_latest_until(stock_code, end_date=end_date, limit=limit)
        if not rows:
            return pd.DataFrame()

        data = []
        for row in rows:
            data.append({
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "amount": row.amount,
                "pct_chg": row.pct_chg,
            })
        return self._normalize_history_frame(pd.DataFrame(data))

    def _fetch_daily_dataframe(self, manager, stock_code: str, days: int) -> Tuple[pd.DataFrame, Optional[str]]:
        df, source = manager.get_daily_data(
            stock_code=stock_code,
            start_date=None,
            end_date=None,
            days=days,
        )
        return self._normalize_history_frame(df), source

    def _persist_stable_history(self, stock_code: str, df: pd.DataFrame, source: Optional[str], stable_end_date: date) -> None:
        if df is None or df.empty:
            return

        save_df = df.copy()
        save_df["date"] = pd.to_datetime(save_df["date"], errors="coerce")
        save_df = save_df.dropna(subset=["date"])
        save_df = save_df[save_df["date"].dt.date <= stable_end_date]
        if save_df.empty:
            return

        save_df["date"] = save_df["date"].dt.date
        self.repo.save_dataframe(save_df, stock_code, data_source=source or "Unknown")

    def _merge_history_frames(self, cached_stable_df: pd.DataFrame, recent_df: pd.DataFrame, days: int) -> pd.DataFrame:
        frames = []
        if cached_stable_df is not None and not cached_stable_df.empty:
            frames.append(cached_stable_df)
        if recent_df is not None and not recent_df.empty:
            frames.append(recent_df)
        if not frames:
            return pd.DataFrame()

        merged = pd.concat(frames, ignore_index=True)
        merged = self._normalize_history_frame(merged)
        return merged.tail(days).reset_index(drop=True)

    def _normalize_history_frame(self, df: Optional[pd.DataFrame]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"])

        normalized = df.copy()
        for column in ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]:
            if column not in normalized.columns:
                normalized[column] = None

        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
        normalized = normalized.dropna(subset=["date"])
        normalized = normalized.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        return normalized.reset_index(drop=True)

    @staticmethod
    def _frame_contains_date(df: pd.DataFrame, target_date: date) -> bool:
        if df is None or df.empty or "date" not in df.columns:
            return False
        return bool((pd.to_datetime(df["date"], errors="coerce").dt.date == target_date).any())

    @staticmethod
    def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except TypeError:
            pass
        return float(value)

    @staticmethod
    def _to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except TypeError:
            pass
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value in (None, "", [], {}):
                continue
            return value
        return None

    @staticmethod
    def _normalize_date_value(value: Any) -> Optional[str]:
        if value in (None, "", [], {}):
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) == 8 and text.isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        return text

    @staticmethod
    def _extract_board_names(board_df: pd.DataFrame) -> list[str]:
        names: list[str] = []
        if board_df is None or board_df.empty:
            return names

        for _, row in board_df.iterrows():
            for key in row.index:
                key_text = str(key)
                if "板块" in key_text or "名称" in key_text:
                    value = row.get(key)
                    if value not in (None, ""):
                        board_name = str(value).strip()
                        if board_name and board_name not in names:
                            names.append(board_name)
                    break
        return names[:10]

    @staticmethod
    def _resolve_cn_market(stock_code: str) -> str:
        """Infer exchange code for Eastmoney-style CN stock APIs."""
        code = (stock_code or "").strip()
        if code.startswith("6"):
            return "sh"
        if code.startswith(("4", "8")) or code[:2] in {"43", "83", "87", "88", "92"}:
            return "bj"
        return "sz"

    def _get_placeholder_quote(self, stock_code: str) -> Dict[str, Any]:
        """
        获取占位行情数据（用于测试）

        Args:
            stock_code: 股票代码

        Returns:
            占位行情数据
        """
        return {
            "stock_code": stock_code,
            "stock_name": f"股票{stock_code}",
            "current_price": 0.0,
            "change": None,
            "change_percent": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
            "volume": None,
            "amount": None,
            "update_time": datetime.now().isoformat(),
        }
