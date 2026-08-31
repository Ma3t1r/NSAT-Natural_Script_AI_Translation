# -*- coding: utf-8 -*-
"""NSAT 日志：软件根目录 log/ 下按天记录，超 30 天自动清理."""

from __future__ import annotations

import logging
import os
import sys
import time


def log_dir() -> str:
    """日志目录：打包后为 exe 旁 log/，开发时为项目根 log/."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "log")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _cleanup_old(directory: str, days: int = 30) -> None:
    cutoff = time.time() - days * 86400
    try:
        for fn in os.listdir(directory):
            if not fn.endswith(".log"):
                continue
            p = os.path.join(directory, fn)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                continue
    except OSError:
        pass


def setup_logging() -> str:
    """初始化日志：返回日志文件路径。重复调用只加一次 handler."""
    d = log_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return ""
    path = os.path.join(d, f"{_today()}.log")
    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == path
               for h in root.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    _cleanup_old(d)
    return path


def log_app(msg: str) -> None:
    logging.getLogger("nsat").info(msg)