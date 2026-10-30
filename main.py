# -*- coding: utf-8 -*-
"""墨墨桌面管理助手（SJ-desktop-manager）—— 启动入口。

运行方式：python main.py
依赖：仅使用 Python 标准库（tkinter），无需 pip install。
"""
import sys
import os

# 保证以任意工作目录启动时都能找到 core/gui 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
