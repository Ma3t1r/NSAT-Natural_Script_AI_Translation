# -*- coding: utf-8 -*-
"""NSAT Studio 桌面应用入口（PyInstaller 打包用）.

用法：双击运行；或传一个文件夹 / .nsat 文件作为默认打开项。
"""
import os
import sys


def main() -> None:
    project = None
    open_file = None
    for a in sys.argv[1:]:
        if a.startswith("-"):
            continue
        p = os.path.abspath(a)
        if os.path.isfile(p):
            open_file = p
            project = os.path.dirname(p)
        elif os.path.isdir(p):
            project = p
        else:
            print(f"忽略无效路径: {a}")
    from nsat.ui.app import launch

    launch(project_root=project, open_file=open_file)


if __name__ == "__main__":
    main()
