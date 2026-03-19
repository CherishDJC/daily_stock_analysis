# -*- coding: utf-8 -*-
"""
===================================
股票数据相关模型
===================================

职责：
1. 定义股票实时行情模型
2. 定义历史 K 线数据模型
"""

from typing import Optional, List

from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """股票实时行情"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    current_price: float = Field(..., description="当前价格")
    change: Optional[float] = Field(None, description="涨跌额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    prev_close: Optional[float] = Field(None, description="昨收价")
    volume: Optional[float] = Field(None, description="成交量（股）")
    amount: Optional[float] = Field(None, description="成交额（元）")
    update_time: Optional[str] = Field(None, description="更新时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "current_price": 1800.00,
                "change": 15.00,
                "change_percent": 0.84,
                "open": 1785.00,
                "high": 1810.00,
                "low": 1780.00,
                "prev_close": 1785.00,
                "volume": 10000000,
                "amount": 18000000000,
                "update_time": "2024-01-01T15:00:00"
            }
        }


class KLineData(BaseModel):
    """K 线数据点"""
    
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2024-01-01",
                "open": 1785.00,
                "high": 1810.00,
                "low": 1780.00,
                "close": 1800.00,
                "volume": 10000000,
                "amount": 18000000000,
                "change_percent": 0.84
            }
        }


class MinuteBarData(BaseModel):
    """Minute bar data point."""

    timestamp: str = Field(..., description="分钟时间")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    change_percent: Optional[float] = Field(None, description="相对前一根涨跌幅 (%)")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2026-03-19 10:30:00",
                "open": 38.88,
                "high": 39.03,
                "low": 38.82,
                "close": 39.01,
                "volume": 56900,
                "amount": 2218526.01,
                "change_percent": 0.18,
            }
        }


class IntradayTradeData(BaseModel):
    """Intraday trade data point."""

    timestamp: str = Field(..., description="成交时间")
    price: float = Field(..., description="成交价")
    volume: Optional[float] = Field(None, description="成交量（手）")
    side: Optional[str] = Field(None, description="买卖盘性质")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "10:31:27",
                "price": 39.01,
                "volume": 67.0,
                "side": "买盘",
            }
        }


class ExtractFromImageResponse(BaseModel):
    """图片股票代码提取响应"""

    codes: List[str] = Field(..., description="提取的股票代码（已去重）")
    raw_text: Optional[str] = Field(None, description="原始 LLM 响应（调试用）")


class StockHistoryResponse(BaseModel):
    """股票历史行情响应"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    period: str = Field(..., description="K 线周期")
    data: List[KLineData] = Field(default_factory=list, description="K 线数据列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "period": "daily",
                "data": []
            }
        }


class StockIntradayResponse(BaseModel):
    """Stock intraday minute response."""

    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    interval: str = Field(..., description="分钟周期")
    source: Optional[str] = Field(None, description="分钟K线数据源")
    trades_source: Optional[str] = Field(None, description="逐笔成交数据源")
    updated_at: Optional[str] = Field(None, description="更新时间")
    bars: List[MinuteBarData] = Field(default_factory=list, description="分钟K线数据")
    trades: List[IntradayTradeData] = Field(default_factory=list, description="最近逐笔成交")

    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "301428",
                "stock_name": "世纪恒通",
                "interval": "1",
                "source": "AkshareFetcher",
                "trades_source": "AkshareFetcher",
                "updated_at": "2026-03-19T10:31:30+08:00",
                "bars": [],
                "trades": [],
            }
        }
