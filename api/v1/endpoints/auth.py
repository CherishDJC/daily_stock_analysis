# -*- coding: utf-8 -*-
"""Authentication endpoints for Web admin login."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from src.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE_HOURS_DEFAULT,
    change_password,
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_fixed_admin_username,
    get_client_ip,
    is_auth_enabled,
    is_password_changeable,
    is_password_set,
    log_auth_event,
    record_login_failure,
    set_initial_password,
    uses_fixed_credentials,
    validate_request_origin,
    verify_login_credentials,
    verify_password,
    verify_session,
)
from src.services.human_verification_service import (
    get_human_verification_status,
    verify_human_token,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request body."""

    model_config = {"populate_by_name": True}

    username: str = Field(default="", description="Admin username")
    password: str = Field(default="", description="Admin password")
    human_token: str | None = Field(default=None, alias="humanToken", description="Human verification token")


class ChangePasswordRequest(BaseModel):
    """Change password request body."""

    model_config = {"populate_by_name": True}

    current_password: str = Field(default="", alias="currentPassword")
    new_password: str = Field(default="", alias="newPassword")
    new_password_confirm: str = Field(default="", alias="newPasswordConfirm")


def _cookie_params(request: Request) -> dict:
    """Build cookie params including Secure based on request."""
    secure = False
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        proto = request.headers.get("X-Forwarded-Proto", "").lower()
        secure = proto == "https"
    else:
        # Check URL scheme when not behind proxy
        secure = request.url.scheme == "https"

    try:
        max_age_hours = int(os.getenv("ADMIN_SESSION_MAX_AGE_HOURS", str(SESSION_MAX_AGE_HOURS_DEFAULT)))
    except ValueError:
        max_age_hours = SESSION_MAX_AGE_HOURS_DEFAULT
    max_age = max_age_hours * 3600

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": max_age,
    }


@router.get(
    "/status",
    summary="Get auth status",
    description="Returns whether auth is enabled and if the current request is logged in.",
)
async def auth_status(request: Request):
    """Return authEnabled, loggedIn, passwordSet, passwordChangeable without requiring auth."""
    auth_enabled = is_auth_enabled()
    logged_in = False
    human_status = get_human_verification_status()
    if auth_enabled:
        cookie_val = request.cookies.get(COOKIE_NAME)
        logged_in = verify_session(cookie_val) if cookie_val else False
    return {
        "authEnabled": auth_enabled,
        "loggedIn": logged_in,
        "passwordSet": True if auth_enabled and uses_fixed_credentials() else (is_password_set() if auth_enabled else False),
        "passwordChangeable": False if auth_enabled and uses_fixed_credentials() else (is_password_changeable() if auth_enabled else False),
        "usernameRequired": auth_enabled,
        "fixedUsername": get_fixed_admin_username() if auth_enabled and uses_fixed_credentials() else None,
        "humanVerificationEnabled": human_status["enabled"],
        "humanVerificationProvider": human_status["provider"],
        "turnstileSiteKey": human_status["site_key"],
    }


@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. If password not set yet, accepts password+passwordConfirm.",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password, set cookie on success. Returns 401 or 429 on failure."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=400,
            content={"error": "auth_disabled", "message": "Authentication is not configured"},
        )

    origin_ok, origin_error = validate_request_origin(request)
    if not origin_ok:
        ip = get_client_ip(request)
        log_auth_event(
            event_type="origin_rejected",
            ip=ip,
            username=(body.username or "").strip() or None,
            path=str(request.url.path),
            user_agent=request.headers.get("User-Agent"),
            success=False,
            detail=origin_error,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "origin_not_allowed", "message": origin_error or "请求来源不被允许"},
        )

    username = (body.username or "").strip()
    password = (body.password or "").strip()
    if not username:
        return JSONResponse(
            status_code=400,
            content={"error": "username_required", "message": "请输入用户名"},
        )
    if not password:
        return JSONResponse(
            status_code=400,
            content={"error": "password_required", "message": "请输入密码"},
        )

    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        log_auth_event(
            event_type="login_rate_limited",
            ip=ip,
            username=username or None,
            path=str(request.url.path),
            user_agent=request.headers.get("User-Agent"),
            success=False,
            detail="too_many_failures",
        )
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": "Too many failed attempts. Please try again later.",
            },
        )

    human_ok, human_error = verify_human_token(body.human_token or "", remote_ip=ip)
    if not human_ok:
        record_login_failure(ip)
        log_auth_event(
            event_type="login_failed",
            ip=ip,
            username=username or None,
            path=str(request.url.path),
            user_agent=request.headers.get("User-Agent"),
            success=False,
            detail=human_error,
        )
        return JSONResponse(
            status_code=400,
            content={"error": "human_verification_failed", "message": human_error or "人机验证失败"},
        )

    if uses_fixed_credentials():
        if not verify_login_credentials(username=username, password=password):
            record_login_failure(ip)
            log_auth_event(
                event_type="login_failed",
                ip=ip,
                username=username or None,
                path=str(request.url.path),
                user_agent=request.headers.get("User-Agent"),
                success=False,
                detail="invalid_credentials",
            )
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_credentials", "message": "用户名或密码错误"},
            )
    else:
        password_set = is_password_set()
        if not password_set:
            err = set_initial_password(password)
            if err:
                record_login_failure(ip)
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_password", "message": err},
                )
        elif not verify_password(password):
            record_login_failure(ip)
            log_auth_event(
                event_type="login_failed",
                ip=ip,
                username=username or None,
                path=str(request.url.path),
                user_agent=request.headers.get("User-Agent"),
                success=False,
                detail="invalid_password",
            )
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_password", "message": "密码错误"},
            )

    clear_rate_limit(ip)
    session_val = create_session()
    if not session_val:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to create session"},
        )

    resp = JSONResponse(content={"ok": True})
    log_auth_event(
        event_type="login_success",
        ip=ip,
        username=username or None,
        path=str(request.url.path),
        user_agent=request.headers.get("User-Agent"),
        success=True,
        detail="login_ok",
    )
    params = _cookie_params(request)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=session_val,
        httponly=params["httponly"],
        samesite=params["samesite"],
        secure=params["secure"],
        path=params["path"],
        max_age=params["max_age"],
    )
    return resp


@router.post(
    "/change-password",
    summary="Change password",
    description="Change password. Requires valid session.",
)
async def auth_change_password(request: Request, body: ChangePasswordRequest):
    """Change password. Requires login."""
    origin_ok, origin_error = validate_request_origin(request)
    if not origin_ok:
        ip = get_client_ip(request)
        log_auth_event(
            event_type="origin_rejected",
            ip=ip,
            path=str(request.url.path),
            user_agent=request.headers.get("User-Agent"),
            success=False,
            detail=origin_error,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "origin_not_allowed", "message": origin_error or "请求来源不被允许"},
        )

    if uses_fixed_credentials():
        return JSONResponse(
            status_code=400,
            content={"error": "not_changeable", "message": "固定账号模式不支持在线修改密码"},
        )
    if not is_password_changeable():
        return JSONResponse(
            status_code=400,
            content={"error": "not_changeable", "message": "Password cannot be changed via web"},
        )

    current = (body.current_password or "").strip()
    new_pwd = (body.new_password or "").strip()
    new_confirm = (body.new_password_confirm or "").strip()

    if not current:
        return JSONResponse(
            status_code=400,
            content={"error": "current_required", "message": "请输入当前密码"},
        )
    if new_pwd != new_confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "password_mismatch", "message": "两次输入的新密码不一致"},
        )

    err = change_password(current, new_pwd)
    if err:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": err},
        )
    return Response(status_code=204)


@router.post(
    "/logout",
    summary="Logout",
    description="Clear session cookie.",
)
async def auth_logout(request: Request):
    """Clear session cookie."""
    origin_ok, origin_error = validate_request_origin(request)
    if not origin_ok:
        ip = get_client_ip(request)
        log_auth_event(
            event_type="origin_rejected",
            ip=ip,
            path=str(request.url.path),
            user_agent=request.headers.get("User-Agent"),
            success=False,
            detail=origin_error,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "origin_not_allowed", "message": origin_error or "请求来源不被允许"},
        )

    ip = get_client_ip(request)
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    log_auth_event(
        event_type="logout",
        ip=ip,
        path=str(request.url.path),
        user_agent=request.headers.get("User-Agent"),
        success=True,
        detail="logout",
    )
    return resp
