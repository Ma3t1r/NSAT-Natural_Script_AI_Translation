# -*- coding: utf-8 -*-
"""Provider 抽象基类 + 统一返回结构."""

from __future__ import annotations

from typing import Any

from ..errors import AIError

# 孤立代理字符（U+D800-DBFF / U+DC00-DFFF）不能通过 JSON 传输，替换掉


def _sanitize_text(s: str) -> str:
    try:
        s.encode("utf-8", "strict")
        return s
    except UnicodeEncodeError:
        return "".join(ch if not (0xD800 <= ord(ch) <= 0xDFFF) else "\ufffd" for ch in s)


def sanitize_for_api(obj: Any) -> Any:
    """递归清洗字符串里的孤立代理字符，确保可安全 JSON 序列化."""
    if isinstance(obj, str):
        return _sanitize_text(obj)
    if isinstance(obj, dict):
        return {k: sanitize_for_api(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_api(v) for v in obj]
    return obj


class AIProvider:
    """所有 AI 提供商统一接口.

    chat() 返回归一化结构：
    {"content": str, "tool_calls": [{"id", "type", "function": {"name", "arguments"}}]}
    """

    name = "base"

    def __init__(self, config: dict[str, Any], api_key: str):
        self.config = config
        self.api_key = api_key
        self.model = (config.get("model") or "").strip()
        self.temperature = float(config.get("temperature") or 0.2)
        self.max_tokens = int(config.get("max_tokens") or 8192)
        self.timeout = int(config.get("timeout") or 180)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def complete_text(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        reply = self.chat(messages, tools=tools)
        return reply.get("content", "")


def make_assistant_message(content: str, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把归一化回复 dict 转成可回填进 messages 的 assistant 消息."""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg