# -*- coding: utf-8 -*-
"""Windows .nsat 文件关联注册（CLI 与 UI 共用）."""

from __future__ import annotations

import os
import sys


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def register_assoc() -> tuple[bool, str]:
    """注册 .nsat → NSAT-Studio.exe（或 pythonw 启动器）到 HKCU.

    返回 (是否成功, 说明)。
    """
    import ctypes
    import winreg

    project_dir = _project_dir()
    launcher = os.path.join(project_dir, "nsat_ui.pyw")
    icon = os.path.join(project_dir, "icon.ico")
    if not os.path.isfile(launcher) and not os.path.isfile(icon):
        return False, "找不到启动器或图标"

    exe = sys.executable
    base = os.path.dirname(exe)
    pyw = os.path.join(base, "pythonw.exe") if os.path.basename(exe).lower() == "python.exe" else exe
    if not os.path.isfile(pyw):
        pyw = exe

    # 优先独立 exe（onedir: dist/NSAT-Studio/NSAT-Studio.exe）
    exe_app = os.path.join(project_dir, "dist", "NSAT-Studio", "NSAT-Studio.exe")
    if not os.path.isfile(exe_app):
        exe_app = os.path.join(project_dir, "dist", "NSAT-Studio.exe")
    if os.path.isfile(exe_app):
        cmd = f'"{exe_app}" "%1"'
        used = "独立 exe"
    else:
        cmd = f'"{pyw}" "{launcher}" open "%1"'
        used = "pythonw 启动器"

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.nsat") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, "NSAT.File")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\NSAT.File") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, "NSAT 源文件")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\NSAT.File\DefaultIcon") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, f'"{icon}"')
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\NSAT.File\shell\open\command"
        ) as k:
            winreg.SetValue(k, "", winreg.REG_SZ, cmd)
    except Exception as e:  # noqa: BLE001
        return False, f"注册失败: {e}"

    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:  # noqa: BLE001
        pass
    return True, f"已注册（{used}）: {cmd}"