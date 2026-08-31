# -*- coding: utf-8 -*-
"""AI 工具实现：文件读写、目录列举、编辑、删除、命令."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

MAX_READ_BYTES = 256 * 1024  # 单文件读取上限 256KB


@dataclass
class ToolContext:
    root: str                              # 项目根目录
    permission: Any = None                 # PermissionManager
    allow_run_command: bool = False
    state: dict[str, Any] = field(default_factory=dict)

    def resolve(self, path: str) -> str:
        p = path.strip() if isinstance(path, str) else ""
        if not p:
            return self.root
        if os.path.isabs(p):
            return p
        return os.path.join(self.root, p)


# ---------------------------------------------------------------- 实现

def read_file(ctx: ToolContext, path: str) -> str:
    full = ctx.resolve(path)
    if not os.path.isfile(full):
        return f"错误：文件不存在 {full}"
    try:
        size = os.path.getsize(full)
        if size > MAX_READ_BYTES:
            return f"错误：文件过大（{size} 字节），超过 {MAX_READ_BYTES} 字节上限"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        return f"错误：读取失败 {e}"


def list_dir(ctx: ToolContext, path: str = "") -> str:
    full = ctx.resolve(path)
    if not os.path.isdir(full):
        return f"错误：目录不存在 {full}"
    try:
        entries = sorted(os.listdir(full))
    except OSError as e:
        return f"错误：列目录失败 {e}"
    lines = [f"{p}{os.sep}" if os.path.isdir(os.path.join(full, p)) else p for p in entries]
    return "\n".join(lines) if lines else "（空目录）"


def write_file(ctx: ToolContext, path: str, content: str = "") -> str:
    full = ctx.resolve(path)
    existed = os.path.exists(full)
    parent = os.path.dirname(full) or "."
    try:
        os.makedirs(parent, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return f"错误：写入失败 {e}"
    return f"已{'覆盖' if existed else '创建'}文件 {full}（{len(content)} 字符）"


def edit_file(ctx: ToolContext, path: str, replacements: list[dict[str, str]] | None = None) -> str:
    full = ctx.resolve(path)
    if not os.path.isfile(full):
        return f"错误：文件不存在 {full}"
    try:
        with open(full, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return f"错误：读取失败 {e}"
    if not replacements:
        return "错误：edit_file 需要非空 replacements"
    applied = 0
    for rep in replacements:
        old = rep.get("old")
        new = rep.get("new", "")
        if not old:
            continue
        if text.count(old) != 1:
            return f"错误：文本 {old[:40]!r} 匹配 {text.count(old)} 次（需恰好 1 次），未修改文件"
        text = text.replace(old, new)
        applied += 1
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        return f"错误：写入失败 {e}"
    return f"已修改文件 {full}（应用 {applied} 处替换）"


def delete_file(ctx: ToolContext, path: str) -> str:
    full = ctx.resolve(path)
    if not os.path.isfile(full):
        return f"错误：文件不存在 {full}"
    try:
        os.remove(full)
    except OSError as e:
        return f"错误：删除失败 {e}"
    return f"已删除文件 {full}"


def run_command(ctx: ToolContext, cmd: str, cwd: str | None = None) -> str:
    if not ctx.allow_run_command:
        return "错误：run_command 未启用（在配置 permissions.allow_run_command 中开启）"
    full_cwd = ctx.resolve(cwd) if cwd else ctx.root
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=full_cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "错误：命令执行超时（30s）"
    except OSError as e:
        return f"错误：命令执行失败 {e}"
    out = proc.stdout or ""
    err = proc.stderr or ""
    return f"退出码: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"