# -*- coding: utf-8 -*-
"""
桌面悬浮宠物「墨墨」—— 从主程序召唤到桌面上的独立悬浮窗。

三个特性：
  1. 无边框 + 背景完全透明：overrideredirect + `-transparentcolor`，
     只显示章鱼本体，没有白底/灰底
  2. 鼠标穿透：Windows 对透明色区域不做命中测试，点击直接穿过去；
     另附"完全穿透"模式（Win32 WS_EX_TRANSPARENT）
  3. 上下浮动：after() 定时器 + 正弦曲线驱动 Y 坐标

注意：这里用 tk.Toplevel 而不是 tk.Tk —— 主程序只有一个根窗口，
再开一个 Tk 实例会产生第二套 Tcl 解释器，图片资源不通用。
Toplevel 是子窗口，还会跟着主窗口一起退出。
"""

import ctypes
import math
import os
import struct
import time
import zlib
from ctypes import wintypes

import tkinter as tk

# ==========================================================================
#  可调参数
# ==========================================================================

PET_SIZE = 100               # 宠物显示尺寸（像素，改这里就能大/小）

FLOAT_AMPLITUDE = 8          # ★浮动幅度：向上/向下各移动多少像素（0 = 静止）
FLOAT_PERIOD = 4.0           # ★浮动速度：完成一次「上→下→上」的秒数
                             #            数值越大 = 游得越慢
                             #            2.0 轻快 / 4.0 悠闲 / 8.0 慢悠悠
FPS = 60                     # 动画帧率（30 也够顺滑且更省 CPU）

MARGIN_RIGHT = 80            # 初始位置：距屏幕右边
MARGIN_BOTTOM = 110          # 初始位置：距屏幕底边（留任务栏）

KEY_COLOR = "#ff00ff"        # 透明色（品红）；图片里若有同色像素会被挖空

HAPPY_MS = 900               # ★点击后眯眼笑形态保持的毫秒数，之后变回睁眼

# ==========================================================================
#  Win32
# ==========================================================================

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def hwnd_of(win) -> int:
    return int(win.frame(), 16) if win.frame() else 0


def set_full_through(hwnd: int, enabled: bool) -> None:
    """完全穿透：开启后连章鱼本体也不挡点击（同时也无法拖动它）。"""
    if not hwnd:
        return
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_TRANSPARENT) if enabled \
        else (style & ~WS_EX_TRANSPARENT)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def screen_size():
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


# ==========================================================================
#  PNG 解码（自己解，为了拿到真实 alpha —— Tk 只给出"是否全透明"的布尔值）
# ==========================================================================

def decode_png(path: str):
    """解码 PNG → (w, h, rgba:bytearray)。仅支持 8bit 非隔行，其它返回 None。"""
    try:
        data = open(path, "rb").read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos, idat = 8, bytearray()
        w = h = bd = ct = None
        while pos < len(data):
            if pos + 8 > len(data):
                break
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            tag = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            if tag == b"IHDR":
                w, h, bd, ct, _c, _f, inter = struct.unpack(">IIBBBBB", chunk)
                if bd != 8 or inter != 0:
                    return None
            elif tag == b"IDAT":
                idat += chunk
            elif tag == b"IEND":
                break
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ct)
        if w is None or channels is None:
            return None

        raw = zlib.decompress(bytes(idat))
        stride = w * channels
        out = bytearray(h * stride)
        prev = bytearray(stride)
        p = 0
        for y in range(h):
            ft = raw[p]
            p += 1
            line = bytearray(raw[p:p + stride])
            p += stride
            if ft == 1:
                for i in range(channels, stride):
                    line[i] = (line[i] + line[i - channels]) & 255
            elif ft == 2:
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 255
            elif ft == 3:
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
            elif ft == 4:
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    b = prev[i]
                    c = prev[i - channels] if i >= channels else 0
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pred = a if (pa <= pb and pa <= pc) else \
                        (b if pb <= pc else c)
                    line[i] = (line[i] + pred) & 255
            out[y * stride:(y + 1) * stride] = line
            prev = line

        rgba = bytearray(w * h * 4)
        if ct == 6:
            rgba = out
        elif ct == 2:
            for i in range(w * h):
                rgba[i * 4:i * 4 + 3] = out[i * 3:i * 3 + 3]
                rgba[i * 4 + 3] = 255
        elif ct == 0:
            for i in range(w * h):
                v = out[i]
                rgba[i * 4:i * 4 + 3] = bytes((v, v, v))
                rgba[i * 4 + 3] = 255
        elif ct == 4:
            for i in range(w * h):
                v = out[i * 2]
                rgba[i * 4:i * 4 + 3] = bytes((v, v, v))
                rgba[i * 4 + 3] = out[i * 2 + 1]
        else:                       # 调色板
            return None
        return w, h, rgba
    except Exception:
        return None


# ==========================================================================
#  图像处理：缩放 → 去边 → 抖动二值化 → PhotoImage
# ==========================================================================

BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def resize_rgba(src_rgba, sw, sh, size):
    """双线性缩放到 size×size（含 alpha）。"""
    dst = bytearray(size * size * 4)
    fx, fy = sw / size, sh / size
    for y in range(size):
        sy = min(sh - 1, int(y * fy + 0.5))
        sy2 = min(sh - 1, sy + 1)
        wy = y * fy + 0.5 - sy
        wy = 0.0 if wy < 0 else (1.0 if wy > 1 else wy)
        for x in range(size):
            sx = min(sw - 1, int(x * fx + 0.5))
            sx2 = min(sw - 1, sx + 1)
            wx = x * fx + 0.5 - sx
            wx = 0.0 if wx < 0 else (1.0 if wx > 1 else wx)
            i00 = (sy * sw + sx) * 4
            i10 = (sy * sw + sx2) * 4
            i01 = (sy2 * sw + sx) * 4
            i11 = (sy2 * sw + sx2) * 4
            o = (y * size + x) * 4
            for c in range(4):
                a = src_rgba[i00 + c]
                b = src_rgba[i10 + c]
                cc = src_rgba[i01 + c]
                d = src_rgba[i11 + c]
                top = a + (b - a) * wx
                bot = cc + (d - cc) * wx
                dst[o + c] = int(top + (bot - top) * wy)
    return dst


def defringe(rgba, size):
    """去边：半透明像素原本是与背景混合过的灰白色，直接显示会留一圈灰边。

    这里把它们的 RGB 换成邻近实体像素的颜色，边缘就不会发灰。
    """
    col = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            o = (y * size + x) * 4
            if rgba[o + 3] >= 250:
                col[y][x] = (rgba[o], rgba[o + 1], rgba[o + 2])
    for y in range(size):                       # 正向传播
        for x in range(size):
            if col[y][x] is None:
                c = (col[y][x - 1] if x else None) or \
                    (col[y - 1][x] if y else None)
                if c:
                    col[y][x] = c
    for y in range(size - 1, -1, -1):           # 反向补漏
        for x in range(size - 1, -1, -1):
            if col[y][x] is None:
                c = (col[y][x + 1] if x + 1 < size else None) or \
                    (col[y + 1][x] if y + 1 < size else None)
                if c:
                    col[y][x] = c
    for y in range(size):
        for x in range(size):
            o = (y * size + x) * 4
            c = col[y][x]
            if c:
                rgba[o], rgba[o + 1], rgba[o + 2] = c
    return rgba


def build_photo(master, rgba, size, key_rgb=(255, 0, 255)):
    """抖动二值化后生成 PhotoImage。

    transparentcolor 按"颜色"抠图，不支持半透明；若保留半透明像素，它们会
    和品红背景混合成紫边。用 4×4 Bayer 矩阵把 alpha 抖动成全透明/全不透明，
    视觉上仍然柔和，但不会出现紫边。
    """
    rows = []
    kr, kg, kb = key_rgb
    for y in range(size):
        parts = []
        for x in range(size):
            o = (y * size + x) * 4
            a = rgba[o + 3]
            thr = (BAYER4[y & 3][x & 3] + 0.5) * 16
            if a <= thr:
                parts.append("{#%02x%02x%02x}" % (kr, kg, kb))
            else:
                parts.append("{#%02x%02x%02x}" % (rgba[o], rgba[o + 1], rgba[o + 2]))
        rows.append("{" + " ".join(parts) + "}")
    photo = tk.PhotoImage(master=master, width=size, height=size)
    photo.put(" ".join(rows), to=(0, 0, size, size))
    return photo


def default_image_path() -> str:
    """默认用项目 assets 里的墨墨立绘（睁眼形态）。"""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets")
    return os.path.join(base, "momo-open.png")


def load_pet(master, path, size):
    dec = decode_png(path) if path and os.path.isfile(path) else None
    if dec:
        sw, sh, srgba = dec
        scaled = resize_rgba(srgba, sw, sh, size)
        defringe(scaled, size)
        return build_photo(master, scaled, size)
    return None


def load_pet_fallback(master, size):
    """按优先级尝试素材表，全失败返回 None（由调用方画兜底章鱼）。"""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets")
    for name in ("momo-open.png", "mascot-stand.png"):
        photo = load_pet(master, os.path.join(base, name), size)
        if photo is not None:
            return photo
    return None


# ==========================================================================
#  桌宠窗口
# ==========================================================================

class DesktopPet(tk.Toplevel):
    """悬浮在桌面上的墨墨：无边框、真透明、可穿透、会上下浮动。"""

    def __init__(self, master, image_path=None, full_through=False):
        super().__init__(master)
        self._master = master

        # ---- 1) 无边框 + 透明背景 ----
        self.overrideredirect(True)
        self.config(bg=KEY_COLOR)
        self.attributes("-transparentcolor", KEY_COLOR)
        self.attributes("-topmost", True)       # 置顶

        # ---- 图片（睁眼默认形态 + 点击时的眯眼笑形态）----
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "assets")
        self._photo = load_pet(self, image_path or default_image_path(), PET_SIZE) \
            or load_pet_fallback(self, PET_SIZE)
        if self._photo is None:                 # 图片缺失时画一只兜底章鱼
            self._photo = self._fallback_photo()
        happy_path = os.path.join(base, "momo-happy.png")
        self._photo_happy = load_pet(self, happy_path, PET_SIZE) or self._photo
        self._label = tk.Label(self, image=self._photo, bg=KEY_COLOR,
                               bd=0, highlightthickness=0, cursor="fleur")
        self._label.pack()
        self.geometry(f"{PET_SIZE}x{PET_SIZE}")

        # ---- 位置 ----
        sw, sh = screen_size()
        self._base_x = max(0, sw - PET_SIZE - MARGIN_RIGHT)
        self._base_y = max(0, sh - PET_SIZE - MARGIN_BOTTOM)
        self._start = time.monotonic()
        self._dragging = None
        self.update_idletasks()
        self.geometry(f"+{self._base_x}+{self._base_y}")

        # ---- 2) 完全穿透 ----
        self._hwnd = hwnd_of(self)
        self._full_through = False
        self.set_full_through(full_through)

        # ---- 交互 ----
        self._label.bind("<ButtonPress-1>", self._on_press)
        self._label.bind("<B1-Motion>", self._on_move)
        self._label.bind("<ButtonRelease-1>", self._on_release)
        self._label.bind("<Button-3>", self._popup)
        self._label.bind("<Escape>", lambda e: self.on_close())
        self._build_menu()

        # ---- 3) 浮动 ----
        self._alive = True
        self._tick()

    # ---------- 浮动 ----------
    def _tick(self):
        if not self._alive:
            return
        try:
            if self._dragging is None:
                t = time.monotonic() - self._start
                if FLOAT_AMPLITUDE > 0 and FLOAT_PERIOD > 0:
                    phase = (t / FLOAT_PERIOD) * 2.0 * math.pi
                    off = -FLOAT_AMPLITUDE * math.sin(phase)
                else:
                    off = 0
                self.geometry(f"+{self._base_x}+{int(self._base_y + off)}")
            self.after(max(8, int(1000 / FPS)), self._tick)
        except tk.TclError:
            self._alive = False      # 已随主窗口销毁

    def set_speed(self, period, amplitude):
        """运行时改速度：period 越大越慢，amplitude 是上下各多少像素。"""
        global FLOAT_PERIOD, FLOAT_AMPLITUDE
        FLOAT_PERIOD, FLOAT_AMPLITUDE = period, amplitude
        self._start = time.monotonic()

    # ---------- 拖动 ----------
    # 注意：Toplevel 的 winfo_x() 是相对父窗口的坐标，必须用 winfo_rootx()
    # 取屏幕坐标，否则和事件的 x_root 混用会导致拖动手感"跳位"。
    def _on_press(self, e):
        self._dragging = (e.x_root, e.y_root,
                          self.winfo_rootx(), self.winfo_rooty())

    def _on_move(self, e):
        if self._dragging:
            gx, gy, ox, oy = self._dragging
            self._base_x = ox + (e.x_root - gx)
            self._base_y = oy + (e.y_root - gy)
            self.geometry(f"+{self._base_x}+{self._base_y}")

    def _on_release(self, e):
        if self._dragging:
            gx, gy = self._dragging[0], self._dragging[1]
            moved = abs(e.x_root - gx) + abs(e.y_root - gy)
            self._dragging = None
            if moved < 6:               # 没怎么动 = 单击 → 开心一下
                self.show_happy()

    # ---------- 表情 ----------
    def show_happy(self):
        """单击墨墨：眯眼笑一会儿，再变回睁眼。"""
        if self._photo_happy is self._photo:
            return
        self._label.config(image=self._photo_happy)
        if getattr(self, "_happy_job", None):
            self.after_cancel(self._happy_job)
        self._happy_job = self.after(HAPPY_MS, self._back_to_open)

    def _back_to_open(self):
        self._happy_job = None
        try:
            self._label.config(image=self._photo)
        except tk.TclError:
            pass                        # 窗口已销毁

    # ---------- 右键菜单 ----------
    def _build_menu(self):
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="完全穿透（不挡任何点击）",
                               command=lambda: self.set_full_through(
                                   not self._full_through))
        self._menu.add_separator()
        self._menu.add_command(label="浮动：慢悠悠",
                               command=lambda: self.set_speed(8.0, 8))
        self._menu.add_command(label="浮动：悠闲",
                               command=lambda: self.set_speed(4.0, 8))
        self._menu.add_command(label="浮动：轻快",
                               command=lambda: self.set_speed(2.0, 6))
        self._menu.add_command(label="浮动：静止",
                               command=lambda: self.set_speed(4.0, 0))
        self._menu.add_separator()
        self._menu.add_command(label="收起墨墨", command=self.on_close)

    def _popup(self, e):
        self._menu.tk_popup(e.x_root, e.y_root)

    def set_full_through(self, enabled):
        self._full_through = enabled
        set_full_through(self._hwnd, enabled)

    # ---------- 关闭 ----------
    def on_close(self):
        """收起桌宠（通知主窗口同步按钮状态）。"""
        self._alive = False
        try:
            cb = getattr(self._master, "_on_pet_closed", None)
            if cb:
                cb()
        except Exception:
            pass
        self.destroy()

    # ---------- 兜底章鱼 ----------
    def _fallback_photo(self):
        size = PET_SIZE
        pm = tk.PhotoImage(master=self, width=size, height=size)
        rows = []
        cx, cy = size / 2.0, size * 0.42
        rx, ry = size * 0.34, size * 0.30
        body, dark, key = (38, 118, 108), (26, 84, 78), (255, 0, 255)
        for y in range(size):
            parts = []
            for x in range(size):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if dx * dx + dy * dy <= 1.0:
                    hit = False
                    for ex in (cx - rx * 0.42, cx + rx * 0.42):
                        if abs(x + 0.5 - ex) <= size * 0.055 and \
                                abs(y + 0.5 - (cy - ry * 0.1)) <= size * 0.018:
                            parts.append("{#ffffff}")
                            hit = True
                            break
                    if not hit:
                        parts.append("{#%02x%02x%02x}" % body)
                elif size * 0.62 <= y <= size * 0.92 and \
                        abs(x + 0.5 - cx) <= size * 0.36:
                    t = (x * 5.0 / size) % 1.0
                    parts.append("{#%02x%02x%02x}" % (dark if t < 0.55 else key))
                else:
                    parts.append("{#%02x%02x%02x}" % key)
            rows.append("{" + " ".join(parts) + "}")
        pm.put(" ".join(rows), to=(0, 0, size, size))
        return pm
