# -*- coding: utf-8 -*-
"""通用小工具：窗口居中、图片/PhotoImage 处理、圆角矩形、打开目标等。

放在独立模块里，是为了让 gui.app（主框架）和 gui.pages（各页面）
都能引用，不会互相循环导入。
"""
import base64
import math
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox


def open_target(path: str):
    """用系统默认方式打开文件 / 文件夹 / 快捷方式。"""
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showerror("打开失败", str(e))


def make_photo(png, sink: list):
    """把 PNG 字节转成 tkinter PhotoImage；sink 用于持有引用防止被回收。"""
    if not png:
        return None
    try:
        photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
    except tk.TclError:
        return None
    sink.append(photo)
    return photo


def load_image_file(path: str, size: int = 44, sink: list = None):
    """从本地图片文件读取并缩放到 size（返回 PhotoImage，失败返回 None）。

    tkinter 只能整数倍缩放，这里用最接近的整倍数再微调（zoom/subsample）。
    """
    try:
        img = tk.PhotoImage(file=path)
    except Exception:
        return None
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return None
    factor = max(1, int(round(w / float(size))))
    if factor > 1:
        img = img.subsample(factor, factor)
    elif w < size:      # 图太小就放大回去
        img = img.zoom(max(1, size // max(1, w)), max(1, size // max(1, h)))
    if sink is not None:
        sink.append(img)
    return img


def shrink(photo, size: int, sink: list = None):
    """把 PhotoImage 整数倍缩小到不超过 size（系统图标常比请求的大）。"""
    if photo is not None and photo.width() > size:
        f = max(1, math.ceil(photo.width() / float(size)))
        photo = photo.subsample(f, f)
        if sink is not None:
            sink.append(photo)
    return photo


def rounded_rect(canvas, x1, y1, x2, y2, r=12, **kw):
    """在 Canvas 上画圆角矩形（tkinter 没有原生圆角矩形）。"""
    pts = []
    for cx, cy, start in ((x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270),
                          (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90)):
        for i in range(11):
            a = math.radians(start + i * 9)
            pts += (cx + r * math.cos(a), cy + r * math.sin(a))
    return canvas.create_polygon(pts, smooth=True, **kw)


def short_name(name: str, limit: int = 12) -> str:
    """超过长度用省略号截断，避免磁贴文字被硬切。"""
    name = name.strip()
    return name if len(name) <= limit else name[:limit - 1] + "…"


def center_window(win, w: int, h: int, parent=None) -> None:
    """把窗口放到父窗口（没有父窗口则屏幕）正中央，并保证不超出屏幕。

    不指定位置的 Toplevel 默认由窗口管理器随便安排，通常就出现在左上角。
    """
    win.update_idletasks()
    if parent is not None and parent.winfo_ismapped():
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    else:
        px, py = 0, 0
        pw, ph = win.winfo_screenwidth(), win.winfo_screenheight()
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(0, min(x, sw - w))
    y = max(0, min(y, sh - h))
    win.geometry(f"{w}x{h}+{x}+{y}")
    # Tk 的 geometry 定位的是客户区，外框（边框+标题栏）会再偏出去一点；
    # 读回真实位置做一次补偿，保证整个窗口（含边框）视觉上居中。
    win.update_idletasks()
    dx, dy = win.winfo_rootx() - x, win.winfo_rooty() - y
    if dx or dy:
        win.geometry(f"{w}x{h}+{max(0, x - dx)}+{max(0, y - dy)}")


def hline(parent, color, padx=0, pady=6):
    """一条水平分隔线。"""
    f = tk.Frame(parent, bg=color, height=1)
    f.pack(fill="x", padx=padx, pady=pady)
    return f


def stat_bar(parent, ratio, c: dict, width=220, height=10, side="left"):
    """统计占比条：底槽 + 按 ratio 填充的彩色条（自动 pack 到 parent）。"""
    wrap = tk.Frame(parent, bg=c["stat_bar_bg"], width=width, height=height)
    wrap.pack(side=side, padx=4)
    wrap.pack_propagate(False)
    cv = tk.Canvas(wrap, width=width, height=height, bg=c["stat_bar_bg"],
                   highlightthickness=0, bd=0)
    cv.pack()
    r = 0.0 if ratio <= 0 else (1.0 if ratio >= 1 else ratio)
    if r > 0:
        cv.create_rectangle(0, 0, max(2, int(width * r)), height,
                            fill=c["stat_bar"], outline="")
    return wrap
