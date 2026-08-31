# -*- coding: utf-8 -*-
"""NSAT 实验版 - 错误与警告类型."""

from __future__ import annotations


class NSATError(Exception):
    """编译/校验错误基类."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:  # pragma: no cover - 纯展示
        if self.line is not None:
            return f"第 {self.line} 行: {self.message}"
        return self.message


class ParseError(NSATError):
    """本地语法校验错误."""


class ConfigError(NSATError):
    """配置错误."""


class AIError(NSATError):
    """AI 调用错误."""


class ProtocolError(NSATError):
    """AI 返回信封解析错误."""


class RunnerError(NSATError):
    """目标语言运行/编译错误."""


class PermissionDenied(NSATError):
    """用户拒绝或敏感路径拦截."""