# -*- coding: utf-8 -*-
"""
===================================
数据访问层模块初始化
===================================

职责：
1. 导出所有 Repository 类
"""

from src.repositories.analysis_repo import AnalysisRepository
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.reference_data_cache_repo import ReferenceDataCacheRepository
from src.repositories.stock_repo import StockRepository

__all__ = [
    "AnalysisRepository",
    "BacktestRepository",
    "ReferenceDataCacheRepository",
    "StockRepository",
]
