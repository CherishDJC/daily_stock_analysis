# -*- coding: utf-8 -*-
"""Utilities for normalizing and sanitizing news titles and snippets."""

from __future__ import annotations

import html
import re
from typing import Optional


_WHITESPACE_RE = re.compile(r"\s+")

_SAFE_EXTRA_CHARS = set(
    " \t\r\n"
    ".,!?;:'\"()[]{}<>/%&@#$^*+-_=|~`\\"
    "，。！？；：、“”‘’（）《》【】—…·％"
    "℃°"
)


def _is_cjk_or_common_asian(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _is_safe_char(ch: str) -> bool:
    if ch in _SAFE_EXTRA_CHARS:
        return True
    if ch.isascii() and ch.isalnum():
        return True
    if _is_cjk_or_common_asian(ch):
        return True
    return False


def normalize_news_text(text: Optional[str]) -> str:
    """Unescape HTML entities and collapse repeated whitespace."""
    cleaned = html.unescape(text or "")
    cleaned = cleaned.replace("\x00", " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def is_probably_garbled_text(text: Optional[str]) -> bool:
    """Heuristically detect mojibake-like text from mis-decoded snippets."""
    cleaned = normalize_news_text(text)
    if not cleaned:
        return False
    if "\ufffd" in cleaned:
        return True

    meaningful = [ch for ch in cleaned if not ch.isspace()]
    if len(meaningful) < 12:
        return False

    suspicious = sum(1 for ch in meaningful if not _is_safe_char(ch))
    if suspicious == 0:
        return False

    suspicious_ratio = suspicious / len(meaningful)
    cjk_count = sum(1 for ch in meaningful if _is_cjk_or_common_asian(ch))
    ascii_alnum_count = sum(1 for ch in meaningful if ch.isascii() and ch.isalnum())
    ascii_alnum_ratio = ascii_alnum_count / len(meaningful)
    cjk_ratio = cjk_count / len(meaningful)

    if suspicious >= 8 and suspicious_ratio >= 0.18:
        return True
    if suspicious >= 5 and suspicious_ratio >= 0.12 and cjk_ratio < 0.2 and ascii_alnum_ratio < 0.55:
        return True
    return False


def sanitize_news_title(text: Optional[str], fallback: str = "未命名资讯") -> str:
    """Normalize a news title and replace unreadable text with a safe fallback."""
    cleaned = normalize_news_text(text)
    if not cleaned:
        return fallback
    if is_probably_garbled_text(cleaned):
        return fallback
    return cleaned


def sanitize_news_snippet(text: Optional[str]) -> str:
    """Normalize a news snippet and drop mojibake-like content."""
    cleaned = normalize_news_text(text)
    if not cleaned:
        return ""
    if is_probably_garbled_text(cleaned):
        return ""
    return cleaned
