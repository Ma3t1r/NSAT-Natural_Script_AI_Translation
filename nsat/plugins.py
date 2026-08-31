# -*- coding: utf-8 -*-
"""插件系统：从 plugins/ 目录加载 .py 插件.

插件可注册：
- 新的 AI 工具（文件操作类）
- 新的目标语言

插件示例（放在 plugins/my_tool.py）：
    def register(ctx):
        ctx.register_language("lua", ["lua"], "lua")

    def register_tool(ctx):
        ctx.register_tool(
            "read_json",
            "读取并解析 JSON 文件",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            impl=my_impl,
            operation="read",
        )
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Callable

from .errors import NSATError


def plugin_dirs() -> list[str]:
    """插件目录：exe/工程旁的 plugins/ 与用户数据目录."""
    dirs: list[str] = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(os.path.dirname(sys.executable), "plugins"))
    else:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dirs.append(os.path.join(here, "plugins"))
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    dirs.append(os.path.join(base, "nsat", "plugins"))
    return dirs


def _load_module(path: str):
    name = "nsat_plugin_" + os.path.splitext(os.path.basename(path))[0]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001
        print(f"[插件] 加载失败 {os.path.basename(path)}: {e}")
        return None


class PluginContext:
    """插件能用的能力入口."""

    def register_language(self, name: str, aliases: list[str], ext: str) -> None:
        from . import langs

        langs.register_language(name, aliases, ext)

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        impl: Callable,
        operation: str,
    ) -> None:
        from . import tools

        tools.register_tool(name, description, parameters, impl, operation)


def load_plugins() -> list[str]:
    """加载全部插件，返回成功加载的文件名列表."""
    loaded: list[str] = []
    for d in plugin_dirs():
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(d, fn)
            mod = _load_module(path)
            if mod is None:
                continue
            try:
                ctx = PluginContext()
                register = getattr(mod, "register", None)
                if callable(register):
                    register(ctx)
                    loaded.append(fn)
            except Exception as e:  # noqa: BLE001
                print(f"[插件] {fn} 执行 register 失败: {e}")
    if loaded:
        print(f"[插件] 已加载: {', '.join(loaded)}")
    return loaded