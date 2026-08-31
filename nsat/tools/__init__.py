# -*- coding: utf-8 -*-
"""工具注册表、调度器与工具循环."""

from __future__ import annotations

import json
from typing import Any, Callable

from ..ai.base import AIProvider, make_assistant_message
from ..errors import AIError
from ..permissions import (
    OP_DELETE,
    OP_EDIT,
    OP_READ,
    OP_RUN,
    OP_WRITE,
    PermissionManager,
)
from . import file_tools as ft
from .file_tools import ToolContext

# OpenAI 风格工具 schema
_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取项目内某个文本文件的内容（用于查看已有 NSAT 文件、配置文件等）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对项目根的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录下的条目，了解项目结构",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径（默认项目根）"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建新文件或整体覆盖已有文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确修改已有文件：replacements 是 [{old, new}] 列表，old 必须在文件中恰好出现一次",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "replacements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                            "required": ["old", "new"],
                        },
                    },
                },
                "required": ["path", "replacements"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除一个文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在项目目录执行 shell 命令（默认关闭，需要用户在配置中开启）",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["cmd"],
            },
        },
    },
]

# 工具名 → (权限操作, 实现函数)
_TOOL_IMPL: dict[str, tuple[str, Callable]] = {
    "read_file": (OP_READ, ft.read_file),
    "list_dir": (OP_READ, ft.list_dir),
    "write_file": (OP_WRITE, ft.write_file),
    "edit_file": (OP_EDIT, ft.edit_file),
    "delete_file": (OP_DELETE, ft.delete_file),
    "run_command": (OP_RUN, ft.run_command),
}


def tool_schemas(include_run: bool = False) -> list[dict[str, Any]]:
    schemas = [t for t in _TOOL_SCHEMAS]
    if not include_run:
        schemas = [t for t in schemas if t["function"]["name"] != "run_command"]
    return schemas


def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    impl: Callable,
    operation: str,
) -> None:
    """插件注册自定义工具."""
    _TOOL_SCHEMAS.append(
        {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
    )
    _TOOL_IMPL[name] = (operation, impl)


def execute_tool(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
    permission: PermissionManager,
) -> str:
    if name not in _TOOL_IMPL:
        return f"错误：未知工具 {name}"
    op, fn = _TOOL_IMPL[name]
    path = args.get("path", "")
    if not permission.check(op, ctx.resolve(path)):
        return f"操作被拒绝：{op} {path}（用户不同意或命中敏感路径）"
    try:
        return fn(ctx, **args)
    except TypeError as e:
        return f"错误：工具参数不合法 {e}"
    except Exception as e:  # noqa: BLE001 - 工具返回给 AI 的错误信息
        return f"错误：工具执行异常 {e}"


def run_tool_loop(
    provider: AIProvider,
    messages: list[dict[str, Any]],
    ctx: ToolContext,
    permission: PermissionManager,
    *,
    max_rounds: int = 10,
) -> dict[str, Any]:
    """执行带工具的对话循环，返回最终（无工具调用）的回复 dict."""
    include_run = ctx.allow_run_command
    final: dict[str, Any] = {}
    for _ in range(max_rounds):
        reply = provider.chat(messages, tools=tool_schemas(include_run=include_run))
        messages.append(make_assistant_message(reply.get("content", ""), reply.get("tool_calls")))
        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            final = reply
            break
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(name, args, ctx, permission)
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})
    else:
        raise AIError(f"工具调用超过 {max_rounds} 轮仍未结束")
    return final