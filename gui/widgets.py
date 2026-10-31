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
from tkinter import font as tkfont
from tkinter import messagebox

from gui.navicons import ICONS, IconLabel, draw_icon


# ---- 颜色小工具（渐变按钮用）----
def hex_rgb(color: str):
    color = (color or "#000000").lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def rgb_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def mix(c1: str, c2: str, t: float) -> str:
    """两个颜色按 t（0~1）插值。"""
    a, b = hex_rgb(c1), hex_rgb(c2)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return rgb_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


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


class ModernButton(tk.Canvas):
    """胶囊渐变按钮：圆角 + 垂直线性渐变 + hover 高亮 + 内置线性图标。

    tkinter 原生按钮是纯色直角块，这里用 Canvas 逐行着色做出渐变胶囊，
    看起来更接近现代 App；行为（hover / 点击）与 tk.Button 一致。
    """

    FONT = ("Microsoft YaHei", 10)
    ICON_GAP = 7

    def __init__(self, master, text="", command=None, c=None, primary=False,
                 icon=None, height=34, padx=16, font=None, icon_size=17):
        c = dict(c or {})
        self.c = c
        self.primary = primary
        self.text = text
        self.command = command
        self.icon = icon if icon in ICONS else None
        self.icon_size = icon_size
        self.padx = padx
        self.font = tuple(font or self.FONT)
        self._hover = False
        self._pressed = False
        self._enabled = True

        f = tkfont.Font(font=self.font)
        tw = f.measure(text) if text else 0
        icon_w = (icon_size + self.ICON_GAP) if self.icon else 0
        self.W = int(padx * 2 + icon_w + tw)
        self.H = int(height)
        super().__init__(master, width=self.W, height=self.H,
                         bg=c.get("app_bg", "#eeeeee"),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._paint()
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: (self._set_hover(False),
                                        self._set_pressed(False)))
        self.bind("<ButtonPress-1>", lambda e: self._set_pressed(True))
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---- 状态 ----
    def _set_hover(self, on):
        if on != self._hover:
            self._hover = on
            self._paint()

    def _set_pressed(self, on):
        if on != self._pressed:
            self._pressed = on
            self._paint()

    def _on_release(self, e=None):
        self._pressed = False
        self._paint()
        if self._enabled and self.command is not None:
            self.command()

    def set_text(self, text: str):
        self.text = text
        f = tkfont.Font(font=self.font)
        icon_w = (self.icon_size + self.ICON_GAP) if self.icon else 0
        self.W = int(self.padx * 2 + icon_w + (f.measure(text) if text else 0))
        self.config(width=self.W)
        self._paint()

    def set_command(self, command):
        self.command = command

    def set_enabled(self, on: bool):
        self._enabled = bool(on)
        self.config(cursor="hand2" if on else "arrow")
        self._paint()

    # ---- 绘制 ----
    def _colors(self):
        c = self.c
        if self.primary:
            top = c.get("accent_hover") if self._hover else c.get("accent")
            bot = c.get("accent_2_hover") if self._hover else c.get("accent_2")
            fg = c.get("accent_fg", "#ffffff")
        else:
            base = c.get("panel_active", "#e5e5ea") if self._hover \
                else c.get("panel_bg", "#ffffff")
            top = base
            bot = mix(base, c.get("accent", "#4b6bfb"),
                      0.30 if self._hover else 0.16)
            fg = c.get("accent", "#4b6bfb") if self._hover \
                else c.get("text", "#333333")
        if self._pressed:
            top, bot = mix(top, "#000000", 0.12), mix(bot, "#000000", 0.12)
        return top or "#cccccc", bot or "#999999", fg

    def _paint(self):
        self.delete("all")
        w, h, r = self.W, self.H, self.H / 2.0
        top, bot, fg = self._colors()
        if not self._enabled:
            top = bot = mix(top, self.c.get("app_bg", "#eeeeee"), 0.55)
            fg = mix(fg, self.c.get("app_bg", "#eeeeee"), 0.55)
        # 胶囊：逐行填充渐变（天然形成两端圆角）
        for y in range(h):
            dy = abs(y - (h - 1) / 2.0)
            if dy > r:
                continue
            dx = math.sqrt(max(0.0, r * r - dy * dy))
            self.create_line(int(r - dx), y, int(w - r + dx), y,
                             fill=mix(top, bot, y / max(1.0, h - 1.0)))
        # 淡描边，边缘更干净
        self.create_oval(0, 0, h - 1, h - 1, outline=mix(bot, "#000000", 0.06))
        self.create_oval(w - h, 0, w - 1, h - 1,
                         outline=mix(bot, "#000000", 0.06))
        self.create_line(h / 2, 0, w - h / 2, 0, fill=mix(bot, "#000000", 0.06))
        self.create_line(h / 2, h - 1, w - h / 2, h - 1,
                         fill=mix(bot, "#000000", 0.06))

        x = self.padx
        if self.icon:
            draw_icon(self, self.icon, self.icon_size, fg, x,
                      (h - self.icon_size) / 2.0, clear=False)
            x += self.icon_size + self.ICON_GAP
        if self.text:
            self.create_text(x, h / 2.0, text=self.text, anchor="w",
                             fill=fg, font=self.font)


class RoundedEntry(tk.Canvas):
    """圆角搜索框：胶囊底 + 线性放大镜图标 + 输入框 + 清除按钮。"""

    def __init__(self, master, c, textvariable=None, height=34, icon="search",
                 on_clear=None, on_return=None, on_escape=None):
        c = dict(c or {})
        self.c = c
        self.H = int(height)
        self.on_clear = on_clear
        super().__init__(master, height=self.H,
                         bg=c.get("sidebar_bg", "#ffffff"),
                         highlightthickness=0, bd=0)
        bg = c.get("search_bg", "#f2f5fb")
        self.var = textvariable if textvariable is not None else tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, relief="flat", bd=0,
                              bg=bg, fg=c.get("text", "#333333"),
                              insertbackground=c.get("text", "#333333"),
                              highlightthickness=0,
                              font=("Microsoft YaHei", 10),
                              selectbackground=c.get("accent", "#4b6bfb"),
                              selectforeground=c.get("accent_fg", "#ffffff"))
        self.ic = IconLabel(self, icon, 16, c.get("nav_icon", "#5a6478"), bg=bg)
        self.clr = IconLabel(self, "close", 13, c.get("nav_icon", "#5a6478"), bg=bg)
        self.clr.bind("<Button-1>", lambda e: self._clear())
        if on_return is not None:
            self.entry.bind("<Return>", on_return)
        if on_escape is not None:
            self.entry.bind("<Escape>", on_escape)
        self.bind("<Configure>", self._layout)
        self._layout()

    def _layout(self, event=None):
        w = self.winfo_width()
        if w < 60:
            return
        h = self.H
        self.delete("bg")
        rounded_rect(self, 0, 0, w, h, r=h / 2.0,
                     fill=self.c.get("search_bg", "#f2f5fb"),
                     outline=self.c.get("divider", "#e6e9f0"), tags="bg")
        self.ic.place(x=11, y=(h - 16) // 2)
        self.clr.place(x=w - 24, y=(h - 13) // 2)
        self.entry.place(x=34, y=5, width=max(10, w - 34 - 26), height=h - 10)

    def _clear(self):
        self.var.set("")
        if self.on_clear is not None:
            self.on_clear()

    def focus_set(self):
        """供外部调用：把光标放到输入框里。"""
        self.entry.focus_set()
        return self


def hover_card(tile, children, c, base_bg, hover_bg, grow=6, shadow=None,
               slot=None):
    """给首页磁贴挂上 hover 动效：微微放大 + 淡阴影 + 底色高亮。

    tile 必须放在固定尺寸的槽位里并 place 居中（这样放大时不会推动邻居）。
    返回 (enter, leave) 两个回调，直接 bind 到 <Enter> / <Leave>。
    """
    def _paint(on):
        bg = hover_bg if on else base_bg
        try:
            tile.configure(bg=bg)
        except tk.TclError:
            pass
        for w in children:
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass

    def _resize(on):
        """放大 / 还原。place 布局的磁贴要用 place_configure，
        否则 place 里写死的 width 会盖住 configure(width=...)。"""
        try:
            info = tile.place_info() or {}
        except tk.TclError:
            info = {}
        try:
            cur_w = int(float(info.get("width") or 0)) or tile.winfo_width()
            cur_h = int(float(info.get("height") or 0)) or tile.winfo_height()
            new_w, new_h = cur_w + (grow if on else -grow), cur_h + (grow if on else -grow)
            if info:
                tile.place_configure(width=new_w, height=new_h)
            else:
                tile.configure(width=new_w, height=new_h)
        except (tk.TclError, ValueError):
            pass

    def _shadow(on):
        if shadow is None:
            return
        try:
            shadow.configure(bg=c.get("shadow", "#c3cbdc") if on
                             else (slot or tile).cget("bg"))
        except tk.TclError:
            pass

    def enter(e=None):
        _shadow(True)
        _resize(True)
        _paint(True)

    def leave(e=None):
        _paint(False)
        _resize(False)
        _shadow(False)
    return enter, leave


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
