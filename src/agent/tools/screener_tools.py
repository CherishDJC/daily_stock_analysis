# -*- coding: utf-8 -*-
"""
Screener tools — batch stock screening utilities for the agent.

Tools:
- screen_stocks_full_scan: broad-market quote prefilter + technical validation
- get_sector_top_stocks: get top stocks from a specific sector
"""

import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from src.agent.tools.registry import ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)

_FULL_MARKET_QUOTES_CACHE: Dict[str, Any] = {"data": None, "timestamp": 0.0}
_FULL_MARKET_QUOTES_TTL = 60
_STOCK_METADATA_CACHE: Dict[str, Any] = {"data": None, "timestamp": 0.0}
_STOCK_METADATA_TTL = 3600


def _get_fetcher_manager():
    """Lazy import to avoid circular deps."""
    from data_provider import DataFetcherManager
    return DataFetcherManager()


def _hist_start_date() -> str:
    """Return date string for 60 trading days ago (roughly 90 calendar days)."""
    from datetime import date, timedelta
    return (date.today() - timedelta(days=120)).strftime("%Y%m%d")


def _hist_end_date() -> str:
    """Return today's date string."""
    from datetime import date
    return date.today().strftime("%Y%m%d")


def _normalize_stock_code(value: Any) -> Optional[str]:
    """Normalize a stock code into a 6-digit A-share style code."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "." in text:
        text = text.split(".")[-1]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text if text.isdigit() and len(text) == 6 else None


def _round_number(value: Any, digits: int = 2) -> Optional[float]:
    """Round numeric values and convert NaN into None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return round(number, digits)


def _load_stock_metadata(manager, cache_only: bool = False):
    """Load active A-share stock metadata with industry information when available."""
    import pandas as pd

    current_time = time.time()
    cached = _STOCK_METADATA_CACHE["data"]
    if cached is not None and current_time - _STOCK_METADATA_CACHE["timestamp"] < _STOCK_METADATA_TTL:
        return cached.copy()

    if cache_only:
        return pd.DataFrame(columns=["code", "name", "industry"])

    df = manager.get_stock_list()
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name", "industry"])

    metadata = df.copy()
    rename_map = {}
    if "code" not in metadata.columns and "代码" in metadata.columns:
        rename_map["代码"] = "code"
    if "name" not in metadata.columns and "名称" in metadata.columns:
        rename_map["名称"] = "name"
    if "industry" not in metadata.columns:
        if "所属行业" in metadata.columns:
            rename_map["所属行业"] = "industry"
        elif "行业" in metadata.columns:
            rename_map["行业"] = "industry"
    if rename_map:
        metadata = metadata.rename(columns=rename_map)

    if "code" not in metadata.columns:
        return pd.DataFrame(columns=["code", "name", "industry"])

    metadata["code"] = metadata["code"].map(_normalize_stock_code)
    metadata = metadata[metadata["code"].notna()].copy()
    if "name" not in metadata.columns:
        metadata["name"] = ""
    metadata["name"] = metadata["name"].fillna("").astype(str).str.strip()
    if "industry" not in metadata.columns:
        metadata["industry"] = None
    else:
        metadata["industry"] = metadata["industry"].fillna("").astype(str).str.strip().replace("", None)

    normalized = metadata[["code", "name", "industry"]].drop_duplicates(subset=["code"], keep="first")
    _STOCK_METADATA_CACHE["data"] = normalized
    _STOCK_METADATA_CACHE["timestamp"] = current_time
    return normalized.copy()


def _normalize_market_quotes_frame(raw_df, source: str):
    """Normalize a full-market quote frame from efinance or akshare."""
    import pandas as pd

    def pick_column(*names: str) -> Optional[str]:
        for name in names:
            if name in raw_df.columns:
                return name
        return None

    if raw_df is None or raw_df.empty:
        return pd.DataFrame(
            columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
        )

    code_col = pick_column("股票代码", "代码", "code")
    name_col = pick_column("股票名称", "名称", "name")
    price_col = pick_column("最新价", "最新", "price")
    change_col = pick_column("涨跌幅", "pct_chg", "change_pct")
    volume_ratio_col = pick_column("量比", "volume_ratio")
    turnover_col = pick_column("换手率", "turnover_rate")
    pe_col = pick_column("市盈率", "市盈率-动态", "pe_ratio")
    total_mv_col = pick_column("总市值", "total_mv")
    amount_col = pick_column("成交额", "amount")

    if code_col is None:
        return pd.DataFrame(
            columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
        )

    normalized = pd.DataFrame(
        {
            "code": raw_df[code_col],
            "name": raw_df[name_col] if name_col else "",
            "price": raw_df[price_col] if price_col else None,
            "change_pct": raw_df[change_col] if change_col else None,
            "volume_ratio": raw_df[volume_ratio_col] if volume_ratio_col else None,
            "turnover_rate": raw_df[turnover_col] if turnover_col else None,
            "pe_ratio": raw_df[pe_col] if pe_col else None,
            "total_mv": raw_df[total_mv_col] if total_mv_col else None,
            "amount": raw_df[amount_col] if amount_col else None,
        }
    )

    normalized["code"] = normalized["code"].map(_normalize_stock_code)
    normalized = normalized[normalized["code"].notna()].copy()
    normalized["name"] = normalized["name"].fillna("").astype(str).str.strip()
    for column in ("price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized["quote_source"] = source
    return normalized.drop_duplicates(subset=["code"], keep="first")


def _load_full_market_quotes_tencent():
    """Fallback: batch-query Tencent API for A-share realtime quotes."""
    import pandas as pd
    import urllib.request

    # 1. Get stock code list via akshare (fast, no token)
    try:
        import akshare as ak
        code_df = ak.stock_info_a_code_name()
    except Exception as exc:
        logger.debug("Tencent fallback: failed to get stock list: %s", exc)
        return pd.DataFrame(
            columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
        )

    if code_df is None or code_df.empty:
        return pd.DataFrame(
            columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
        )

    code_col = "代码" if "代码" in code_df.columns else "code"
    name_col = "名称" if "名称" in code_df.columns else "name"

    # Build Tencent-style codes: sh600519, sz000001
    tencent_codes = []
    code_map = {}  # tencent_code -> (code, name)
    for _, row in code_df.iterrows():
        code = str(row[code_col]).strip()
        name = str(row.get(name_col, "")).strip()
        if code.startswith("6"):
            tc = f"sh{code}"
        elif code.startswith(("0", "3")):
            tc = f"sz{code}"
        else:
            continue
        tencent_codes.append(tc)
        code_map[tc] = (code, name)

    # 2. Batch query (80 codes per request)
    records = []
    batch_size = 80
    for i in range(0, len(tencent_codes), batch_size):
        batch = tencent_codes[i:i + batch_size]
        url = f"https://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            text = resp.read().decode("gbk", errors="ignore")
        except Exception:
            continue

        for line in text.strip().split(";"):
            line = line.strip()
            if "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                tc_key = line.split("=")[0].split("_")[-1]
                raw_code, raw_name = code_map.get(tc_key, (parts[2], parts[1]))
                price = float(parts[3]) if parts[3] else None
                change_pct = float(parts[32]) if parts[32] else None
                turnover_rate = float(parts[38]) if parts[38] else None
                pe_ratio = float(parts[39]) if parts[39] else None
                total_mv = float(parts[44]) * 1e8 if parts[44] else None  # 亿 -> 元
                amount = float(parts[37]) * 1e4 if parts[37] else None  # 万 -> 元
                records.append({
                    "code": _normalize_stock_code(raw_code) or raw_code,
                    "name": raw_name or parts[1],
                    "price": price,
                    "change_pct": change_pct,
                    "volume_ratio": None,
                    "turnover_rate": turnover_rate,
                    "pe_ratio": pe_ratio,
                    "total_mv": total_mv,
                    "amount": amount,
                    "quote_source": "tencent",
                })
            except (ValueError, IndexError):
                continue

    if not records:
        return pd.DataFrame(
            columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
        )

    df = pd.DataFrame(records)
    df["code"] = df["code"].map(_normalize_stock_code)
    df = df[df["code"].notna()].copy()
    return df.drop_duplicates(subset=["code"], keep="first")


def _load_full_market_quotes():
    """Load a full-market A-share quote frame with a short in-memory cache."""
    import pandas as pd

    current_time = time.time()
    cached = _FULL_MARKET_QUOTES_CACHE["data"]
    if cached is not None and current_time - _FULL_MARKET_QUOTES_CACHE["timestamp"] < _FULL_MARKET_QUOTES_TTL:
        return cached.copy()

    attempts = []

    try:
        import efinance as ef

        raw_df = ef.stock.get_realtime_quotes()
        normalized = _normalize_market_quotes_frame(raw_df, source="efinance")
        if not normalized.empty:
            _FULL_MARKET_QUOTES_CACHE["data"] = normalized
            _FULL_MARKET_QUOTES_CACHE["timestamp"] = current_time
            return normalized.copy()
        attempts.append("efinance returned empty data")
    except Exception as exc:
        attempts.append(f"efinance failed: {exc}")

    try:
        import akshare as ak

        raw_df = ak.stock_zh_a_spot_em()
        normalized = _normalize_market_quotes_frame(raw_df, source="akshare_em")
        if not normalized.empty:
            _FULL_MARKET_QUOTES_CACHE["data"] = normalized
            _FULL_MARKET_QUOTES_CACHE["timestamp"] = current_time
            return normalized.copy()
        attempts.append("akshare_em returned empty data")
    except Exception as exc:
        attempts.append(f"akshare_em failed: {exc}")

    # Fallback: Tencent batch quotes
    try:
        tencent_df = _load_full_market_quotes_tencent()
        if not tencent_df.empty:
            _FULL_MARKET_QUOTES_CACHE["data"] = tencent_df
            _FULL_MARKET_QUOTES_CACHE["timestamp"] = current_time
            logger.info("Tencent fallback: loaded %d stocks", len(tencent_df))
            return tencent_df.copy()
        attempts.append("tencent returned empty data")
    except Exception as exc:
        attempts.append(f"tencent failed: {exc}")

    logger.warning("Full-market quote loading failed: %s", " | ".join(attempts))
    return pd.DataFrame(
        columns=["code", "name", "price", "change_pct", "volume_ratio", "turnover_rate", "pe_ratio", "total_mv", "amount"]
    )


def _filter_by_requested_sectors(df, target_sectors, manager):
    """Filter the candidate universe by requested sectors/industries."""
    if not target_sectors:
        return df

    cleaned_targets = [str(item).strip() for item in target_sectors if str(item).strip()]
    if not cleaned_targets:
        return df

    if "industry" in df.columns:
        industry_series = df["industry"].fillna("").astype(str)
        mask = industry_series == "__never_match__"
        for sector in cleaned_targets:
            mask = mask | industry_series.str.contains(sector, case=False, na=False)
        filtered = df[mask].copy()
        if not filtered.empty:
            return filtered

    fallback_codes = set()
    for sector_name in cleaned_targets[:10]:
        try:
            sector_df = manager.get_sector_constituents(sector_name=sector_name, limit=10)
        except Exception:
            sector_df = None
        if sector_df is None or sector_df.empty:
            continue
        first_column = sector_df.columns[0]
        fallback_codes.update(
            code
            for code in sector_df[first_column].map(_normalize_stock_code).tolist()
            if code is not None
        )

    if fallback_codes:
        return df[df["code"].isin(fallback_codes)].copy()

    return df.iloc[0:0].copy()


def _compute_ma_filter(code: str) -> Optional[dict]:
    """Fetch daily history and compute MA alignment for a single stock."""
    # Use akshare directly to avoid slow efinance timeout on servers where eastmoney is unreachable
    try:
        import akshare as ak
        raw_df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=_hist_start_date(), end_date=_hist_end_date(), adjust="qfq")
        if raw_df is None or raw_df.empty or len(raw_df) < 20:
            return None
        # Normalize column names
        col_map = {}
        for cn, en in [("日期", "date"), ("开盘", "open"), ("收盘", "close"), ("最高", "high"), ("最低", "low"), ("成交量", "volume")]:
            if cn in raw_df.columns:
                col_map[cn] = en
        if col_map:
            raw_df = raw_df.rename(columns=col_map)
    except Exception:
        return None

    if "close" not in raw_df.columns or len(raw_df) < 20:
        return None

    close = raw_df["close"]
    current_price = float(close.iloc[-1])

    ma5 = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else None
    ma10 = float(close.rolling(10).mean().iloc[-1]) if len(close) >= 10 else None
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
    if ma5 is None or ma10 is None or ma20 is None:
        return None

    volume_ratio = None
    if "volume" in raw_df.columns and len(raw_df["volume"]) >= 5:
        latest_volume = float(raw_df["volume"].iloc[-1])
        avg_volume_5 = float(raw_df["volume"].iloc[-5:].mean())
        if avg_volume_5 > 0:
            volume_ratio = round(latest_volume / avg_volume_5, 2)

    return {
        "code": code,
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "current_price": round(current_price, 2),
        "ma_bullish": ma5 > ma10 > ma20,
        "bias_ma5": round((current_price - ma5) / ma5 * 100, 2) if ma5 else None,
        "volume_ratio": volume_ratio,
    }


def _apply_quote_filters(df, conds):
    """Apply realtime-quote-level filters to the candidate universe."""
    filtered = df.copy()
    exclude_st = conds.get("exclude_st", True)

    if exclude_st:
        filtered = filtered[~filtered["name"].str.upper().str.contains("ST", na=False)].copy()

    if conds.get("pe_max") is not None:
        filtered = filtered[filtered["pe_ratio"].notna() & (filtered["pe_ratio"] <= float(conds["pe_max"]))].copy()
    if conds.get("pe_min") is not None:
        filtered = filtered[filtered["pe_ratio"].notna() & (filtered["pe_ratio"] >= float(conds["pe_min"]))].copy()
    if conds.get("change_pct_min") is not None:
        filtered = filtered[filtered["change_pct"].notna() & (filtered["change_pct"] >= float(conds["change_pct_min"]))].copy()
    if conds.get("change_pct_max") is not None:
        filtered = filtered[filtered["change_pct"].notna() & (filtered["change_pct"] <= float(conds["change_pct_max"]))].copy()
    if conds.get("market_cap_min") is not None:
        min_market_cap_yuan = float(conds["market_cap_min"]) * 1e8
        filtered = filtered[filtered["total_mv"].notna() & (filtered["total_mv"] >= min_market_cap_yuan)].copy()
    if conds.get("market_cap_max") is not None:
        max_market_cap_yuan = float(conds["market_cap_max"]) * 1e8
        filtered = filtered[filtered["total_mv"].notna() & (filtered["total_mv"] <= max_market_cap_yuan)].copy()

    return filtered


def _rank_quote_candidates(df, technical_scan_limit: int):
    """Prioritize liquid candidates before the expensive technical pass."""
    ranked = df.copy()
    ranked["amount"] = ranked["amount"].fillna(0.0)
    ranked["turnover_rate"] = ranked["turnover_rate"].fillna(0.0)
    ranked["volume_ratio"] = ranked["volume_ratio"].fillna(0.0)
    ranked["change_pct"] = ranked["change_pct"].fillna(-999.0)
    ranked = ranked.sort_values(
        by=["amount", "turnover_rate", "volume_ratio", "change_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    return ranked.head(technical_scan_limit).copy()


def _handle_full_scan(
    conditions: str,
    top_n: int = 15,
    max_candidates: int = 120,
) -> dict:
    """Broad-market quote prefilter + targeted technical validation."""
    try:
        conds = json.loads(conditions) if isinstance(conditions, str) else conditions
    except (json.JSONDecodeError, TypeError):
        return {"error": f"Invalid conditions JSON: {conditions}"}

    manager = _get_fetcher_manager()
    quotes_df = _load_full_market_quotes()

    if quotes_df.empty:
        return {"error": "No full-market realtime quote data available", "results": []}

    requested_sectors = conds.get("sectors", [])
    metadata_df = _load_stock_metadata(manager, cache_only=not bool(requested_sectors))

    if not metadata_df.empty:
        universe_df = quotes_df.merge(metadata_df, on="code", how="inner", suffixes=("", "_meta"))
        universe_df["name"] = universe_df["name"].where(universe_df["name"].astype(str).str.strip().ne(""), universe_df["name_meta"])
        universe_df = universe_df.drop(columns=["name_meta"])
    else:
        universe_df = quotes_df.copy()
        universe_df["industry"] = None

    total_market_stocks = len(universe_df)
    sector_filtered_df = _filter_by_requested_sectors(universe_df, conds.get("sectors", []), manager)
    if sector_filtered_df.empty and conds.get("sectors"):
        return {
            "error": f"No stocks matched requested sectors: {conds.get('sectors')}",
            "total_market_stocks": total_market_stocks,
            "results": [],
        }
    if sector_filtered_df.empty:
        sector_filtered_df = universe_df

    quote_filtered_df = _apply_quote_filters(sector_filtered_df, conds)
    if quote_filtered_df.empty:
        return {
            "error": "No stocks passed realtime quote filters",
            "total_market_stocks": total_market_stocks,
            "after_sector_filter": len(sector_filtered_df),
            "after_quote_filter": 0,
            "results": [],
        }

    technical_scan_limit = min(len(quote_filtered_df), max(max_candidates, top_n * 8, 80))
    ranked_df = _rank_quote_candidates(quote_filtered_df, technical_scan_limit)
    codes_to_analyze = ranked_df["code"].tolist()

    ma_results = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(codes_to_analyze)))) as pool:
        futures = {pool.submit(_compute_ma_filter, code): code for code in codes_to_analyze}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                result = None
            if result:
                ma_results[result["code"]] = result

    need_ma_bullish = conds.get("ma_bullish", False)
    final_results = []

    for stock in ranked_df.to_dict(orient="records"):
        ma = ma_results.get(stock["code"])
        if ma is None:
            if need_ma_bullish:
                continue
            stock["ma_bullish"] = None
            stock["bias_ma5"] = None
            stock["ma5"] = None
            stock["ma10"] = None
            stock["ma20"] = None
        else:
            if need_ma_bullish and not ma["ma_bullish"]:
                continue
            if conds.get("bias_ma5_max") is not None and ma["bias_ma5"] is not None and ma["bias_ma5"] > float(conds["bias_ma5_max"]):
                continue
            if conds.get("bias_ma5_min") is not None and ma["bias_ma5"] is not None and ma["bias_ma5"] < float(conds["bias_ma5_min"]):
                continue
            if conds.get("volume_ratio_min") is not None and ma["volume_ratio"] is not None and ma["volume_ratio"] < float(conds["volume_ratio_min"]):
                continue
            if conds.get("volume_ratio_max") is not None and ma["volume_ratio"] is not None and ma["volume_ratio"] > float(conds["volume_ratio_max"]):
                continue

            stock["ma_bullish"] = ma["ma_bullish"]
            stock["bias_ma5"] = ma["bias_ma5"]
            stock["ma5"] = ma["ma5"]
            stock["ma10"] = ma["ma10"]
            stock["ma20"] = ma["ma20"]
            if ma["volume_ratio"] is not None:
                stock["volume_ratio"] = ma["volume_ratio"]

        score = 50
        if stock.get("ma_bullish"):
            score += 20
        bias_ma5 = stock.get("bias_ma5")
        if bias_ma5 is not None:
            if 0 <= bias_ma5 <= 3:
                score += 10
            elif bias_ma5 < 0:
                score += 5
            elif bias_ma5 > 5:
                score -= 15

        volume_ratio = stock.get("volume_ratio")
        if volume_ratio is not None and 0.8 <= volume_ratio <= 2.5:
            score += 5

        change_pct = stock.get("change_pct") or 0
        if 0 < change_pct <= 5:
            score += 5
        elif change_pct > 5:
            score -= 5

        total_mv = stock.get("total_mv")
        market_cap_yi = _round_number(total_mv / 1e8, 2) if total_mv is not None else None
        final_results.append(
            {
                "code": stock.get("code"),
                "name": stock.get("name"),
                "sector": stock.get("industry"),
                "industry": stock.get("industry"),
                "price": _round_number(stock.get("price"), 2),
                "change_pct": _round_number(stock.get("change_pct"), 2),
                "volume_ratio": _round_number(stock.get("volume_ratio"), 2),
                "turnover_rate": _round_number(stock.get("turnover_rate"), 2),
                "pe_ratio": _round_number(stock.get("pe_ratio"), 2),
                "market_cap_yi": market_cap_yi,
                "ma_bullish": stock.get("ma_bullish"),
                "bias_ma5": _round_number(stock.get("bias_ma5"), 2),
                "ma5": _round_number(stock.get("ma5"), 2),
                "ma10": _round_number(stock.get("ma10"), 2),
                "ma20": _round_number(stock.get("ma20"), 2),
                "signal_score": min(100, max(0, score)),
                "quote_source": stock.get("quote_source"),
            }
        )

    final_results.sort(
        key=lambda item: (
            item.get("signal_score", 0),
            item.get("turnover_rate") or 0,
            item.get("volume_ratio") or 0,
            item.get("change_pct") or -999,
        ),
        reverse=True,
    )

    return {
        "market_scope": "a_share_full_market",
        "total_market_stocks": total_market_stocks,
        "after_sector_filter": len(sector_filtered_df),
        "after_quote_filter": len(quote_filtered_df),
        "technical_scan_count": len(codes_to_analyze),
        "technical_scan_truncated": len(quote_filtered_df) > technical_scan_limit,
        "result_count": len(final_results),
        "results": final_results[:top_n],
    }


screen_stocks_full_scan_tool = ToolDefinition(
    name="screen_stocks_full_scan",
    description="Broad-market stock screener. It first loads full-market realtime quotes, "
                "applies quote-level filters across the entire A-share universe, then performs "
                "MA/bias technical validation on the highest-priority filtered candidates. "
                "Use this FIRST before any per-stock analysis tools.",
    parameters=[
        ToolParameter(
            name="conditions",
            type="string",
            description="JSON string with filtering conditions. Keys: "
                        "ma_bullish (bool), bias_ma5_max (float, e.g. 5.0), "
                        "bias_ma5_min (float, e.g. -3.0), volume_ratio_min/max, "
                        "pe_min/max, change_pct_min/max, market_cap_min/max (亿元), "
                        "sectors (array of sector/industry names), exclude_st (bool, default true). "
                        'Example: {"ma_bullish": true, "bias_ma5_max": 3, "volume_ratio_min": 0.5}',
        ),
        ToolParameter(
            name="top_n",
            type="integer",
            description="Maximum number of results to return (default: 15)",
            required=False,
            default=15,
        ),
        ToolParameter(
            name="max_candidates",
            type="integer",
            description="Primary technical-validation budget after quote prefiltering (default: 120).",
            required=False,
            default=120,
        ),
    ],
    handler=_handle_full_scan,
    category="screener",
)


def _handle_get_sector_top_stocks(sector_name: str, top_n: int = 10) -> dict:
    """Get top performing stocks from a specific sector."""
    manager = _get_fetcher_manager()
    df = manager.get_sector_constituents(sector_name=sector_name, limit=top_n)

    if df is None or df.empty:
        return {"error": f"No constituent data for sector '{sector_name}'"}

    records = df.to_dict(orient="records")
    clean_records = []
    for record in records:
        clean = {}
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                clean[key] = None
            else:
                clean[key] = value
        clean_records.append(clean)

    return {
        "sector": sector_name,
        "count": len(clean_records),
        "stocks": clean_records,
    }


get_sector_top_stocks_tool = ToolDefinition(
    name="get_sector_top_stocks",
    description="Get top performing stocks within a specific sector/industry. "
                "Returns constituent stocks with their performance data. "
                "Use this after identifying promising sectors from get_sector_rankings.",
    parameters=[
        ToolParameter(
            name="sector_name",
            type="string",
            description="Sector/industry name in Chinese, e.g., '白酒', '锂电池', '半导体'",
        ),
        ToolParameter(
            name="top_n",
            type="integer",
            description="Number of top stocks to return (default: 10)",
            required=False,
            default=10,
        ),
    ],
    handler=_handle_get_sector_top_stocks,
    category="screener",
)


ALL_SCREENER_TOOLS = [
    screen_stocks_full_scan_tool,
    get_sector_top_stocks_tool,
]
