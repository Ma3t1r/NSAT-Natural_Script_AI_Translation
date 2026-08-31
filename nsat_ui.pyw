# -*- coding: utf-8 -*-
"""NSAT 桌面启动器（供 .nsat 文件关联双击调用，pythonw 运行无控制台）."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nsat.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
