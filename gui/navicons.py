# -*- coding: utf-8 -*-
"""统一风格的线性图标（纯 Canvas 绘制，无任何图片资源 / 第三方依赖）。

为什么不用现成的 SVG 图标包：本项目坚持「零第三方依赖 + 纯标准库」，
Python 标准库无法解析渲染 SVG，外链下载又会让离线环境失效。所以这里
用一套**自制矢量图标**：全部在 24×24 网格上作图、统一线宽（1.7）、
统一圆头圆角，风格与常见 Iconfont 线性图标一致（描边式而非实心），
颜色直接跟随主题（浅色/深色自动适配，选中态用强调色）。

用法：
    cv = tk.Canvas(parent, width=20, height=20, bg=bg, highlightthickness=0)
    draw_icon(cv, "home", 20, "#5a6478")
"""
import math

import tkinter as tk

# 24×24 设计网格
G = 24.0
# 绘制偏移（供 draw_icon 的 ox / oy 使用，单线程下安全）
_OX = _OY = 0.0


def _scale(pts, s):
    out = []
    for x, y in pts:
        out += (x * s + _OX, y * s + _OY)
    return out


def _line(cv, pts, s, color, w, smooth=False):
    """折线（圆头圆角，线性图标的基本笔触）。"""
    cv.create_line(_scale(pts, s), fill=color, width=w,
                   capstyle="round", joinstyle="round", smooth=smooth)


def _poly(cv, pts, s, color, w):
    cv.create_polygon(_scale(pts, s), outline=color, fill="", width=w,
                      joinstyle="round")


def _oval(cv, x, y, d, s, color, w):
    cv.create_oval(x * s + _OX, y * s + _OY, (x + d) * s + _OX,
                   (y + d) * s + _OY, outline=color, width=w)


def _rrect(cv, x, y, w_, h_, s, color, lw, r=2.0):
    """圆角矩形描边：用多边形逼近（tkinter 没有原生圆角矩形）。"""
    pts = []
    corners = ((x + r, y + r, 180), (x + w_ - r, y + r, 270),
               (x + w_ - r, y + h_ - r, 0), (x + r, y + h_ - r, 90))
    for cx, cy, start in corners:
        for i in range(7):
            a = math.radians(start + i * 15)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _poly(cv, pts, s, color, lw)


def _ring(cv, cx, cy, r, s, color, w, spokes=0, inner=0.0):
    """齿轮：正 spokes 边形轮廓 + 内圈。"""
    pts = []
    n = max(3, spokes)
    for i in range(n):
        a = math.radians(360.0 / n * i - 90)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _poly(cv, pts, s, color, w)
    if inner:
        _oval(cv, cx - inner, cy - inner, inner * 2, s, color, w)


# ---------------------------------------------------------------- 图标定义
def _home(cv, s, color, w):
    _line(cv, [(3, 11.2), (12, 3.8), (21, 11.2)], s, color, w)
    _rrect(cv, 5, 10, 14, 10, s, color, w, r=2.2)
    _line(cv, [(10, 20), (10, 14.6), (14, 14.6), (14, 20)], s, color, w)


def _grid(cv, s, color, w):
    for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
        _rrect(cv, x, y, 8, 8, s, color, w, r=2.2)


def _chart(cv, s, color, w):
    _line(cv, [(3.4, 20.4), (20.6, 20.4)], s, color, w)
    for x, top in ((6.6, 13.5), (12, 8.2), (17.4, 16)):
        _line(cv, [(x, 19.6), (x, top)], s, color, w * 2.1)


def _monitor(cv, s, color, w):
    _rrect(cv, 2.6, 4, 18.8, 12.6, s, color, w, r=2.4)
    _line(cv, [(12, 16.6), (12, 19.4)], s, color, w)
    _line(cv, [(8.6, 19.4), (15.4, 19.4)], s, color, w)
    _line(cv, [(5.6, 13), (9.4, 9.2), (12.6, 11.8), (18, 7)], s, color, w)


def _clock(cv, s, color, w):
    _oval(cv, 3.6, 3.6, 16.8, s, color, w)
    _line(cv, [(12, 7.4), (12, 12.2), (15.6, 14.4)], s, color, w)


def _gear(cv, s, color, w):
    _ring(cv, 12, 12, 8.4, s, color, w, spokes=8, inner=3.4)


def _search(cv, s, color, w):
    _oval(cv, 4, 4, 12, s, color, w)
    _line(cv, [(13.2, 13.2), (20, 20)], s, color, w)


def _collapse(cv, s, color, w):
    _line(cv, [(12, 6.6), (12, 17.4)], s, color, w)
    _line(cv, [(8.2, 9), (4.2, 12), (8.2, 15)], s, color, w)
    _line(cv, [(15.8, 9), (19.8, 12), (15.8, 15)], s, color, w)


def _power(cv, s, color, w):
    cv.create_arc(6 * s + _OX, 6 * s + _OY, 18 * s + _OX, 18 * s + _OY,
                  start=38, extent=284, style="arc", outline=color, width=w)
    _line(cv, [(12, 3.4), (12, 11.4)], s, color, w)


def _pet(cv, s, color, w):
    """小章鱼：圆头 + 两条触手（桌宠入口）。"""
    _oval(cv, 4.6, 3.4, 14.8, s, color, w)
    _line(cv, [(8.6, 12), (8.6, 15), (6.4, 17.4)], s, color, w, smooth=True)
    _line(cv, [(15.4, 12), (15.4, 15), (17.6, 17.4)], s, color, w, smooth=True)
    _oval(cv, 8.5, 9.6, 1.8, s, color, w)
    _oval(cv, 13.7, 9.6, 1.8, s, color, w)


def _refresh(cv, s, color, w):
    cv.create_arc(3.6 * s + _OX, 3.6 * s + _OY, 20.4 * s + _OX, 20.4 * s + _OY,
                  start=48, extent=272, style="arc", outline=color, width=w)
    _line(cv, [(17.4, 3.6), (20.6, 3.6), (20.6, 6.8)], s, color, w)


def _folder(cv, s, color, w):
    _line(cv, [(3, 6.4), (9, 6.4), (11, 8.8), (21, 8.8), (21, 18.6),
               (3, 18.6), (3, 6.4)], s, color, w)


def _close(cv, s, color, w):
    _line(cv, [(6, 6), (18, 18)], s, color, w)
    _line(cv, [(18, 6), (6, 18)], s, color, w)


def _calendar(cv, s, color, w):
    _rrect(cv, 3, 4.6, 18, 15.4, s, color, w, r=2.2)
    _line(cv, [(7.6, 2.6), (7.6, 6.4)], s, color, w)
    _line(cv, [(16.4, 2.6), (16.4, 6.4)], s, color, w)
    _line(cv, [(3, 9.4), (21, 9.4)], s, color, w)


ICONS = {
    "home": _home,
    "grid": _grid,
    "chart": _chart,
    "monitor": _monitor,
    "clock": _clock,
    "gear": _gear,
    "search": _search,
    "collapse": _collapse,
    "power": _power,
    "pet": _pet,
    "refresh": _refresh,
    "folder": _folder,
    "close": _close,
    "calendar": _calendar,
}


def draw_icon(canvas, name: str, size: int, color: str,
              ox: float = 0.0, oy: float = 0.0, clear: bool = True):
    """在 canvas 上重绘指定图标（ox / oy 可把图标画到画布内的某个角落）。

    clear=False 时不清理画布 —— 供渐变按钮这类「先画背景再叠图标」的场景。
    """
    global _OX, _OY
    if clear:
        canvas.delete("all")
    fn = ICONS.get(name)
    if fn is None:
        return
    _OX, _OY = ox, oy
    try:
        s = size / G
        fn(canvas, s, color, max(1.15, 1.7 * s))
    finally:
        _OX = _OY = 0.0


class IconLabel(tk.Canvas):
    """一个只画线性图标的小部件（背景跟随父容器，颜色可随时换）。"""

    def __init__(self, master, name, size=20, color="#333333", bg=None):
        try:
            bg = bg or master.cget("bg")
        except tk.TclError:
            bg = "#ffffff"
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self.name = name
        self.size = size
        self._color = color
        draw_icon(self, name, size, color)

    def set_color(self, color: str):
        if color != self._color:
            self._color = color
            draw_icon(self, self.name, self.size, color)

    def set_icon(self, name: str):
        self.name = name
        draw_icon(self, name, self.size, self._color)
