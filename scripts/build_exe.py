# -*- coding: utf-8 -*-
"""一键打包 NSAT Studio 为 Windows exe（PyInstaller onefile, 窗口模式）."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_SRC = os.path.join(ROOT, "nsat", "ui", "static")
STATIC_DST = os.path.join("nsat", "ui", "static")
ICON = os.path.join(ROOT, "icon.ico")
ENTRY = os.path.join(ROOT, "nsat_desktop.py")

ARGS = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",                          # 目录模式：更新只需替换文件，插件也放这里
    "--windowed",                        # 无控制台窗口
    "--name", "NSAT-Studio",
    "--icon", ICON,
    "--add-data", f"{STATIC_SRC}{os.pathsep}{STATIC_DST}",
    "--add-data", f"{ICON}{os.pathsep}.",
    # webview / pythonnet 相关收集
    "--collect-all", "webview",
    "--collect-all", "bottle",
    "--hidden-import", "clr_loader",
    "--hidden-import", "pythonnet",
    "--hidden-import", "requests",
    ENTRY,
]

print("打包命令：")
print(" ".join(ARGS))
print()
rc = subprocess.call(ARGS, cwd=ROOT)
if rc == 0:
    out = os.path.join(ROOT, "dist", "NSAT-Studio", "NSAT-Studio.exe")
    print()
    print("打包完成：", out)
    print("提示：插件放到 exe 旁的 plugins/ 目录即可扩展 AI 工具/语言。")
else:
    print("打包失败，exit =", rc)
    sys.exit(rc)
