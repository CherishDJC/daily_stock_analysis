# -*- coding: utf-8 -*-
"""Agent API schemas — Screener history & streaming."""

from typing import Any, List, Optional

from pydantic import BaseModel


# ------------------------------------------------------------------
# Screener History
# ------------------------------------------------------------------

class ScreenerHistoryItem(BaseModel):
    id: int
    query: str
    result_count: int
    strategy_summary: Optional[str] = None
    status: Optional[str] = None
    provider: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None


class ScreenerHistoryResponse(BaseModel):
    records: List[ScreenerHistoryItem]


class ScreenerHistoryDetailResponse(BaseModel):
    id: int
    query: str
    conditions: Optional[Any] = None
    dashboard: Optional[Any] = None
    results: Optional[Any] = None
    report_markdown: Optional[str] = None
    result_count: int = 0
    strategy_summary: Optional[str] = None
    risk_warning: Optional[str] = None
    status: Optional[str] = None
    provider: Optional[str] = None
    error_message: Optional[str] = None
    total_steps: int = 0
    total_tokens: int = 0
    created_at: Optional[str] = None


class ScreenerSaveRequest(BaseModel):
    query: str
    dashboard: Optional[Any] = None
    results: Optional[Any] = None
    report_markdown: Optional[str] = None
    status: Optional[str] = None
    provider: Optional[str] = None
    error_message: Optional[str] = None
    result_count: int = 0
    strategy_summary: Optional[str] = None
    risk_warning: Optional[str] = None
    conditions: Optional[Any] = None
    total_steps: int = 0
    total_tokens: int = 0


class ScreenerRequest(BaseModel):
    query: str
    skills: Optional[List[str]] = None
