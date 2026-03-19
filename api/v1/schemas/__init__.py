# -*- coding: utf-8 -*-
"""
===================================
API v1 Schemas 模块初始化
===================================

职责：
1. 导出所有 Pydantic 模型
"""

from api.v1.schemas.common import (
    RootResponse,
    HealthResponse,
    ErrorResponse,
    SuccessResponse,
)
from api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    TaskStatus,
)
from api.v1.schemas.history import (
    HistoryItem,
    HistoryListResponse,
    NewsIntelItem,
    NewsIntelResponse,
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
)
from api.v1.schemas.stocks import (
    StockQuote,
    StockHistoryResponse,
    KLineData,
    MinuteBarData,
    IntradayTradeData,
    StockIntradayResponse,
)
from api.v1.schemas.backtest import (
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestResultItem,
    BacktestResultsResponse,
    PerformanceMetrics,
)
from api.v1.schemas.system_config import (
    SystemConfigFieldSchema,
    SystemConfigCategorySchema,
    SystemConfigSchemaResponse,
    SystemConfigItem,
    SystemConfigResponse,
    SystemConfigUpdateItem,
    UpdateSystemConfigRequest,
    UpdateSystemConfigResponse,
    ValidateSystemConfigRequest,
    ConfigValidationIssue,
    ValidateSystemConfigResponse,
    SystemConfigValidationErrorResponse,
    SystemConfigConflictResponse,
)
from api.v1.schemas.market import (
    PartialError,
    MarketWatchlistItem,
    MarketIndexSnapshot,
    MarketStatsSnapshot,
    SectorSnapshot,
    SectorConstituentItem,
    SectorConstituentResponse,
    MarketOverviewResponse,
)

__all__ = [
    # common
    "RootResponse",
    "HealthResponse",
    "ErrorResponse",
    "SuccessResponse",
    # analysis
    "AnalyzeRequest",
    "AnalysisResultResponse",
    "TaskAccepted",
    "TaskStatus",
    # history
    "HistoryItem",
    "HistoryListResponse",
    "NewsIntelItem",
    "NewsIntelResponse",
    "AnalysisReport",
    "ReportMeta",
    "ReportSummary",
    "ReportStrategy",
    "ReportDetails",
    # stocks
    "StockQuote",
    "StockHistoryResponse",
    "KLineData",
    "MinuteBarData",
    "IntradayTradeData",
    "StockIntradayResponse",
    # backtest
    "BacktestRunRequest",
    "BacktestRunResponse",
    "BacktestResultItem",
    "BacktestResultsResponse",
    "PerformanceMetrics",
    # system config
    "SystemConfigFieldSchema",
    "SystemConfigCategorySchema",
    "SystemConfigSchemaResponse",
    "SystemConfigItem",
    "SystemConfigResponse",
    "SystemConfigUpdateItem",
    "UpdateSystemConfigRequest",
    "UpdateSystemConfigResponse",
    "ValidateSystemConfigRequest",
    "ConfigValidationIssue",
    "ValidateSystemConfigResponse",
    "SystemConfigValidationErrorResponse",
    "SystemConfigConflictResponse",
    # market
    "PartialError",
    "MarketWatchlistItem",
    "MarketIndexSnapshot",
    "MarketStatsSnapshot",
    "SectorSnapshot",
    "SectorConstituentItem",
    "SectorConstituentResponse",
    "MarketOverviewResponse",
]
