# -*- coding: utf-8 -*-
"""NSAT 桌面 UI 启动入口（PyWebview，回退到浏览器）."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from urllib.parse import quote

from .server import become_primary, start_server


def _project_icon() -> str | None:
    """项目根下的 icon.ico（Windows 窗口图标 / 文件关联图标）."""
    if getattr(sys, "frozen", False):  # PyInstaller
        cand = os.path.join(sys._MEIPASS, "icon.ico")
        if os.path.isfile(cand):
            return cand
        return None
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for cand in (here, os.getcwd()):
        p = os.path.join(cand, "icon.ico")
        if os.path.isfile(p):
            return p
    return None


def _set_window_icon(hwnd: int, icon_path: str) -> None:
    """用 Win32 把窗口图标设为 icon.ico."""
    if not icon_path or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        # IMAGE_ICON=1, LR_LOADFROMFILE=0x10
        hicon = user32.LoadImageW(None, icon_path, 1, 0, 0, 0x10)
        if hicon:
            user32.SendMessageW(ctypes.c_void_p(hwnd), 0x0080, 1, hicon)  # WM_SETICON BIG
            user32.SendMessageW(ctypes.c_void_p(hwnd), 0x0080, 0, hicon)  # WM_SETICON SMALL
    except Exception:  # noqa: BLE001 - 图标失败不影响运行
        pass


class _NativeDialogApi:
    """暴露给前端 JS 调用的原生系统文件/文件夹对话框.

    window.pywebview.api.pick_folder() / pick_file()
    返回选中的路径字符串，取消返回 None。
    """

    def pick_folder(self):
        import webview

        try:
            result = webview.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:  # noqa: BLE001
            return None
        return result[0] if result else None

    def pick_file(self):
        import webview

        try:
            result = webview.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("NSAT 文件 (*.nsat)", "所有文件 (*.*)"),
            )
        except Exception:  # noqa: BLE001
            return None
        return result[0] if result else None


def launch(
    project_root: str | None = None,
    host: str = "127.0.0.1",
    browser_only: bool = False,
    open_file: str | None = None,
) -> None:
    # 单实例：已运行则把打开请求发给现有窗口后退出
    if not become_primary(open_file):
        print("NSAT Studio 已在运行，已发送打开请求。")
        return

    server, url = start_server(host, 0)
    params = []
    if project_root:
        params.append("root=" + quote(project_root))
    if open_file:
        params.append("file=" + quote(open_file))
    if params:
        url += "?" + "&".join(params)

    icon = _project_icon()

    if browser_only:
        import webbrowser

        webbrowser.open(url)
        print(f"NSAT Studio 已在浏览器打开: {url}")
        print("按 Ctrl+C 退出。")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview  # type: ignore
    except ImportError:
        import webbrowser

        webbrowser.open(url)
        print(f"未安装 pywebview，已在浏览器打开: {url}")
        print("安装：pip install pywebview，即可使用桌面窗口。")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        return

    window = webview.create_window(
        "NSAT Studio",
        url,
        width=1360,
        height=860,
        min_size=(900, 600),
        background_color="#1e1e1e",
    )

    def _on_ready():
        try:
            native = getattr(window, "native", None)
            handle = getattr(native, "Handle", None)
            if handle is not None:
                _set_window_icon(int(handle.ToInt64()), icon or "")
        except Exception:  # noqa: BLE001
            pass

    webview.start(func=_on_ready)


if __name__ == "__main__":
    launch()