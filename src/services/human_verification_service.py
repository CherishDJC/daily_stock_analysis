# -*- coding: utf-8 -*-
"""Human verification service helpers."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _truthy_env(name: str, default: str = "false") -> bool:
    value = (os.getenv(name, default) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_human_verification_status() -> Dict[str, Any]:
    """Return current human verification configuration exposed to the UI."""
    provider = (os.getenv("HUMAN_VERIFY_PROVIDER", "turnstile") or "").strip().lower()
    enabled = _truthy_env("HUMAN_VERIFY_ENABLED", "false")
    site_key = (os.getenv("TURNSTILE_SITE_KEY") or "").strip()
    secret_key = (os.getenv("TURNSTILE_SECRET_KEY") or "").strip()

    turnstile_ready = enabled and provider == "turnstile" and bool(site_key and secret_key)
    return {
        "enabled": turnstile_ready,
        "provider": "turnstile" if turnstile_ready else None,
        "site_key": site_key if turnstile_ready else None,
    }


def verify_human_token(token: str, remote_ip: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Verify the submitted human verification token."""
    status = get_human_verification_status()
    if not status["enabled"]:
        return True, None

    if not token or not token.strip():
        return False, "请先完成人机验证"

    provider = status["provider"]
    if provider != "turnstile":
        logger.error("Unsupported human verification provider: %s", provider)
        return False, "不支持的人机验证提供方"

    payload = {
        "secret": (os.getenv("TURNSTILE_SECRET_KEY") or "").strip(),
        "response": token.strip(),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        TURNSTILE_SITEVERIFY_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("Turnstile verification HTTP error: %s", exc)
        return False, "人机验证服务异常"
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Turnstile verification failed: %s", exc)
        return False, "人机验证失败，请重试"

    if body.get("success") is True:
        return True, None

    error_codes = body.get("error-codes") or []
    logger.info("Turnstile rejected token: %s", error_codes)
    return False, "人机验证未通过，请重试"
