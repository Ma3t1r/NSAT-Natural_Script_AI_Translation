# -*- coding: utf-8 -*-
"""nsatconfig.json 读写与校验."""

from __future__ import annotations

import json
import os
from typing import Any

from .errors import ConfigError

DEFAULT_CONFIG: dict[str, Any] = {
    "ai": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "",
        "base_url": "",
        "temperature": 0.2,
        "max_tokens": 8192,
        "timeout": 180,
    },
    "logic_errors": {"mode": "ask"},
    "permissions": {
        "mode": "ask",
        "enable_tools": True,
        "allow_run_command": False,
    },
    "context": {
        "history_rounds": 4,
        "follow_refs_depth": 3,
    },
    "targets": {
        "python": {"run": ["python"], "build": ["python", "-m", "py_compile"]},
        "go": {"run": ["go", "run"], "build": ["go", "build"]},
        "rust": {"run": ["cargo", "run"], "build": ["cargo", "build"]},
    },
    "output": {"dir": "out"},
}

# provider -> 默认 base_url（OpenAI 兼容接口）
PROVIDER_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "custom": "",
}

CONFIG_NAME = "nsatconfig.json"


def user_config_path() -> str:
    """用户级全局设置文件（API Key 等）。Windows: %APPDATA%/nsat/settings.json."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "nsat", "settings.json")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict[str, Any]:
    """加载配置：默认值 < 用户级设置 < 项目 nsatconfig.json."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
    # 用户级全局设置
    up = user_config_path()
    if os.path.exists(up):
        try:
            with open(up, "r", encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    # 项目配置
    path = path or CONFIG_NAME
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} 不是合法 JSON: {e}")
    return cfg


def save_config(cfg: dict[str, Any], path: str | None = None) -> str:
    path = path or CONFIG_NAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def save_user_config(cfg: dict[str, Any]) -> str:
    """保存到用户级设置文件（独立于项目）."""
    path = user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def resolve_api_key(cfg: dict[str, Any]) -> str:
    """优先环境变量 NSAT_API_KEY，其次配置文件."""
    key = os.environ.get("NSAT_API_KEY", "").strip()
    if key:
        return key
    return (cfg.get("ai", {}).get("api_key") or "").strip()


def resolve_base_url(cfg: dict[str, Any]) -> str:
    ai = cfg.get("ai", {})
    return (ai.get("base_url") or "").strip() or PROVIDER_DEFAULTS.get(ai.get("provider", "deepseek"), "")


def check_provider(cfg: dict[str, Any]) -> None:
    provider = cfg.get("ai", {}).get("provider", "")
    if provider not in ("deepseek", "openai", "anthropic", "custom"):
        raise ConfigError(f"未知 provider: {provider!r}（可选 deepseek/openai/anthropic/custom）")
    if provider == "custom" and not (cfg.get("ai", {}).get("base_url") or "").strip():
        raise ConfigError("provider 为 custom 时必须设置 base_url")
    if not resolve_api_key(cfg):
        raise ConfigError("缺少 API Key：请设置环境变量 NSAT_API_KEY，或在 nsatconfig.json 的 ai.api_key 中填写")