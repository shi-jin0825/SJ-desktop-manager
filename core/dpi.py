# -*- coding: utf-8 -*-
"""高 DPI 屏幕适配。

不主动声明的话，Windows 会把程序当成「不认识 DPI 的老程序」整体拉伸，
界面（尤其是我们这种自绘的图标和渐变按钮）就会发虚。这里在**创建任何
窗口之前**声明 Per-Monitor V2，让 Tk 按真实像素渲染。

全部走 ctypes，失败也无所谓（老系统没这些 API 就退回系统默认行为）。
"""
import ctypes
import os
import sys

_DONE = False


def enable_dpi_awareness() -> str:
    """声明 DPI 感知，返回实际用上的方式（仅用于排查问题）。"""
    global _DONE
    if _DONE:
        return "already"
    _DONE = True
    if sys.platform != "win32":
        return "non-windows"
    try:
        # Win10 1703+：Per-Monitor V2（拖到不同缩放的显示器也不糊）
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)
        return "per-monitor-v2"
    except (AttributeError, OSError, WindowsError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
        return "per-monitor"
    except (AttributeError, OSError, WindowsError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError, WindowsError):
        return "unavailable"


def scale_factor() -> float:
    """当前主显示器的缩放比例（1.0 / 1.25 / 1.5 ...）—— 排查显示问题时用。"""
    if sys.platform != "win32":
        return 1.0
    try:
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, dc)
        return dpi / 96.0
    except (AttributeError, OSError, WindowsError):
        return 1.0
