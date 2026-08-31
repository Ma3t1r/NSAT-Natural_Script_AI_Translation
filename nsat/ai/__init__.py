# -*- coding: utf-8 -*-
"""AI Provider 工厂."""

from __future__ import annotations

from typing import Any

from .. import config as _config
from ..errors import ConfigError
from .base import AIProvider
from .anthropic import AnthropicProvider
from .openai_compat import OpenAICompatProvider


def create_provider(cfg: dict[str, Any]) -> AIProvider:
    """按配置创建 provider 实例."""
    ai = cfg.get("ai", {})
    provider_name = ai.get("provider", "deepseek")
    api_key = _config.resolve_api_key(cfg)
    if not api_key:
        raise ConfigError("缺少 API Key：请设置环境变量 NSAT_API_KEY，或在 nsatconfig.json 的 ai.api_key 中填写")

    if provider_name == "anthropic":
        return AnthropicProvider(ai, api_key)
    if provider_name in ("deepseek", "openai", "custom"):
        base_url = _config.resolve_base_url(cfg)
        if not base_url:
            raise ConfigError(f"provider {provider_name!r} 需要有效的 base_url")
        return OpenAICompatProvider(ai, api_key, base_url)
    raise ConfigError(f"未知 provider: {provider_name!r}")