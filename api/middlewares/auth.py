# -*- coding: utf-8 -*-
"""
Auth middleware: protect /api/v1/* when admin auth is enabled.
"""

from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import (
    COOKIE_NAME,
    get_client_ip,
    is_auth_enabled,
    log_auth_event,
    validate_request_origin,
    verify_session,
)

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({
    "/login",
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/v1/auth/logout",
    "/api/health",
    "/health",
})

EXEMPT_PREFIXES = (
    "/assets/",
    "/api/v1/auth/",
)
HTML_LOGIN_PATHS = {"/docs", "/redoc"}


def _path_exempt(path: str) -> bool:
    """Check if path is exempt from auth."""
    normalized = path.rstrip("/") or "/"
    return normalized in EXEMPT_PATHS or any(normalized.startswith(prefix) for prefix in EXEMPT_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid session for /api/v1/* when auth is enabled."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        if not is_auth_enabled():
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path):
            return await call_next(request)

        if path in HTML_LOGIN_PATHS or (not path.startswith("/api/v1/") and not path.startswith("/api/") and path != "/openapi.json"):
            cookie_val = request.cookies.get(COOKIE_NAME)
            if cookie_val and verify_session(cookie_val):
                return await call_next(request)
            log_auth_event(
                event_type="unauthorized_page",
                ip=get_client_ip(request),
                path=path,
                user_agent=request.headers.get("User-Agent"),
                success=False,
                detail="login_required",
            )
            redirect_target = path
            if request.url.query:
                redirect_target = f"{redirect_target}?{request.url.query}"
            login_url = f"/login?redirect={quote(redirect_target, safe='')}"
            return RedirectResponse(url=login_url, status_code=307)

        cookie_val = request.cookies.get(COOKIE_NAME)
        if not cookie_val or not verify_session(cookie_val):
            log_auth_event(
                event_type="unauthorized_api",
                ip=get_client_ip(request),
                path=path,
                user_agent=request.headers.get("User-Agent"),
                success=False,
                detail="login_required",
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Login required",
                },
            )

        origin_ok, origin_error = validate_request_origin(request)
        if not origin_ok:
            log_auth_event(
                event_type="origin_rejected",
                ip=get_client_ip(request),
                path=path,
                user_agent=request.headers.get("User-Agent"),
                success=False,
                detail=origin_error,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "origin_not_allowed",
                    "message": origin_error or "请求来源不被允许",
                },
            )

        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API routes.

    The middleware is always registered; whether auth is enforced is determined
    at request time by is_auth_enabled() so the decision stays consistent across
    any runtime configuration reload.
    """
    app.add_middleware(AuthMiddleware)
