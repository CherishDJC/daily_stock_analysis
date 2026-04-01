# -*- coding: utf-8 -*-
"""
===================================
实时看盘接口
===================================

职责：
1. 提供 GET /api/v1/market/overview 聚合看盘快照接口
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.market import MarketOverviewResponse, SectorConstituentResponse
from src.services.market_monitor_service import get_market_monitor_service
from src.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Watchlist management
# ============================================================

class WatchlistAddBody(BaseModel):
    codes: List[str] = Field(..., description="要添加的股票代码列表")


class WatchlistAddResponse(BaseModel):
    added: int = Field(..., description="实际新增数量")
    watchlist_total: int = Field(..., description="自选股总数")


class WatchlistRemoveResponse(BaseModel):
    removed: str = Field(..., description="被移除的股票代码")
    watchlist_total: int = Field(..., description="自选股总数")


class WatchlistResponse(BaseModel):
    codes: List[str] = Field(..., description="当前自选股代码列表")


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    summary="获取自选股列表",
    description="返回当前自选股中的所有股票代码。",
)
def get_watchlist() -> WatchlistResponse:
    config = get_config()
    return WatchlistResponse(codes=config.stock_list)


@router.post(
    "/watchlist",
    response_model=WatchlistAddResponse,
    summary="添加股票到自选股",
    description="将股票代码添加到自选股列表，自动去重。",
)
def add_to_watchlist(request: WatchlistAddBody) -> WatchlistAddResponse:
    config = get_config()
    added = config.add_stocks(request.codes)
    return WatchlistAddResponse(
        added=added,
        watchlist_total=len(config.stock_list),
    )


@router.delete(
    "/watchlist/{code}",
    response_model=WatchlistRemoveResponse,
    summary="从自选股移除",
    description="从自选股列表中移除指定股票代码。",
)
def remove_from_watchlist(code: str) -> WatchlistRemoveResponse:
    config = get_config()
    removed = config.remove_stock(code)
    if not removed:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不在自选股中")
    return WatchlistRemoveResponse(
        removed=code,
        watchlist_total=len(config.stock_list),
    )


@router.get(
    "/overview",
    response_model=MarketOverviewResponse,
    responses={
        200: {"description": "A-share realtime market overview snapshot"},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="获取实时看盘总览",
    description="聚合自选股行情、指数、市场宽度和板块排行，用于 Web 实时看盘页面。",
)
def get_market_overview(
    force_refresh: bool = Query(False, description="Bypass in-memory cache and refresh immediately"),
    include_watchlist: bool = Query(True, description="Include watchlist snapshot rows"),
    include_summary: bool = Query(True, description="Include indices, market breadth, and sector rankings"),
) -> MarketOverviewResponse:
    """Return a realtime A-share monitor snapshot."""
    try:
        service = get_market_monitor_service()
        return MarketOverviewResponse(
            **service.get_overview(
                force_refresh=force_refresh,
                include_watchlist=include_watchlist,
                include_summary=include_summary,
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get market overview: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时看盘总览失败: {exc}",
            },
        )


@router.get(
    "/sectors/{sector_name}/constituents",
    response_model=SectorConstituentResponse,
    responses={
        200: {"description": "A-share sector related stocks"},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="获取板块相关股",
    description="按行业名称返回最多 10 条 A 股相关股票信息，用于 Web 看盘页板块冷热钻取。",
)
def get_sector_constituents(
    sector_name: str,
    force_refresh: bool = Query(False, description="Bypass in-memory cache and refresh immediately"),
    limit: int = Query(10, ge=1, le=10, description="Maximum number of related stocks to return"),
) -> SectorConstituentResponse:
    """Return up to N related A-share stocks for the selected sector."""
    try:
        service = get_market_monitor_service()
        return SectorConstituentResponse(
            **service.get_sector_constituents(
                sector_name=sector_name,
                force_refresh=force_refresh,
                limit=limit,
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get sector constituents for %s: %s", sector_name, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取板块相关股失败: {exc}",
            },
        )
