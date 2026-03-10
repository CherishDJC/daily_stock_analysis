# -*- coding: utf-8 -*-
"""Helpers for OpenAI-compatible protocol variants.

Supports both legacy ``chat.completions`` style gateways and
OpenAI ``responses`` style gateways.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional


def normalize_openai_api_style(style: Optional[str]) -> str:
    """Normalize user-facing API style aliases to internal constants."""
    value = (style or "").strip().lower().replace("-", "_")
    if value in {"responses", "openai_responses", "openai_response"}:
        return "responses"
    return "chat_completions"


def build_responses_tools(openai_tools: List[dict]) -> List[dict]:
    """Convert chat.completions tool schema to responses tool schema."""
    tools: List[dict] = []
    for tool in openai_tools or []:
        if tool.get("type") != "function":
            continue
        fn = tool.get("function", {})
        tools.append(
            {
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description"),
                "parameters": fn.get("parameters"),
                "strict": False,
            }
        )
    return tools


def build_responses_input(messages: List[Dict[str, Any]]) -> List[dict]:
    """Convert provider-neutral messages into Responses API input items."""
    items: List[dict] = []

    for index, msg in enumerate(messages):
        role = msg.get("role")

        if role in {"system", "developer", "user"}:
            content = msg.get("content", "")
            items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": [{"type": "input_text", "text": str(content)}],
                }
            )
            continue

        if role == "assistant":
            content = msg.get("content")
            if content:
                items.append(
                    {
                        "id": msg.get("message_id") or f"msg_{index}_{uuid.uuid4().hex[:8]}",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": str(content),
                                "annotations": [],
                            }
                        ],
                    }
                )

            for tool_call in msg.get("tool_calls") or []:
                call_id = (
                    tool_call.get("call_id")
                    or tool_call.get("id")
                    or f"call_{uuid.uuid4().hex[:8]}"
                )
                item = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": tool_call["name"],
                    "arguments": json.dumps(tool_call.get("arguments", {}), ensure_ascii=False),
                    "status": "completed",
                }
                if tool_call.get("id"):
                    item["id"] = tool_call["id"]
                items.append(item)
            continue

        if role == "tool":
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id") or msg.get("call_id") or "",
                    "output": content,
                }
            )

    return items


def extract_text_from_responses(response: Any) -> str:
    """Extract plain text from a Responses API result."""
    texts: List[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", None) == "output_text" and getattr(part, "text", None):
                texts.append(part.text)
    return "".join(texts).strip()


def extract_tool_calls_from_responses(response: Any) -> List[dict]:
    """Extract function tool calls from a Responses API result."""
    tool_calls: List[dict] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "function_call":
            continue
        raw_arguments = getattr(item, "arguments", "") or ""
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            arguments = {"raw": raw_arguments}
        tool_calls.append(
            {
                "id": getattr(item, "id", None) or getattr(item, "call_id", None) or uuid.uuid4().hex[:8],
                "call_id": getattr(item, "call_id", None) or getattr(item, "id", None),
                "name": getattr(item, "name", ""),
                "arguments": arguments,
            }
        )
    return tool_calls


def extract_usage_from_responses(response: Any) -> Dict[str, int]:
    """Normalize usage fields from a Responses API result."""
    usage = getattr(response, "usage", None)
    if not usage:
        return {}

    prompt_tokens = getattr(usage, "input_tokens", 0) or 0
    completion_tokens = getattr(usage, "output_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
