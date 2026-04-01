# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. POST /api/v1/stocks/extract-from-image 从图片提取股票代码
2. GET /api/v1/stocks/{code}/quote 实时行情接口
3. GET /api/v1/stocks/{code}/history 历史行情接口
4. GET /api/v1/stocks/{code}/intraday 分钟级行情接口
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.v1.schemas.stocks import (
    ExtractFromImageResponse,
    FundFlowData,
    IntradayTradeData,
    KLineData,
    MinuteBarData,
    StockFundFlowResponse,
    StockHistoryResponse,
    StockIntradayResponse,
    StockMetaResponse,
    StockQuote,
    StockSearchResponse,
    StockSearchResult,
)
from api.v1.schemas.common import ErrorResponse
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.stock_service import StockService

logger = logging.getLogger(__name__)

router = APIRouter()

# 须在 /{stock_code} 路由之前定义
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "提取的股票代码"},
        400: {"description": "图片无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从图片提取股票代码",
    description="上传截图/图片，通过 Vision LLM 提取股票代码。支持 JPEG、PNG、WebP、GIF，最大 5MB。",
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> ExtractFromImageResponse:
    """
    从上传的图片中提取股票代码（使用 Vision LLM）。

    表单字段请使用 file 上传图片。优先级：Gemini / Anthropic / OpenAI（首个可用）。
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # 先读取限定大小，再检查是否还有剩余（语义清晰：超出则拒绝）
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"读取上传文件失败: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        )

    try:
        codes, raw_text = extract_stock_codes_from_image(data, content_type)
        return ExtractFromImageResponse(
            codes=codes,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"图片提取失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "图片提取失败"},
        )


# In-memory cache for stock list (loaded once, refreshed every 24h)
_stock_list_cache: Optional[List[Dict[str, Optional[str]]]] = None
_stock_list_cache_time: float = 0
_STOCK_LIST_CACHE_TTL = 24 * 3600  # 24 hours


def _load_stock_list() -> List[Dict[str, Optional[str]]]:
    """Load A-share stock list with caching."""
    global _stock_list_cache, _stock_list_cache_time

    import time

    now = time.time()
    if _stock_list_cache is not None and (now - _stock_list_cache_time) < _STOCK_LIST_CACHE_TTL:
        return _stock_list_cache

    df = None

    # 1. AkShare stock_info_a_code_name (fast, free, no token)
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            col_map = {}
            if "code" not in df.columns and "代码" in df.columns:
                col_map["代码"] = "code"
            if "name" not in df.columns and "名称" in df.columns:
                col_map["名称"] = "name"
            if col_map:
                df = df.rename(columns=col_map)
    except Exception as e:
        logger.debug(f"akshare stock_info_a_code_name 失败: {e}")

    # 2. Fallback: DataFetcherManager (slow, needs Tushare/Baostock)
    if df is None or (hasattr(df, 'empty') and df.empty):
        try:
            from data_provider import DataFetcherManager
            manager = DataFetcherManager()
            df = manager.get_stock_list()
        except Exception as e:
            logger.debug(f"DataFetcherManager.get_stock_list 失败: {e}")

    if df is None or (hasattr(df, 'empty') and df.empty):
        return _stock_list_cache or []

    records = []
    for _, row in df.iterrows():
        records.append({
            "code": str(row.get("code", "")).strip(),
            "name": str(row.get("name", "")).strip(),
            "industry": str(row.get("industry", "")).strip() or None,
        })

    _stock_list_cache = records
    _stock_list_cache_time = now
    logger.info(f"股票列表缓存已更新: {len(records)} 条")
    return records


@router.get(
    "/search",
    response_model=StockSearchResponse,
    responses={
        200: {"description": "搜索结果"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="搜索股票",
    description="按代码或名称模糊搜索 A 股股票，返回匹配的股票列表。",
)
def search_stocks(
    q: str = Query(..., min_length=1, description="搜索关键词（代码或名称）"),
    limit: int = Query(10, ge=1, le=20, description="最大返回条数"),
) -> StockSearchResponse:
    """模糊搜索 A 股股票。"""
    try:
        stock_list = _load_stock_list()
        if not stock_list:
            return StockSearchResponse(results=[])

        query_lower = q.lower()
        results = []
        for item in stock_list:
            if query_lower in item["code"].lower() or query_lower in item["name"].lower():
                results.append(
                    StockSearchResult(
                        code=item["code"],
                        name=item["name"],
                        industry=item.get("industry"),
                    )
                )
                if len(results) >= limit:
                    break

        return StockSearchResponse(results=results)

    except Exception as e:
        logger.error(f"股票搜索失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"搜索失败: {str(e)}"},
        )


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情

    获取指定股票的最新行情数据

    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）

    Returns:
        StockQuote: 实时行情数据

    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()

        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )

        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/meta",
    response_model=StockMetaResponse,
    responses={
        200: {"description": "股票基础信息"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票基础信息",
    description="获取指定股票的基础信息、所属行业与所属板块摘要",
)
def get_stock_meta(stock_code: str) -> StockMetaResponse:
    """获取股票基础信息摘要。"""
    try:
        service = StockService()
        result = service.get_stock_meta_data(stock_code=stock_code)
        return StockMetaResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            source=result.get("source"),
            updated_at=result.get("updated_at"),
            industry=result.get("industry"),
            market=result.get("market"),
            area=result.get("area"),
            list_date=result.get("list_date"),
            full_name=result.get("full_name"),
            website=result.get("website"),
            main_business=result.get("main_business"),
            employees=result.get("employees"),
            pe_ratio=result.get("pe_ratio"),
            pb_ratio=result.get("pb_ratio"),
            total_market_value=result.get("total_market_value"),
            circulating_market_value=result.get("circulating_market_value"),
            belong_boards=result.get("belong_boards") or [],
        )
    except Exception as e:
        logger.error(f"获取基础信息失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取基础信息失败: {str(e)}",
            },
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情

    获取指定股票的历史 K 线数据

    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数

    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()

        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )

        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]

        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )

    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取历史行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/intraday",
    response_model=StockIntradayResponse,
    responses={
        200: {"description": "分钟级行情数据"},
        422: {"description": "不支持的分钟周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票分钟级行情",
    description="获取指定股票的分钟 K 线和最近逐笔成交（免费数据源版）",
)
def get_stock_intraday(
    stock_code: str,
    interval: str = Query("1", description="分钟周期", pattern="^(1|5|15|30|60)$"),
    limit: int = Query(240, ge=30, le=960, description="分钟K返回条数"),
    include_trades: bool = Query(True, description="是否附带最近逐笔成交"),
) -> StockIntradayResponse:
    """Get stock intraday minute bars and recent trades."""
    try:
        service = StockService()
        result = service.get_intraday_data(
            stock_code=stock_code,
            interval=interval,
            limit=limit,
            include_trades=include_trades,
        )

        bars = [
            MinuteBarData(
                timestamp=item.get("timestamp"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent"),
            )
            for item in result.get("bars", [])
        ]
        trades = [
            IntradayTradeData(
                timestamp=item.get("timestamp"),
                price=item.get("price"),
                volume=item.get("volume"),
                side=item.get("side"),
            )
            for item in result.get("trades", [])
        ]

        return StockIntradayResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            interval=result.get("interval", interval),
            source=result.get("source"),
            trades_source=result.get("trades_source"),
            updated_at=result.get("updated_at"),
            bars=bars,
            trades=trades,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_interval",
                "message": str(e),
            },
        )
    except Exception as e:
        logger.error(f"获取分钟行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取分钟行情失败: {str(e)}",
            },
        )


@router.get(
    "/{stock_code}/fund-flow",
    response_model=StockFundFlowResponse,
    responses={
        200: {"description": "个股资金流向数据"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取个股资金流向",
    description="获取指定股票最近若干交易日的主力资金流向明细",
)
def get_stock_fund_flow(
    stock_code: str,
    limit: int = Query(10, ge=3, le=30, description="最近返回条数"),
) -> StockFundFlowResponse:
    """Get stock fund flow details."""
    try:
        service = StockService()
        result = service.get_fund_flow_data(stock_code=stock_code, limit=limit)

        data = [
            FundFlowData(
                date=item.get("date"),
                close=item.get("close"),
                change_percent=item.get("change_percent"),
                main_net_inflow=item.get("main_net_inflow"),
                main_net_inflow_ratio=item.get("main_net_inflow_ratio"),
                super_large_net_inflow=item.get("super_large_net_inflow"),
                super_large_net_inflow_ratio=item.get("super_large_net_inflow_ratio"),
                large_net_inflow=item.get("large_net_inflow"),
                large_net_inflow_ratio=item.get("large_net_inflow_ratio"),
                medium_net_inflow=item.get("medium_net_inflow"),
                medium_net_inflow_ratio=item.get("medium_net_inflow_ratio"),
                small_net_inflow=item.get("small_net_inflow"),
                small_net_inflow_ratio=item.get("small_net_inflow_ratio"),
            )
            for item in result.get("data", [])
        ]

        return StockFundFlowResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            source=result.get("source"),
            updated_at=result.get("updated_at"),
            data=data,
        )
    except Exception as e:
        logger.error(f"获取资金流向失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取资金流向失败: {str(e)}",
            },
        )
