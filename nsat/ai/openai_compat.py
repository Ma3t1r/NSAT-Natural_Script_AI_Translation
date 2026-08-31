# -*- coding: utf-8 -*-
"""OpenAI 兼容接口（含 DeepSeek、自定义 base_url）."""

from __future__ import annotations

from typing import Any

import requests

from ..errors import AIError
from .base import AIProvider, sanitize_for_api


class OpenAICompatProvider(AIProvider):
    name = "openai_compat"

    def __init__(self, config: dict[str, Any], api_key: str, base_url: str):
        super().__init__(config, api_key)
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )

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
            "messages": sanitize_for_api(messages),
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/chat/completions"
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise AIError(f"AI 请求失败: {e}")
        if resp.status_code != 200:
            raise AIError(f"AI 接口返回 {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as e:
            raise AIError(f"AI 响应结构异常: {e}")

        content = msg.get("content") or ""
        if not content.strip():
            reasoning = msg.get("reasoning_content") or ""
            finish = data.get("choices", [{}])[0].get("finish_reason")
            if reasoning:
                hint = "AI 返回空内容：推理模型消耗了过多 token"
                if finish == "length":
                    hint += "（输出被 max_tokens 截断）"
                hint += "。建议在「设置」把模型改为 deepseek-chat，或增大 max_tokens。"
                raise AIError(hint)
            raise AIError("AI 返回了空内容，请重试（或检查 API Key/模型是否有效）")

        tcs = msg.get("tool_calls") or []
        tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"].get("arguments", ""),
                },
            }
            for tc in tcs
            if tc.get("function")
        ]
        return {"content": content, "tool_calls": tool_calls}