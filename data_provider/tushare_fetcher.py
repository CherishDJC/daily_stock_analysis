# -*- coding: utf-8 -*-
"""
===================================
TushareFetcher - 备用数据源 1 (Priority 2)
===================================

数据来源：Tushare Pro API（挖地兔）
特点：需要 Token、有请求配额限制
优点：数据质量高、接口稳定

流控策略：
1. 实现"每分钟调用计数器"
2. 超过免费配额（80次/分）时，强制休眠到下一分钟
3. 使用 tenacity 实现指数退避重试
"""

import json as _json
import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, RateLimitError, STANDARD_COLUMNS
from .realtime_types import UnifiedRealtimeQuote
from src.config import get_config
import os

logger = logging.getLogger(__name__)


# ETF code prefixes by exchange
# Shanghai: 51xxxx, 52xxxx, 56xxxx, 58xxxx
# Shenzhen: 15xxxx, 16xxxx, 18xxxx
_ETF_SH_PREFIXES = ('51', '52', '56', '58')
_ETF_SZ_PREFIXES = ('15', '16', '18')
_ETF_ALL_PREFIXES = _ETF_SH_PREFIXES + _ETF_SZ_PREFIXES


def _is_etf_code(stock_code: str) -> bool:
    """
    Check if the code is an ETF fund code.

    ETF code ranges:
    - Shanghai ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - Shenzhen ETF: 15xxxx, 16xxxx, 18xxxx
    """
    code = stock_code.strip().split('.')[0]
    return code.startswith(_ETF_ALL_PREFIXES) and len(code) == 6


def _is_us_code(stock_code: str) -> bool:
    """
    判断代码是否为美股
    
    美股代码规则：
    - 1-5个大写字母，如 'AAPL', 'TSLA'
    - 可能包含 '.'，如 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


class TushareFetcher(BaseFetcher):
    """
    Tushare Pro 数据源实现
    
    优先级：2
    数据来源：Tushare Pro API
    
    关键策略：
    - 每分钟调用计数器，防止超出配额
    - 超过 80 次/分钟时强制等待
    - 失败后指数退避重试
    
    配额说明（Tushare 免费用户）：
    - 每分钟最多 80 次请求
    - 每天最多 500 次请求
    """
    
    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "2"))  # 默认优先级，会在 __init__ 中根据配置动态调整

    def __init__(self, rate_limit_per_minute: int = 80):
        """
        初始化 TushareFetcher

        Args:
            rate_limit_per_minute: 每分钟最大请求数（默认80，Tushare免费配额）
        """
        self.rate_limit_per_minute = rate_limit_per_minute
        self._call_count = 0  # 当前分钟内的调用次数
        self._minute_start: Optional[float] = None  # 当前计数周期开始时间
        self._api: Optional[object] = None  # Tushare API 实例

        # 尝试初始化 API
        self._init_api()

        # 根据 API 初始化结果动态调整优先级
        self.priority = self._determine_priority()
    
    def _init_api(self) -> None:
        """
        初始化 Tushare API
        
        如果 Token 未配置，此数据源将不可用
        """
        config = get_config()
        
        if not config.tushare_token:
            logger.warning("Tushare Token 未配置，此数据源不可用")
            return
        
        try:
            import tushare as ts
            
            # Set Token
            ts.set_token(config.tushare_token)
            
            # Get API instance
            self._api = ts.pro_api()
            
            # Fix: tushare SDK 1.4.x hardcodes api.waditu.com/dataapi which may
            # be unavailable (503). Monkey-patch the query method to use the
            # official api.tushare.pro endpoint which posts to root URL.
            self._patch_api_endpoint(config.tushare_token)

            logger.info("Tushare API 初始化成功")
            
        except Exception as e:
            logger.error(f"Tushare API 初始化失败: {e}")
            self._api = None

    def _patch_api_endpoint(self, token: str) -> None:
        """
        Patch tushare SDK to use the official api.tushare.pro endpoint.

        The SDK (v1.4.x) hardcodes http://api.waditu.com/dataapi and appends
        /{api_name} to the URL. That endpoint may return 503, causing silent
        empty-DataFrame failures. This method replaces the query method to
        POST directly to http://api.tushare.pro (root URL, no path suffix).
        """
        import types

        TUSHARE_API_URL = "http://api.tushare.pro"
        _token = token
        _timeout = getattr(self._api, '_DataApi__timeout', 30)

        def patched_query(self_api, api_name, fields='', **kwargs):
            req_params = {
                'api_name': api_name,
                'token': _token,
                'params': kwargs,
                'fields': fields,
            }
            res = requests.post(TUSHARE_API_URL, json=req_params, timeout=_timeout)
            if res.status_code != 200:
                raise Exception(f"Tushare API HTTP {res.status_code}")
            result = _json.loads(res.text)
            if result['code'] != 0:
                raise Exception(result['msg'])
            data = result['data']
            columns = data['fields']
            items = data['items']
            return pd.DataFrame(items, columns=columns)

        self._api.query = types.MethodType(patched_query, self._api)
        logger.debug(f"Tushare API endpoint patched to {TUSHARE_API_URL}")

    def _determine_priority(self) -> int:
        """
        根据 Token 配置和 API 初始化状态确定优先级

        策略：
        - Token 配置且 API 初始化成功：优先级 -1（绝对最高，优于 efinance）
        - 其他情况：优先级 2（默认）

        Returns:
            优先级数字（0=最高，数字越大优先级越低）
        """
        config = get_config()

        if config.tushare_token and self._api is not None:
            # Token 配置且 API 初始化成功，提升为最高优先级
            logger.info("✅ 检测到 TUSHARE_TOKEN 且 API 初始化成功，Tushare 数据源优先级提升为最高 (Priority -1)")
            return -1

        # Token 未配置或 API 初始化失败，保持默认优先级
        return 2

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            True 表示可用，False 表示不可用
        """
        return self._api is not None

    def _check_rate_limit(self) -> None:
        """
        检查并执行速率限制
        
        流控策略：
        1. 检查是否进入新的一分钟
        2. 如果是，重置计数器
        3. 如果当前分钟调用次数超过限制，强制休眠
        """
        current_time = time.time()
        
        # 检查是否需要重置计数器（新的一分钟）
        if self._minute_start is None:
            self._minute_start = current_time
            self._call_count = 0
        elif current_time - self._minute_start >= 60:
            # 已经过了一分钟，重置计数器
            self._minute_start = current_time
            self._call_count = 0
            logger.debug("速率限制计数器已重置")
        
        # 检查是否超过配额
        if self._call_count >= self.rate_limit_per_minute:
            # 计算需要等待的时间（到下一分钟）
            elapsed = current_time - self._minute_start
            sleep_time = max(0, 60 - elapsed) + 1  # +1 秒缓冲
            
            logger.warning(
                f"Tushare 达到速率限制 ({self._call_count}/{self.rate_limit_per_minute} 次/分钟)，"
                f"等待 {sleep_time:.1f} 秒..."
            )
            
            time.sleep(sleep_time)
            
            # 重置计数器
            self._minute_start = time.time()
            self._call_count = 0
        
        # 增加调用计数
        self._call_count += 1
        logger.debug(f"Tushare 当前分钟调用次数: {self._call_count}/{self.rate_limit_per_minute}")
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Tushare 格式
        
        Tushare 要求的格式：
        - 沪市股票：600519.SH
        - 深市股票：000001.SZ
        - 沪市 ETF：510050.SH, 563230.SH
        - 深市 ETF：159919.SZ
        
        Args:
            stock_code: 原始代码，如 '600519', '000001', '563230'
            
        Returns:
            Tushare 格式代码，如 '600519.SH', '000001.SZ', '563230.SH'
        """
        code = stock_code.strip()
        
        # Already has suffix
        if '.' in code:
            return code.upper()
        
        # ETF: determine exchange by prefix
        if code.startswith(_ETF_SH_PREFIXES) and len(code) == 6:
            return f"{code}.SH"
        if code.startswith(_ETF_SZ_PREFIXES) and len(code) == 6:
            return f"{code}.SZ"
        
        # Regular stocks
        # Shanghai: 600xxx, 601xxx, 603xxx, 688xxx (STAR Market)
        # Shenzhen: 000xxx, 002xxx, 300xxx (ChiNext)
        if code.startswith(('600', '601', '603', '688')):
            return f"{code}.SH"
        elif code.startswith(('000', '002', '300')):
            return f"{code}.SZ"
        else:
            logger.warning(f"无法确定股票 {code} 的市场，默认使用深市")
            return f"{code}.SZ"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Tushare 获取原始数据
        
        根据代码类型选择不同接口：
        - 普通股票：daily()
        - ETF 基金：fund_daily()
        
        流程：
        1. 检查 API 是否可用
        2. 检查是否为美股（不支持）
        3. 执行速率限制检查
        4. 转换股票代码格式
        5. 根据代码类型选择接口并调用
        """
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，请检查 Token 配置")
        
        # US stocks not supported
        if _is_us_code(stock_code):
            raise DataFetchError(f"TushareFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")
        
        # Rate-limit check
        self._check_rate_limit()
        
        # Convert code format
        ts_code = self._convert_stock_code(stock_code)
        
        # Convert date format (Tushare requires YYYYMMDD)
        ts_start = start_date.replace('-', '')
        ts_end = end_date.replace('-', '')
        
        is_etf = _is_etf_code(stock_code)
        api_name = "fund_daily" if is_etf else "daily"
        logger.debug(f"调用 Tushare {api_name}({ts_code}, {ts_start}, {ts_end})")
        
        try:
            if is_etf:
                # ETF uses fund_daily interface
                df = self._api.fund_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            else:
                # Regular stocks use daily interface
                df = self._api.daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            
            return df
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # 检测配额超限
            if any(keyword in error_msg for keyword in ['quota', '配额', 'limit', '权限']):
                logger.warning(f"Tushare 配额可能超限: {e}")
                raise RateLimitError(f"Tushare 配额超限: {e}") from e
            
            raise DataFetchError(f"Tushare 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Tushare 数据
        
        Tushare daily 返回的列名：
        ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
        
        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()
        
        # 列名映射
        column_mapping = {
            'trade_date': 'date',
            'vol': 'volume',
            # open, high, low, close, amount, pct_chg 列名相同
        }
        
        df = df.rename(columns=column_mapping)
        
        # 转换日期格式（YYYYMMDD -> YYYY-MM-DD）
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        
        # 成交量单位转换（Tushare 的 vol 单位是手，需要转换为股）
        if 'volume' in df.columns:
            df['volume'] = df['volume'] * 100
        
        # 成交额单位转换（Tushare 的 amount 单位是千元，转换为元）
        if 'amount' in df.columns:
            df['amount'] = df['amount'] * 1000
        
        # 添加股票代码列
        df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        获取股票名称
        
        使用 Tushare 的 stock_basic 接口获取股票基本信息
        
        Args:
            stock_code: 股票代码
            
        Returns:
            股票名称，失败返回 None
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票名称")
            return None
        
        # 检查缓存
        if hasattr(self, '_stock_name_cache') and stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        # 初始化缓存
        if not hasattr(self, '_stock_name_cache'):
            self._stock_name_cache = {}
        
        try:
            # 速率限制检查
            self._check_rate_limit()
            
            # 转换代码格式
            ts_code = self._convert_stock_code(stock_code)
            
            # ETF uses fund_basic, regular stocks use stock_basic
            if _is_etf_code(stock_code):
                df = self._api.fund_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            else:
                df = self._api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            
            if df is not None and not df.empty:
                name = df.iloc[0]['name']
                self._stock_name_cache[stock_code] = name
                logger.debug(f"Tushare 获取股票名称成功: {stock_code} -> {name}")
                return name
            
        except Exception as e:
            logger.warning(f"Tushare 获取股票名称失败 {stock_code}: {e}")
        
        return None
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        获取股票列表
        
        使用 Tushare 的 stock_basic 接口获取全部股票列表
        
        Returns:
            包含 code, name 列的 DataFrame，失败返回 None
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票列表")
            return None
        
        try:
            # 速率限制检查
            self._check_rate_limit()
            
            # 调用 stock_basic 接口获取所有股票
            df = self._api.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,name,industry,area,market'
            )
            
            if df is not None and not df.empty:
                # 转换 ts_code 为标准代码格式
                df['code'] = df['ts_code'].apply(lambda x: x.split('.')[0])
                
                # 更新缓存
                if not hasattr(self, '_stock_name_cache'):
                    self._stock_name_cache = {}
                for _, row in df.iterrows():
                    self._stock_name_cache[row['code']] = row['name']
                
                logger.info(f"Tushare 获取股票列表成功: {len(df)} 条")
                return df[['code', 'name', 'industry', 'area', 'market']]
            
        except Exception as e:
            logger.warning(f"Tushare 获取股票列表失败: {e}")
        
        return None

    @staticmethod
    def _clean_scalar(value: Any) -> Any:
        """Convert pandas/numpy scalars into JSON-friendly Python values."""
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            return value.strftime('%Y-%m-%d')
        if hasattr(value, "item") and callable(getattr(value, "item")):
            try:
                value = value.item()
            except Exception:
                pass
        if isinstance(value, float) and math.isnan(value):
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        return value

    @classmethod
    def _frame_to_records(cls, df: Optional[pd.DataFrame], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Convert DataFrame rows into cleaned dictionaries."""
        if df is None or df.empty:
            return []

        records: List[Dict[str, Any]] = []
        sliced = df.head(limit) if limit is not None else df
        for _, row in sliced.iterrows():
            records.append({key: cls._clean_scalar(value) for key, value in row.items()})
        return records

    def get_name_changes(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get historical stock name changes."""
        if self._api is None:
            return []

        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            df = self._api.namechange(
                ts_code=ts_code,
                fields='ts_code,name,start_date,end_date,ann_date,change_reason',
            )
            if df is None or df.empty:
                return []
            df = df.sort_values(['ann_date', 'start_date'], ascending=False, na_position='last')
            return self._frame_to_records(df, limit=limit)
        except Exception as e:
            logger.warning(f"Tushare 获取股票曾用名失败 {stock_code}: {e}")
            return []

    def get_dividend(self, stock_code: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get dividend history for an A-share stock."""
        if self._api is None:
            return []

        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            df = self._api.dividend(
                ts_code=ts_code,
                fields='ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,'
                       'cash_div_tax,record_date,ex_date,pay_date',
            )
            if df is None or df.empty:
                return []
            df = df.sort_values(['end_date', 'ann_date'], ascending=False, na_position='last')
            return self._frame_to_records(df, limit=limit)
        except Exception as e:
            logger.warning(f"Tushare 获取分红送股失败 {stock_code}: {e}")
            return []

    def get_top10_holders(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top ten holder disclosures."""
        if self._api is None:
            return []

        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            df = self._api.top10_holders(
                ts_code=ts_code,
                fields='ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio',
            )
            if df is None or df.empty:
                return []
            df = df.sort_values(['end_date', 'ann_date', 'hold_ratio'], ascending=[False, False, False], na_position='last')
            return self._frame_to_records(df, limit=limit)
        except Exception as e:
            logger.warning(f"Tushare 获取前十大股东失败 {stock_code}: {e}")
            return []

    def get_top10_floatholders(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top ten float holder disclosures."""
        if self._api is None:
            return []

        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            df = self._api.top10_floatholders(
                ts_code=ts_code,
                fields='ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio',
            )
            if df is None or df.empty:
                return []
            df = df.sort_values(['end_date', 'ann_date', 'hold_ratio'], ascending=[False, False, False], na_position='last')
            return self._frame_to_records(df, limit=limit)
        except Exception as e:
            logger.warning(f"Tushare 获取前十大流通股东失败 {stock_code}: {e}")
            return []

    def get_base_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        Get merged A-share basic information from Tushare.

        This combines stock list metadata, company profile, name changes,
        dividend history, and top holder disclosures.
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票基本信息")
            return None

        if not hasattr(self, '_base_info_cache'):
            self._base_info_cache = {}
        if stock_code in self._base_info_cache:
            return dict(self._base_info_cache[stock_code])

        ts_code = self._convert_stock_code(stock_code)
        result: Dict[str, Any] = {
            "code": stock_code,
            "ts_code": ts_code,
            "source": "tushare",
        }

        try:
            self._check_rate_limit()
            if _is_etf_code(stock_code):
                basic_df = self._api.fund_basic(
                    market='E',
                    ts_code=ts_code,
                    fields='ts_code,name,management,custodian,fund_type,found_date,due_date,list_date,'
                           'issue_amount,m_fee,c_fee,p_value,min_amount,benchmark,status',
                )
            else:
                basic_df = self._api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,symbol,name,area,industry,market,list_date,cnspell,act_name,'
                           'exchange,fullname,enname,curr_type,list_status,delist_date,is_hs',
                )

            if basic_df is not None and not basic_df.empty:
                result.update(self._frame_to_records(basic_df, limit=1)[0])
        except Exception as e:
            logger.warning(f"Tushare 获取基础列表信息失败 {stock_code}: {e}")

        if not _is_etf_code(stock_code):
            try:
                self._check_rate_limit()
                company_df = self._api.stock_company(
                    ts_code=ts_code,
                    fields='ts_code,exchange,chairman,manager,secretary,reg_capital,setup_date,province,city,'
                           'introduction,website,email,office,employees,main_business,business_scope',
                )
                if company_df is not None and not company_df.empty:
                    result.update(self._frame_to_records(company_df, limit=1)[0])
            except Exception as e:
                logger.warning(f"Tushare 获取公司信息失败 {stock_code}: {e}")

            name_changes = self.get_name_changes(stock_code, limit=10)
            if name_changes:
                result["name_changes"] = name_changes
                result["former_names"] = [item.get("name") for item in name_changes if item.get("name")]

            dividends = self.get_dividend(stock_code, limit=5)
            if dividends:
                result["dividends"] = dividends
                result["latest_dividend"] = dividends[0]

            top10_holders = self.get_top10_holders(stock_code, limit=10)
            if top10_holders:
                result["top10_holders"] = top10_holders

            top10_floatholders = self.get_top10_floatholders(stock_code, limit=10)
            if top10_floatholders:
                result["top10_floatholders"] = top10_floatholders

        meaningful = {k: v for k, v in result.items() if v not in (None, "", [], {})}
        if meaningful:
            self._base_info_cache[stock_code] = dict(meaningful)
        return meaningful or None

    def get_index_basic(self, market: str = "SSE") -> Optional[pd.DataFrame]:
        """Get A-share index basic metadata."""
        if self._api is None:
            return None

        try:
            self._check_rate_limit()
            df = self._api.index_basic(market=market)
            return df if df is not None and not df.empty else None
        except Exception as e:
            logger.warning(f"Tushare 获取指数基础信息失败 {market}: {e}")
            return None

    def get_limit_list_d(self, trade_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Get daily A-share limit-up/limit-down list."""
        if self._api is None:
            return None

        target_date = (trade_date or datetime.now().strftime('%Y%m%d')).replace('-', '')
        try:
            self._check_rate_limit()
            df = self._api.limit_list_d(trade_date=target_date)
            return df if df is not None and not df.empty else None
        except Exception as e:
            logger.warning(f"Tushare 获取涨跌停列表失败 {target_date}: {e}")
            return None

    def get_new_share(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Get recent IPO schedule data."""
        if self._api is None:
            return None

        end = (end_date or datetime.now().strftime('%Y%m%d')).replace('-', '')
        start = (start_date or (datetime.now() - pd.Timedelta(days=365)).strftime('%Y%m%d')).replace('-', '')
        try:
            self._check_rate_limit()
            df = self._api.new_share(start_date=start, end_date=end)
            return df if df is not None and not df.empty else None
        except Exception as e:
            logger.warning(f"Tushare 获取新股列表失败 {start}~{end}: {e}")
            return None
    
    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情

        策略：
        1. 优先尝试 Pro 接口（需要2000积分）：数据全，稳定性高
        2. 失败降级到旧版接口：门槛低，数据较少

        Args:
            stock_code: 股票代码

        Returns:
            UnifiedRealtimeQuote 对象，失败返回 None
        """
        if self._api is None:
            return None

        from .realtime_types import (
            RealtimeSource,
            safe_float, safe_int
        )

        # 速率限制检查
        self._check_rate_limit()

        # 尝试 Pro 接口
        try:
            ts_code = self._convert_stock_code(stock_code)
            # 尝试调用 Pro 实时接口 (需要积分)
            df = self._api.quotation(ts_code=ts_code)

            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"Tushare Pro 实时行情获取成功: {stock_code}")

                return UnifiedRealtimeQuote(
                    code=stock_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=safe_float(row.get('price')),
                    change_pct=safe_float(row.get('pct_chg')),  # Pro 接口通常直接返回涨跌幅
                    change_amount=safe_float(row.get('change')),
                    volume=safe_int(row.get('vol')),
                    amount=safe_float(row.get('amount')),
                    high=safe_float(row.get('high')),
                    low=safe_float(row.get('low')),
                    open_price=safe_float(row.get('open')),
                    pre_close=safe_float(row.get('pre_close')),
                    turnover_rate=safe_float(row.get('turnover_ratio')), # Pro 接口可能有换手率
                    pe_ratio=safe_float(row.get('pe')),
                    pb_ratio=safe_float(row.get('pb')),
                    total_mv=safe_float(row.get('total_mv')),
                )
        except Exception as e:
            # 仅记录调试日志，不报错，继续尝试降级
            logger.debug(f"Tushare Pro 实时行情不可用 (可能是积分不足): {e}")

        # 降级：尝试旧版接口
        try:
            import tushare as ts

            # Tushare 旧版接口使用 6 位代码
            code_6 = stock_code.split('.')[0] if '.' in stock_code else stock_code

            # 特殊处理指数代码：旧版接口需要前缀 (sh000001, sz399001)
            # 简单的指数判断逻辑
            if code_6 == '000001':  # 上证指数
                symbol = 'sh000001'
            elif code_6 == '399001': # 深证成指
                symbol = 'sz399001'
            elif code_6 == '399006': # 创业板指
                symbol = 'sz399006'
            elif code_6 == '000300': # 沪深300
                symbol = 'sh000300'
            else:
                symbol = code_6

            # 调用旧版实时接口 (ts.get_realtime_quotes)
            df = ts.get_realtime_quotes(symbol)

            if df is None or df.empty:
                return None

            row = df.iloc[0]

            # 计算涨跌幅
            price = safe_float(row['price'])
            pre_close = safe_float(row['pre_close'])
            change_pct = 0.0
            change_amount = 0.0

            if price and pre_close and pre_close > 0:
                change_amount = price - pre_close
                change_pct = (change_amount / pre_close) * 100

            # 构建统一对象
            return UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row['name']),
                source=RealtimeSource.TUSHARE,
                price=price,
                change_pct=round(change_pct, 2),
                change_amount=round(change_amount, 2),
                volume=safe_int(row['volume']) // 100,  # 转换为手
                amount=safe_float(row['amount']),
                high=safe_float(row['high']),
                low=safe_float(row['low']),
                open_price=safe_float(row['open']),
                pre_close=pre_close,
            )

        except Exception as e:
            logger.warning(f"Tushare (旧版) 获取实时行情失败 {stock_code}: {e}")
            return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[dict]]:
        """
        获取主要指数实时行情 (Tushare Pro)，仅支持 A 股
        """
        if region != "cn":
            return None
        if self._api is None:
            return None

        from .realtime_types import safe_float

        # 指数映射：Tushare代码 -> 名称
        indices_map = {
            '000001.SH': '上证指数',
            '399001.SZ': '深证成指',
            '399006.SZ': '创业板指',
            '000688.SH': '科创50',
            '000016.SH': '上证50',
            '000300.SH': '沪深300',
        }

        try:
            self._check_rate_limit()

            # Tushare index_daily 获取历史数据，实时数据需用其他接口或估算
            # 由于 Tushare 免费用户可能无法获取指数实时行情，这里作为备选
            # 使用 index_daily 获取最近交易日数据

            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - pd.Timedelta(days=5)).strftime('%Y%m%d')

            results = []

            # 批量获取所有指数数据
            for ts_code, name in indices_map.items():
                try:
                    df = self._api.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if df is not None and not df.empty:
                        row = df.iloc[0] # 最新一天

                        current = safe_float(row['close'])
                        prev_close = safe_float(row['pre_close'])

                        results.append({
                            'code': ts_code.split('.')[0], # 兼容 sh000001 格式需转换，这里保持纯数字
                            'name': name,
                            'current': current,
                            'change': safe_float(row['change']),
                            'change_pct': safe_float(row['pct_chg']),
                            'open': safe_float(row['open']),
                            'high': safe_float(row['high']),
                            'low': safe_float(row['low']),
                            'prev_close': prev_close,
                            'volume': safe_float(row['vol']),
                            'amount': safe_float(row['amount']) * 1000, # 千元转元
                            'amplitude': 0.0 # Tushare index_daily 不直接返回振幅
                        })
                except Exception as e:
                    logger.debug(f"Tushare 获取指数 {name} 失败: {e}")
                    continue

            if results:
                return results
            else:
                logger.warning("[Tushare] 未获取到指数行情数据")

        except Exception as e:
            logger.error(f"[Tushare] 获取指数行情失败: {e}")

        return None

    def get_market_stats(self) -> Optional[dict]:
        """
        获取市场涨跌统计 (Tushare Pro)
        """
        if self._api is None:
            return None

        try:
            # Avoid relying on trade_cal because this token may not have
            # permission for it, while daily(trade_date=...) is available.
            candidate_dates = [
                (datetime.now() - timedelta(days=offset)).strftime('%Y%m%d')
                for offset in range(0, 7)
            ]

            for trade_date in candidate_dates:
                self._check_rate_limit()
                df = self._api.daily(trade_date=trade_date)
                current_len = len(df) if df is not None else 0
                logger.info(f"[Tushare] Fetch daily stats candidate {trade_date}, records={current_len}")

                if df is None or df.empty or current_len < 100:
                    continue

                logger.info(f"[Tushare] 使用交易日 {trade_date} 进行市场统计分析")
                df['pct_chg'] = pd.to_numeric(df['pct_chg'], errors='coerce')
                df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
                df = df.dropna(subset=['pct_chg'])

                up_count = len(df[df['pct_chg'] > 0])
                down_count = len(df[df['pct_chg'] < 0])
                flat_count = len(df[df['pct_chg'] == 0])
                limit_up = len(df[df['pct_chg'] >= 9.9])
                limit_down = len(df[df['pct_chg'] <= -9.9])
                total_amount = df['amount'].fillna(0).sum() * 1000 / 1e8  # 千元 -> 亿元

                return {
                    'up_count': up_count,
                    'down_count': down_count,
                    'flat_count': flat_count,
                    'limit_up_count': limit_up,
                    'limit_down_count': limit_down,
                    'total_amount': total_amount
                }

            logger.warning("[Tushare] 最近 7 天均未获取到可用的市场统计数据")

        except Exception as e:
            logger.error(f"[Tushare] 获取市场统计失败: {e}")

        return None

    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[list, list]]:
        """
        获取板块涨跌榜 (Tushare Pro)
        """
        # Tushare 获取板块数据较复杂，暂时返回 None，让 AkShare 处理
        return None


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = TushareFetcher()
    
    try:
        # 测试历史数据
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
        
        # 测试股票名称
        name = fetcher.get_stock_name('600519')
        print(f"股票名称: {name}")
        
    except Exception as e:
        print(f"获取失败: {e}")
