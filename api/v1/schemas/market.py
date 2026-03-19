# -*- coding: utf-8 -*-
"""
===================================
实时看盘相关模型
===================================

职责：
1. 定义实时看盘聚合响应模型
2. 描述自选股、指数、市场宽度和板块排行结构
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PartialError(BaseModel):
    """Partial error entry for non-blocking data fetch failures."""

    scope: str = Field(..., description="Failed data scope, e.g. watchlist_quote or indices")
    target: str = Field(..., description="Failed target identifier")
    message: str = Field(..., description="Human-readable failure message")


class MarketWatchlistItem(BaseModel):
    """Aggregated watchlist quote row."""

    stock_code: str = Field(..., description="Stock code")
    stock_name: Optional[str] = Field(None, description="Stock name")
    status: Literal["ok", "error"] = Field(..., description="Quote fetch status")
    error_message: Optional[str] = Field(None, description="Failure message when status=error")
    current_price: Optional[float] = Field(None, description="Latest price")
    change: Optional[float] = Field(None, description="Price change amount")
    change_percent: Optional[float] = Field(None, description="Price change percentage")
    open: Optional[float] = Field(None, description="Open price")
    high: Optional[float] = Field(None, description="Session high")
    low: Optional[float] = Field(None, description="Session low")
    prev_close: Optional[float] = Field(None, description="Previous close")
    volume: Optional[float] = Field(None, description="Volume")
    amount: Optional[float] = Field(None, description="Turnover amount")
    volume_ratio: Optional[float] = Field(None, description="Volume ratio")
    turnover_rate: Optional[float] = Field(None, description="Turnover rate")
    amplitude: Optional[float] = Field(None, description="Amplitude percentage")
    source: Optional[str] = Field(None, description="Realtime data source")
    price_position: Optional[float] = Field(None, description="Normalized position within low-high range")


class MarketIndexSnapshot(BaseModel):
    """Major index snapshot."""

    code: str = Field(..., description="Index code")
    name: str = Field(..., description="Index name")
    current: Optional[float] = Field(None, description="Current level")
    change: Optional[float] = Field(None, description="Change amount")
    change_pct: Optional[float] = Field(None, description="Change percentage")
    open: Optional[float] = Field(None, description="Open level")
    high: Optional[float] = Field(None, description="High level")
    low: Optional[float] = Field(None, description="Low level")
    prev_close: Optional[float] = Field(None, description="Previous close")
    volume: Optional[float] = Field(None, description="Volume")
    amount: Optional[float] = Field(None, description="Turnover amount")
    amplitude: Optional[float] = Field(None, description="Amplitude percentage")


class MarketStatsSnapshot(BaseModel):
    """Market breadth and turnover snapshot."""

    up_count: Optional[int] = Field(None, description="Number of rising stocks")
    down_count: Optional[int] = Field(None, description="Number of falling stocks")
    flat_count: Optional[int] = Field(None, description="Number of unchanged stocks")
    limit_up_count: Optional[int] = Field(None, description="Number of limit-up stocks")
    limit_down_count: Optional[int] = Field(None, description="Number of limit-down stocks")
    total_amount: Optional[float] = Field(None, description="Total turnover amount")


class SectorSnapshot(BaseModel):
    """Sector ranking entry."""

    name: str = Field(..., description="Sector name")
    change_pct: Optional[float] = Field(None, description="Sector change percentage")


class SectorConstituentItem(BaseModel):
    """Related stock row for a sector detail drill-down."""

    stock_code: str = Field(..., description="Stock code")
    stock_name: Optional[str] = Field(None, description="Stock name")
    industry: Optional[str] = Field(None, description="Industry name")
    area: Optional[str] = Field(None, description="Region or area")
    status: Literal["ok", "error"] = Field(..., description="Quote fetch status")
    error_message: Optional[str] = Field(None, description="Failure message when status=error")
    current_price: Optional[float] = Field(None, description="Latest price")
    change: Optional[float] = Field(None, description="Price change amount")
    change_percent: Optional[float] = Field(None, description="Price change percentage")
    volume_ratio: Optional[float] = Field(None, description="Volume ratio")
    turnover_rate: Optional[float] = Field(None, description="Turnover rate")
    amount: Optional[float] = Field(None, description="Turnover amount")
    source: Optional[str] = Field(None, description="Realtime data source")


class SectorConstituentResponse(BaseModel):
    """Sector detail drill-down response."""

    sector_name: str = Field(..., description="Selected sector name")
    total_matched: int = Field(..., description="Total matched stocks before truncation")
    limit: int = Field(..., description="Maximum number of rows returned")
    updated_at: str = Field(..., description="Snapshot generation timestamp")
    constituents: List[SectorConstituentItem] = Field(default_factory=list, description="Matched stock rows")
    partial_errors: List[PartialError] = Field(default_factory=list, description="Non-blocking partial failures")


class MarketOverviewResponse(BaseModel):
    """Realtime monitor overview response."""

    trading_date: str = Field(..., description="Trading date in Asia/Shanghai")
    session_state: Literal["pre_open", "open", "midday_break", "after_close", "non_trading_day"] = Field(
        ...,
        description="Current A-share session state",
    )
    realtime_enabled: bool = Field(..., description="Whether realtime quote is enabled")
    updated_at: str = Field(..., description="Snapshot generation timestamp")
    refresh_interval_seconds: int = Field(..., description="Suggested client polling interval")
    watchlist_total: int = Field(..., description="Configured STOCK_LIST size")
    supported_total: int = Field(..., description="Number of supported A-share watchlist items")
    unsupported_codes: List[str] = Field(default_factory=list, description="Unsupported non-A-share codes")
    watchlist: List[MarketWatchlistItem] = Field(default_factory=list, description="A-share watchlist quotes")
    indices: List[MarketIndexSnapshot] = Field(default_factory=list, description="Major A-share indices")
    market_stats: MarketStatsSnapshot = Field(..., description="Market breadth snapshot")
    top_sectors: List[SectorSnapshot] = Field(default_factory=list, description="Top gaining sectors")
    bottom_sectors: List[SectorSnapshot] = Field(default_factory=list, description="Top losing sectors")
    partial_errors: List[PartialError] = Field(default_factory=list, description="Non-blocking partial failures")

    class Config:
        json_schema_extra = {
            "example": {
                "trading_date": "2026-03-18",
                "session_state": "open",
                "realtime_enabled": True,
                "updated_at": "2026-03-18T10:15:00+08:00",
                "refresh_interval_seconds": 5,
                "watchlist_total": 3,
                "supported_total": 2,
                "unsupported_codes": ["AAPL"],
                "watchlist": [
                    {
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                        "status": "ok",
                        "error_message": None,
                        "current_price": 1820.0,
                        "change": 12.5,
                        "change_percent": 0.69,
                        "open": 1810.0,
                        "high": 1828.0,
                        "low": 1805.0,
                        "prev_close": 1807.5,
                        "volume": 950000,
                        "amount": 1730000000,
                        "volume_ratio": 1.23,
                        "turnover_rate": 0.62,
                        "amplitude": 1.27,
                        "source": "efinance",
                        "price_position": 0.65,
                    }
                ],
                "indices": [],
                "market_stats": {
                    "up_count": 3600,
                    "down_count": 1400,
                    "flat_count": 120,
                    "limit_up_count": 82,
                    "limit_down_count": 4,
                    "total_amount": 8123.5,
                },
                "top_sectors": [{"name": "半导体", "change_pct": 3.2}],
                "bottom_sectors": [{"name": "煤炭", "change_pct": -1.1}],
                "partial_errors": [],
            }
        }
