# -*- coding: utf-8 -*-
"""权限管理器：对 AI 的文件操作按 vibe-code 规范询问用户."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

# 敏感路径命中即强制拒绝（无论权限配置如何）
SENSITIVE_PATTERNS: list[str] = [
    r"[\\/]\.git[\\/]",
    r"[\\/]\.ssh[\\/]",
    r"[\\/]\.aws[\\/]",
    r"nsatconfig\.json$",
    r"\.env$",
    r"\.pem$",
    r"\.key$",
    r"id_rsa$",
    r"id_ed25519$",
]


def is_sensitive(path: str) -> bool:
    norm = path.replace("/", os.sep).replace("\\", os.sep)
    return any(re.search(p, norm, re.IGNORECASE) for p in SENSITIVE_PATTERNS)


@dataclass
class PermissionDecision:
    allowed: bool
    remember: bool = False


class PermissionManager:
    """mode: ask | allow_all | deny_all.

    ask_fn(operation, path) -> PermissionDecision，由 CLI/GUI 各自实现。
    """

    def __init__(self, mode: str = "ask", ask_fn: Callable[[str, str], PermissionDecision] | None = None):
        self.mode = mode
        self.ask_fn = ask_fn or _deny_default
        self._remember: dict[tuple[str, str], bool] = {}

    def check(self, operation: str, path: str) -> bool:
        if is_sensitive(path):
            return False
        if self.mode == "allow_all":
            return True
        if self.mode == "deny_all":
            return False
        key = (operation, os.path.normpath(path))
        if key in self._remember:
            return self._remember[key]
        decision = self.ask_fn(operation, path)
        if decision.remember:
            self._remember[key] = decision.allowed
        return decision.allowed


def _deny_default(operation: str, path: str) -> PermissionDecision:
    return PermissionDecision(allowed=False)

# 操作分类名（工具 → 权限操作）
OP_READ = "read"       # read_file / list_dir
OP_WRITE = "write"     # write_file（新建/覆盖）
OP_EDIT = "edit"       # edit_file（修改）
OP_DELETE = "delete"   # delete_file
OP_RUN = "run"         # run_command