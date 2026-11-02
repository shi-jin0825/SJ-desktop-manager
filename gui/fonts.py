# -*- coding: utf-8 -*-
"""字体：统一常量 + 缺失回退。

以前 "Microsoft YaHei" 在四个文件里硬编码了 95 次。两个问题：
  1. 想换字体要改 95 处；
  2. 微软雅黑并非到处都有 —— 精简版 Windows、非中文系统、部分 Windows
     Server 上都没有，Tk 会静默回落到某个默认字体，中文可能变成方块。
这里集中解析一次：在系统已安装字体里按优先级挑第一个存在的，之后所有
界面只调 font(size, ...)。
"""
import tkinter as tk
from tkinter import font as tkfont

# 按优先级排列：优先带 UI 的版本（行距更适合小字号界面），再退到能显示
# 中文的常见字体，最后是 Tk 能拿到的任何无衬线字体。
CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "SimHei",
)

# 一个字体都探测不到时的兜底（Tk 内置，永远存在）
FALLBACK = "TkDefaultFont"

_family = None


def _detect():
    """在系统字体表里找第一个可用的候选；还没有 Tk 根窗口时返回 None。"""
    try:
        root = tk._default_root
        if root is None:
            return None
        available = set(tkfont.families(root))
    except Exception:
        return None
    for name in CANDIDATES:
        if name in available:
            return name
    return FALLBACK


def family() -> str:
    """当前使用的字体名（首次调用时解析一次并缓存）。"""
    global _family
    if _family is None:
        # 根窗口还没建好时不缓存，下次再试一次，免得永远卡在兜底字体上
        _family = _detect()
    return _family or FALLBACK


def font(size: int = 10, *styles):
    """生成 tkinter 的 font 元组，如 font(11, "bold")。"""
    return (family(), int(size)) + tuple(styles)


def reset_cache():
    """测试 / 换主题时用：清掉缓存，下次重新探测。"""
    global _family
    _family = None
