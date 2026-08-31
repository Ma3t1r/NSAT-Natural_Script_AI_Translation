# -*- coding: utf-8 -*-
"""目标语言运行/编译器调用."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from .errors import RunnerError


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        lines = [f"退出码: {self.exit_code}", f"耗时: {self.duration:.2f}s"]
        if self.stdout:
            lines.append("--- stdout ---")
            lines.append(self.stdout.rstrip())
        if self.stderr:
            lines.append("--- stderr ---")
            lines.append(self.stderr.rstrip())
        return "\n".join(lines)


def _resolve_command(cmd: list[str]) -> list[str]:
    """把目标配置里的命令解析为可执行命令（Python 特判为当前解释器）."""
    if cmd and cmd[0] == "python":
        return [sys.executable] + cmd[1:]
    return cmd


def _command_exists(cmd: list[str]) -> bool:
    if not cmd:
        return False
    exe = cmd[0]
    if exe == "python":
        return True
    return shutil.which(exe) is not None


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(cmd: list[str], *, cwd: str | None, timeout: int) -> RunResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(exit_code=-1, stdout="", stderr=f"运行超时（>{timeout}s）", duration=0.0)
    except OSError as e:
        raise RunnerError(f"运行失败: {e}")
    duration = time.monotonic() - start
    return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "", duration)


def run_target(
    language: str,
    cfg: dict[str, Any],
    filepath: str,
    *,
    cwd: str | None = None,
    timeout: int = 60,
) -> RunResult:
    """临时测试：运行目标代码文件."""
    targets = cfg.get("targets", {})
    entry = targets.get(language)
    if not entry or not entry.get("run"):
        raise RunnerError(f"目标语言 {language!r} 没有配置 run 命令（targets.{language}.run）")
    cmd = _resolve_command(entry["run"])
    if not _command_exists(cmd):
        raise RunnerError(f"找不到命令 {cmd[0]}，请安装或修改 targets.{language}.run 配置")
    return _run(cmd + [filepath], cwd=cwd, timeout=timeout)


def compile_target(
    language: str,
    cfg: dict[str, Any],
    filepath: str,
    *,
    cwd: str | None = None,
    timeout: int = 120,
) -> RunResult:
    """最终编译：调用目标语言编译器."""
    targets = cfg.get("targets", {})
    entry = targets.get(language)
    if not entry or not entry.get("build"):
        raise RunnerError(f"目标语言 {language!r} 没有配置 build 命令（targets.{language}.build）")
    cmd = _resolve_command(entry["build"])
    if not _command_exists(cmd):
        raise RunnerError(f"找不到命令 {cmd[0]}，请安装或修改 targets.{language}.build 配置")
    return _run(cmd + [filepath], cwd=cwd, timeout=timeout)