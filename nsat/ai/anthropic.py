# -*- coding: utf-8 -*-
"""Anthropic Claude（messages API + native tools）."""

from __future__ import annotations

import json
from typing import Any

import requests

from ..errors import AIError
from .base import AIProvider, sanitize_for_api

ANTHROPIC_VERSION = "2023-06-01"


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把统一消息结构转换为 Anthropic messages 结构.

    统一结构：system / user(content) / assistant(content+tool_calls) / tool(tool_call_id, content)
    Anthropic 结构：user(content blocks) / assistant(content blocks) / user(tool_result block)
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments") or "{}"
                try:
                    args_obj = json.loads(args)
                except json.JSONDecodeError:
                    args_obj = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args_obj,
                    }
                )
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": m.get("content", ""),
                        }
                    ],
                }
            )
    return out


def _extract_system(messages: list[dict[str, Any]]) -> str:
    parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    return "\n\n".join(parts)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, config: dict[str, Any], api_key: str, base_url: str = "https://api.anthropic.com/v1"):
        super().__init__(config, api_key)
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "system": _extract_system(messages) or None,
            "messages": _to_anthropic_messages(sanitize_for_api(messages)),
        }
        if tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/messages", json=payload, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise AIError(f"AI 请求失败: {e}")
        if resp.status_code != 200:
            raise AIError(f"AI 接口返回 {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
            blocks = data.get("content", [])
        except ValueError as e:
            raise AIError(f"AI 响应结构异常: {e}")

        text_parts = []
        tool_calls = []
        for b in blocks:
            if b.get("type") == "text":
                text_parts.append(b.get("text", ""))
            elif b.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": b.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": b.get("name", ""),
                            "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                        },
                    }
                )
        return {"content": "".join(text_parts), "tool_calls": tool_calls}