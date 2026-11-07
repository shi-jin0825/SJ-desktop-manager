# -*- coding: utf-8 -*-
"""
桌面悬浮宠物「墨墨」—— 2.0：物理引擎 + 系统状态联动 + 番茄钟伴学。

特性一览：
  1. 无边框 + 背景完全透明（-transparentcolor），透明区域自动鼠标穿透
  2. 物理引擎：
     · 抓起来拖动，松手把"甩出"的速度继承下来（vx / vy）
     · 重力下落、左右墙壁反弹、地面反弹衰减
     · 落地瞬间播放 Q 弹压缩动画（Tk 原生 zoom/subsample 生成整数比帧）
  3. 摸头互动：单击 → 眯眼笑；3 秒内连续点击 5 次 → 害羞
  4. 系统联动（可开关，零依赖复用 core/sysinfo）：
     · CPU 占用 ≥ 80% → 好热（汗滴 + 吐舌）
     · 内存负载 ≥ 85% → 疲惫（半闭眼），浮动也变得有气无力
     · 下载 ≥ 400 KB/s → 奔跑（速度线 + 横向跑动，越快跑得越快）
     状态变化时头顶冒气泡说明
  5. 番茄钟伴学：主窗口/右键菜单开启后，墨墨捧书陪你，头顶显示倒计时
  6. 右键菜单：番茄钟 / 物理开关 / 联动开关 / 穿透 / 浮动速度 / 收起

注意：tk.Toplevel（不是第二个 Tk 实例），资源与主窗口互通。
"""

import ctypes
import math
import os
import struct
import time
import traceback
import zlib
from ctypes import wintypes

import tkinter as tk

from core import dpi
from gui.fonts import font
from gui.tokens import FS

# ==========================================================================
#  可调参数
# ==========================================================================

PET_SIZE = 100               # 宠物显示尺寸（像素）

WIN_SCALE = 1.45             # 窗口相对图片的放大倍数（容纳 Q 弹拉伸）
                             # 图片在窗口内底部居中，四周透明可穿透

FLOAT_AMPLITUDE = 8          # 浮动幅度（0 = 静止）
FLOAT_PERIOD = 4.0           # 浮动周期（秒），越大越慢
FPS = 60                     # 动画帧率
MAX_DT = 0.05                # 单帧最大步长（秒）：卡顿后不跳穿，也不变慢动作

GRAVITY = 2200.0             # 重力加速度 px/s²
RESTITUTION = 0.42           # 反弹恢复系数（0~1，越大弹得越久）
BOUNCE_STOP_V = 160.0        # 反弹速度低于此值就停下来
DRAG_SMOOTH = 0.35           # 抛出速度 = 历史速度的指数平均系数
MAX_LAUNCH = 2600.0          # 抛出速度上限（防止甩飞出屏）

MARGIN_X = 80                # 水平安全边距
MARGIN_RIGHT = 80            # 初始位置：距屏幕右边
MARGIN_BOTTOM = 110          # 初始位置：距屏幕底边（留任务栏）

KEY_COLOR = "#ff00ff"        # 透明色（品红）

HAPPY_MS = 900               # 单击后开心形态保持毫秒数
SHY_AFTER_CLICKS = 5         # 3 秒内连续点击多少次后害羞
SHY_MS = 1600                # 害羞形态保持毫秒数

MONITOR_PERIOD_S = 1.0       # 系统状态采样间隔
CPU_HOT = 80                 # CPU 占用超过此值 → 好热
MEM_TIRED = 90               # 内存负载超过此值 → 疲惫
NET_FAST = 400 * 1024        # 下载速度超过此值 → 奔跑（字节/秒）
NET_RUN_SPEED = 150          # 奔跑横向速度基准 px/s（随网速加快）
SQUASH_MS = 260              # 落地压缩动画总时长

# ==========================================================================
#  Win32
# ==========================================================================

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
_user32 = ctypes.WinDLL("user32", use_last_error=True)


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


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


def work_area_height() -> int:
    """不含任务栏的工作区底边 y（落地以它为准）。"""
    rc = _RECT()
    if _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):
        return rc.bottom
    return screen_size()[1]


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
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets")
    for name in ("momo-open.png", "mascot-stand.png"):
        photo = load_pet(master, os.path.join(base, name), size)
        if photo is not None:
            return photo
    return None


def squash(base_photo, sy_num, sy_den, sx_num, sx_den):
    """整数比压缩帧：垂直 sy_num/sy_den、水平 sx_num/sx_den。

    用 Tk 原生 subsample（丢行）/zoom（复制行），C 实现，零 Python 循环。
    先 subsample 再 zoom 可实现任意 a/b 比例（a<b 压缩，a>b 拉伸）。
    """
    img = base_photo
    if sy_den != 1:
        img = img.subsample(1, sy_den)
    if sy_num != sy_den:
        img = img.zoom(1, sy_num)
    if sx_num != sx_den:
        img = img.zoom(sx_num, 1)
        img = img.subsample(sx_den, 1)
    return img


# ==========================================================================
#  表情表
# ==========================================================================

FACE_FILES = {
    "idle": "momo-open.png",      # 睁眼笑（默认）
    "happy": "momo-happy.png",    # 点击：开心
    "shy": "momo-shy.png",        # 连续点击：害羞
    "hot": "momo-hot.png",        # CPU 高：冒汗吐舌
    "tired": "momo-tired.png",    # 内存紧：疲惫
    "study": "momo-study.png",    # 番茄钟：伴学
    "run": "momo-run.png",        # 网速快：奔跑
}


# ==========================================================================
#  头顶气泡
# ==========================================================================

class Bubble(tk.Toplevel):
    """宠物头顶的气泡：Canvas 圆角矩形 + 文字，随宠物移动。"""

    PAD_X, PAD_Y = 10, 7
    TAIL = 9

    def __init__(self, pet, colors):
        super().__init__(pet)
        self.overrideredirect(True)
        self.config(bg=KEY_COLOR)
        self.attributes("-transparentcolor", KEY_COLOR)
        self.attributes("-topmost", True)
        self._pet = pet
        self._c = colors
        self._cv = tk.Canvas(self, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self._cv.pack(fill="both", expand=True)
        self.withdraw()
        self._auto = None
        self.bw = self.bh = 0
        # 优先级仲裁：番茄钟倒计时 > 庆祝 > 状态提示/互动，低优先级不许
        # 抢占高优先级的显示位（以前 8 处写入互相覆盖，倒计时一闪一闪）
        self._priority = 0
        self._hold_until = 0.0

    def say(self, text: str, ms=3000, priority: int = 1) -> bool:
        """显示气泡；ms 毫秒后自动消失（0 = 一直显示直到 hide）。

        有更高优先级的信息在显示时拒绝写入（返回 False），同优先级
        （如每秒刷新的倒计时）允许覆盖更新。
        """
        now = time.monotonic()
        if now < self._hold_until and priority < self._priority:
            return False
        c = self._c
        self._cv.delete("all")
        probe = self._cv.create_text(0, 0, text=text, anchor="nw",
                                     font=font(FS["xs"]), fill=c["text"])
        bx0, by0, bx1, by1 = self._cv.bbox(probe)
        self._cv.delete(probe)
        tw, th = bx1 - bx0, by1 - by0
        self.bw = tw + self.PAD_X * 2 + 20
        self.bh = th + self.PAD_Y * 2 + self.TAIL + 10
        self.geometry(f"{int(self.bw)}x{int(self.bh)}")
        self._cv.config(width=int(self.bw), height=int(self.bh))
        x0, y0 = 10, 4
        x1, y1 = 10 + tw + self.PAD_X * 2, y0 + th + self.PAD_Y * 2
        self._round_rect(self._cv, x0, y0, x1, y1, 10,
                         fill=c["bubble_bg"], outline=c["bubble_outline"])
        self._cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                             font=font(FS["xs"]), fill=c["text"],
                             justify="center")
        cx = self._pet._win_w // 2 + 10          # 尾巴对准章鱼头顶
        self._cv.create_polygon(cx - 7, y1 - 1, cx + 7, y1 - 1, cx, y1 + self.TAIL,
                                fill=c["bubble_bg"], outline="")
        self._cv.create_line(cx - 7, y1 - 1, cx, y1 + self.TAIL, cx + 7, y1 - 1,
                             fill=c["bubble_outline"])
        self.deiconify()
        if self._auto:
            try:
                self.after_cancel(self._auto)
            except Exception:
                pass
            self._auto = None
        self._priority = priority
        # ms=0 = 长期占位（如倒计时），靠同/更高优先级覆盖或 hide() 释放
        self._hold_until = now + (ms / 1000.0 if ms else 86400.0)
        if ms:
            self._auto = self.after(ms, self.hide)
        return True

    def hide(self):
        self._auto = None
        self._priority = 0
        self._hold_until = 0.0
        try:
            self.withdraw()
        except tk.TclError:
            pass

    def follow(self, pet_x, pet_y):
        self.geometry(f"+{int(pet_x + self._pet._win_w / 2 - self.bw / 2)}"
                      f"+{int(pet_y - self.bh + 10)}")

    @staticmethod
    def _round_rect(cv, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
               x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
               x1, y1 + r, x1, y1]
        return cv.create_polygon(pts, smooth=True, **kw)


# ==========================================================================
#  桌宠窗口
# ==========================================================================

class DesktopPet(tk.Toplevel):
    """悬浮在桌面上的墨墨：物理引擎 + 系统联动 + 番茄钟。"""

    def __init__(self, master, image_path=None, full_through=False):
        super().__init__(master)
        self._master = master
        # 按屏幕 DPI 放大：150% 缩放屏上 PET_SIZE 还是 100 物理像素会显得
        # 比界面小一圈（v1.7 以前就是这个情况）
        self._size = int(PET_SIZE * max(1.0, min(2.0, dpi.scale_factor())))

        # ---- 1) 无边框 + 透明背景 ----
        self.overrideredirect(True)
        self.config(bg=KEY_COLOR)
        self.attributes("-transparentcolor", KEY_COLOR)
        self.attributes("-topmost", True)

        # ---- 2) 表情库 ----
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "assets")
        self._faces = {}
        idle = load_pet(self, image_path or default_image_path(), self._size) \
            or load_pet_fallback(self, self._size)
        if idle is None:
            idle = self._fallback_photo()
        self._faces["idle"] = idle
        for key, name in FACE_FILES.items():
            if key == "idle":
                continue
            photo = load_pet(self, os.path.join(base, name), self._size)
            if photo is not None:
                self._faces[key] = photo
        self._face = "idle"

        # ---- 3) 窗口与布局（图片底部居中，方便 Q 弹压缩）----
        self._win_w = int(self._size * WIN_SCALE)
        self._win_h = int(self._size * WIN_SCALE)
        self._label = tk.Label(self, image=idle, bg=KEY_COLOR,
                               bd=0, highlightthickness=0, cursor="hand2")
        self._label.place(relx=0.5, rely=1.0, anchor="s")
        self.geometry(f"{self._win_w}x{self._win_h}")

        # ---- 位置 / 物理 ----
        self._sw, self._sh = screen_size()
        self._ground = float(max(0, work_area_height() - self._win_h - 40))
        self.x = float(max(0, self._sw - self._win_w - MARGIN_RIGHT))
        self.y = self._ground
        self._base_y = self._ground      # 浮动中心
        self.vx = self.vy = 0.0
        self._mode = "float"          # float / drag / fall
        self._squash = None           # (frames, t0)
        self._start = time.monotonic()
        self._last_geo = None
        self._dragging = None
        self._hist = []
        self._run_dir = 1
        self.update_idletasks()
        self.geometry(f"+{int(self.x)}+{int(self.y)}")

        # ---- 4) 完全穿透 ----
        self._hwnd = hwnd_of(self)
        self._full_through = False
        self.set_full_through(full_through)

        # ---- 交互 / 联动 ----
        self._clicks = []
        self._temp_until = 0.0        # 一次性表情（happy/shy）保持到这个时刻
        self._label.bind("<ButtonPress-1>", self._on_press)
        self._label.bind("<B1-Motion>", self._on_move)
        self._label.bind("<ButtonRelease-1>", self._on_release)
        self._label.bind("<Button-3>", self._popup)
        self._build_menu()

        cfg = getattr(master, "cfg", None)
        self._monitor_on = cfg.get_setting("pet_monitor", True) if cfg else True
        self._physics_on = cfg.get_setting("pet_physics", True) if cfg else True
        self._sys_state = "idle"
        self._net_down = 0.0          # 最近一次采到的下载速度（字节/秒）

        # 上次选的浮动节奏（慢悠悠 / 悠闲 / 轻快 / 静止）
        # 浮动参数放在实例上：早先 set_speed 改的是模块级全局，会污染下一次召唤
        self._float_period = FLOAT_PERIOD
        self._float_amp = FLOAT_AMPLITUDE
        if cfg is not None:
            try:
                period = float(cfg.get_setting("pet_float_period", FLOAT_PERIOD))
                amp = float(cfg.get_setting("pet_float_amplitude",
                                            FLOAT_AMPLITUDE))
            except (TypeError, ValueError):
                period, amp = FLOAT_PERIOD, FLOAT_AMPLITUDE
            self.set_speed(period, amp, remember=False)

        # ---- 番茄钟 ----
        self._pomo_showing = False    # 当前气泡是否在显示番茄钟倒计时
        self._celebrating = False     # 番茄钟结束后短暂的庆祝气泡
        self._celebrate_until = 0.0

        # ---- 气泡 ----
        self._bubble = Bubble(self, self._bubble_colors())
        self._bubble.follow(self.x, self.y)

        self._alive = True
        self._tick()
        self._monitor_tick()

    # ============================ 帧循环 ============================
    # 两条循环链的调度都放在 try 之外：任何非 TclError 的异常（KeyError、
    # TypeError…）都不能让下一帧不再被排队，否则桌宠会当场定格、控制台一声
    # 不吭 —— 这是最难排查的一类"静默死亡"。
    def _tick(self):
        if not self._alive:
            return
        try:
            self._step()
        except tk.TclError:
            self._alive = False          # 窗口已销毁，正常收摊
            return
        except Exception:
            traceback.print_exc()        # 其它异常：打出来，动画继续跑
        self.after(max(8, int(1000 / FPS)), self._tick)

    def _step(self):
        """一帧物理。

        dt 用「真实经过的时间」而不是固定 1/FPS：掉帧时（比如刚开机、
        被大窗口盖住）不会变成慢动作，最多是步子跨大一点（已夹上限）。
        """
        now = time.monotonic()
        last = getattr(self, "_last_t", None)
        if last is None:
            self._last_t = now
            last = now
        dt = now - last
        self._last_t = now
        if dt <= 0:
            dt = 1.0 / FPS
        dt = min(dt, MAX_DT)        # 长时间卡顿后不要一帧跳穿屏幕

        if self._mode == "drag":
            return                        # 位置由拖动事件驱动

        if self._squash is not None:      # 落地压缩动画进行中：物理暂停
            frames, t0 = self._squash
            # SQUASH_MS 是毫秒，monotonic 差是秒 —— 别搞混单位
            i = int((now - t0) / (SQUASH_MS / 1000.0 / (len(frames) - 1)))
            if i >= len(frames) - 1:
                self._squash = None
                self._show_face()
            else:
                self._label.config(image=frames[i])
            return

        if self._mode == "float":
            amp = self._float_amp
            if self._face == "tired":
                # 疲惫时没力气：只压低幅度，不再把用户选的「静止」档强行改活
                amp = min(amp, 3)
            if amp > 0 and self._float_period > 0:
                phase = ((now - self._start) / self._float_period) * 2.0 * math.pi
                self.y = self._base_y - amp * math.sin(phase)
            if self._face == "run":
                self._run_step(dt)
        elif self._mode == "fall":
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            self.x += self.vx * dt
            # 左右墙壁反弹
            if self.x < 0:
                self.x, self.vx = 0, -self.vx * RESTITUTION
            elif self.x > self._sw - self._win_w:
                self.x, self.vx = self._sw - self._win_w, -self.vx * RESTITUTION
            # 触地
            if self.y >= self._ground:
                self.y = self._ground
                impact = abs(self.vy)
                if self._physics_on and impact > BOUNCE_STOP_V:
                    self.vy = -impact * RESTITUTION
                    self.vx *= 0.82
                    self._play_squash(impact)
                else:
                    self.vy = 0.0
                    self.vx = 0.0
                    self._base_y = self._ground
                    self._play_squash(impact)
                    self._mode = "float"

        gx, gy = int(self.x), int(self.y)
        if (gx, gy) != self._last_geo:
            self.geometry(f"+{gx}+{gy}")
            self._last_geo = (gx, gy)
        if getattr(self, "_bubble", None) is not None:
            self._bubble.follow(gx, gy)

    def _run_step(self, dt):
        """奔跑：横向往返，速度随网速加快。

        网速不再在这里现采 —— 60fps 下每帧一次 GetIfTable2 既没意义又费
        CPU，直接复用 _measure() 每个监控节拍（1.2s）刷新的 self._net_down。
        """
        speed = NET_RUN_SPEED
        if self._net_down > 0:
            speed = NET_RUN_SPEED * (0.6 + min(3.0, self._net_down / NET_FAST))
        self.x += self._run_dir * speed * dt
        if self.x <= MARGIN_X:
            self.x, self._run_dir = MARGIN_X, 1
        elif self.x >= self._sw - self._win_w - MARGIN_X:
            self.x, self._run_dir = self._sw - self._win_w - MARGIN_X, -1

    # ============================ Q 弹压缩 ============================
    def _play_squash(self, impact=0.0):
        """落地压缩动画：冲得越狠压得越扁、弹得越久。

        基底用「当前脸」而不是永远 idle：番茄钟伴学时落地，压缩帧
        不会把捧书脸切回默认笑脸闪一下。
        """
        base = self._faces.get(self._face) or self._faces["idle"]
        frames = []
        seq = ((2, 3, 6, 5), (4, 5, 5, 4), (5, 4, 4, 5), (9, 8, 8, 9))
        if impact <= 900:
            seq = seq[:3]
        for (a, b, cc, d) in seq:
            try:
                frames.append(squash(base, a, b, cc, d))
            except tk.TclError:
                frames.append(base)
        frames.append(base)
        self._squash = (frames, time.monotonic())
        self._label.config(image=frames[0])

    # ============================ 表情 ============================
    def _show_face(self, name=None):
        photo = self._faces.get(name or self._face) or self._faces["idle"]
        try:
            self._label.config(image=photo)
        except tk.TclError:
            pass

    def _set_face(self, face):
        if face not in self._faces:
            face = "idle"
        if face != self._face:
            self._face = face
            self._show_face(face)

    def show_happy(self):
        """单击：开心；3 秒内点满 5 次：害羞。"""
        now = time.monotonic()
        self._clicks = [t for t in self._clicks if now - t < 3.0] + [now]
        if len(self._clicks) >= SHY_AFTER_CLICKS and "shy" in self._faces:
            self._clicks = []
            self._temp_until = now + SHY_MS / 1000.0
            self._set_face("shy")
            self._bubble.say("别、别摸啦，会化掉的… (害羞)", SHY_MS)
            return
        if "happy" in self._faces:
            self._temp_until = now + HAPPY_MS / 1000.0
            self._set_face("happy")
            lines = ("耶！又被摸头啦", "好舒服~", "(开心地晃触手)")
            self._bubble.say(lines[int(now) % len(lines)], HAPPY_MS)

    # ============================ 系统联动 ============================
    def _monitor_tick(self):
        if not self._alive:
            return
        try:
            self._sample()
        except tk.TclError:
            self._alive = False
            return
        except Exception:
            traceback.print_exc()
        self.after(int(MONITOR_PERIOD_S * 1000), self._monitor_tick)

    def _sample(self):
        now = time.monotonic()
        if self._squash is not None:
            return

        pomo = self._pomodoro()
        # 番茄钟结束或被手动取消：收起倒计时气泡，不再显示剩余时间。
        # 暂停中不收回——下面会把气泡换成「已暂停」提示
        if (not pomo and self._pomo_showing
                and not (getattr(self._master, "pomodoro", None) or {})
                        .get("paused")):
            self._pomo_showing = False
            if not self._celebrating:
                self._bubble.hide()
                self._sys_state = "idle"
        # 庆祝气泡到点后自动收起，回到日常状态
        if self._celebrating and now >= self._celebrate_until:
            self._celebrating = False
            self._bubble.hide()
            self._sys_state = "idle"
            self._set_face("idle")

        if self._celebrating:
            return                        # 庆祝文案期间保持气泡
        if time.monotonic() < self._temp_until:
            return                        # 开心 / 害羞等一次性表情还在播放

        if pomo:
            # pomo 是主窗口塞进来的 dict，字段缺失时给个兜底值 —— 早先这里
            # 是裸索引 pomo["minutes"]，缺键就抛 KeyError，采样链当场断掉。
            left = max(0, int(pomo.get("end", 0) - time.time()))
            m, s = divmod(left, 60)
            if pomo.get("phase") == "rest":
                # 休息阶段：倒计时 + 换开心脸，和专注阶段区分开
                self._bubble.say(f"☕ 休息 {m:02d}:{s:02d}\n"
                                 "喝口水，眺望一下远方～", 0, priority=3)
                self._set_face("happy")
            else:
                mins = pomo.get("minutes") or self._pomo_minutes()
                self._bubble.say(f"📚 番茄钟 {mins} 分钟\n"
                                 f"还剩 {m:02d}:{s:02d}，我陪你学习", 0,
                                 priority=3)
                self._set_face("study")
            self._pomo_showing = True
            return

        # 暂停中的番茄钟：气泡换成暂停提示，恢复或结束后由上面的分支接管
        raw = getattr(self._master, "pomodoro", None)
        if raw and raw.get("paused"):
            self._bubble.say("⏸ 番茄钟已暂停\n休息好了点「继续」吧～", 0,
                             priority=3)
            self._set_face("study")
            self._pomo_showing = True
            return

        if not self._monitor_on:
            self._net_down = 0.0
            self._bubble.hide()
            self._set_face("idle")
            return

        state, tip = self._measure()
        if state != self._sys_state:
            self._sys_state = state
            if tip:
                self._bubble.say(tip, 3500)
            elif state == "idle":
                self._bubble.hide()
        self._set_face(state)

    def _measure(self):
        """读系统指标 → (状态名, 气泡文案)。

        三个指标各自独立容错：CPU 采不到（首次调用只建基准，返回 None）
        不影响内存 / 网速的判断。以前 cpu=None 会在 >= 比较处抛 TypeError，
        被外层一并吞掉——三个联动一起静默失效，且没有任何提示。
        """
        from core import sysinfo
        cpu, mem, down, net_ok = None, None, 0.0, False
        try:
            cpu = sysinfo.cpu_percent()
        except Exception:
            cpu = None
        try:
            mem = sysinfo.mem_info() or {}
        except Exception:
            mem = None
        try:
            sp = sysinfo.net_speed()
            down = sp[0] if sp else 0.0
            net_ok = True
        except Exception:
            down, net_ok = 0.0, False
        self._net_down = down
        if cpu is None and mem is None and not net_ok:
            # 全部采不到：至少让用户知道联动为什么不动了
            return "idle", "😵 系统状态采不到了…\n联动先休息，我乖乖待着"
        if cpu is not None and cpu >= CPU_HOT:
            return "hot", (f"🥵 CPU {cpu:.0f}%，好热呀…\n（吐舌头散热中）")
        load = (mem or {}).get("load", 0.0)
        if load >= MEM_TIRED:
            return "tired", (f"😵 内存负载 {load:.0f}%…\n走不动了，让电脑歇歇吧")
        if down >= NET_FAST:
            return "run", (f"🏃 网速 {down / 1024:.0f} KB/s！\n脚底抹油冲鸭——")
        return "idle", None

    # ============================ 番茄钟 ============================
    def _pomodoro(self):
        """正在走表的番茄钟；暂停中或已到点的都不算。"""
        p = getattr(self._master, "pomodoro", None)
        if p and not p.get("paused") and time.time() < p.get("end", 0):
            return p
        return None

    def _pomo_minutes(self) -> int:
        """气泡里显示的专注时长：以主窗口记录的为准，拿不到就用默认设置。"""
        p = getattr(self._master, "pomodoro", None)
        for val in (p.get("minutes") if isinstance(p, dict) else None,
                    getattr(self._master, "pomo_minutes", None)):
            try:
                if val:
                    return int(val)
            except (TypeError, ValueError):
                continue
        return 45

    def _start_pomodoro(self):
        """按用户设置的默认时长开始（右键菜单）。"""
        start = getattr(self._master, "start_pomodoro", None)
        if start:
            start(getattr(self._master, "pomo_minutes", 45))

    def _custom_pomodoro(self):
        """弹出时长设置框：滚轴自定义专注 / 休息分钟数。"""
        try:
            from gui.pages import PomodoroDialog
        except Exception:
            return
        try:
            PomodoroDialog(self, self._master)
        except Exception:
            pass

    def _stop_pomodoro(self):
        stop = getattr(self._master, "stop_pomodoro", None)
        if stop:
            stop()

    def _pause_pomodoro(self):
        fn = getattr(self._master, "pause_or_resume_pomodoro", None)
        if fn:
            fn()

    def on_pomodoro_end(self, kind="stop", minutes=0, break_minutes=0):
        """番茄钟结束 / 被取消：立刻收起头顶的倒计时。

        kind="done" 时先播一句庆祝（8 秒），之后同样不再显示剩余时间。
        """
        self._pomo_showing = False
        if kind == "done":
            rest = break_minutes or getattr(self._master, "pomo_break", 5)
            try:
                # priority=2：庆祝期间不被状态提示（priority=1）抢位，
                # 但下一秒的同优先级刷新仍会正常更新
                self._bubble.say(f"🍅 {minutes} 分钟专注完成！\n"
                                 f"休息 {rest} 分钟吧～", 8000, priority=2)
            except Exception:
                pass
            self._celebrating = True
            self._celebrate_until = time.monotonic() + 8.0
            self._sys_state = "idle"
            if "happy" in self._faces:
                self._set_face("happy")
            else:
                self._set_face("idle")
            return
        self._celebrating = False
        self._bubble.hide()
        self._sys_state = "idle"
        if time.monotonic() >= self._temp_until:
            self._set_face("idle")

    # ============================ 拖动 / 抛出 ============================
    def _on_press(self, e):
        self._mode = "drag"
        self._squash = None
        self._dragging = (e.x_root, e.y_root,
                          self.winfo_rootx(), self.winfo_rooty())
        self._hist = [(time.monotonic(), e.x_root, e.y_root)]
        if "happy" in self._faces:
            self._show_face("happy")      # 被抓起来的瞬间会"笑"

    def _on_move(self, e):
        if not self._dragging:
            return
        gx, gy, ox, oy = self._dragging
        self.x = ox + (e.x_root - gx)
        self.y = oy + (e.y_root - gy)
        self.geometry(f"+{int(self.x)}+{int(self.y)}")
        self._last_geo = (int(self.x), int(self.y))
        if getattr(self, "_bubble", None) is not None:
            self._bubble.follow(int(self.x), int(self.y))
        now = time.monotonic()
        self._hist.append((now, e.x_root, e.y_root))
        if len(self._hist) > 6:
            self._hist.pop(0)

    def _on_release(self, e):
        if not self._dragging:
            return
        gx, gy = self._dragging[0], self._dragging[1]
        self._dragging = None
        moved = abs(e.x_root - gx) + abs(e.y_root - gy)
        if moved < 6:                       # 没怎么动 = 单击 → 摸头互动
            self.show_happy()
            self._mode = "float"
            self._base_y = self.y
            self.vx = self.vy = 0.0
            return
        # 抛出：用最近几次位移的指数平均作为初速度
        vx = vy = 0.0
        for (t0, x0, y0), (t1, x1, y1) in zip(self._hist, self._hist[1:]):
            dt = max(0.008, t1 - t0)
            vx += ((x1 - x0) / dt - vx) * DRAG_SMOOTH
            vy += ((y1 - y0) / dt - vy) * DRAG_SMOOTH
        if self._physics_on:
            self.vx = max(-MAX_LAUNCH, min(MAX_LAUNCH, vx))
            self.vy = max(-MAX_LAUNCH, min(MAX_LAUNCH, vy))
            self._mode = "fall" if (self.vy < -40 or abs(self.vx) > 60 or
                                    self.y < self._ground) else "float"
            if self._mode == "float":
                self._base_y = self.y
        else:
            self._mode = "float"
            self._base_y = self.y
        self._show_face()

    # ============================ 菜单 / 设置 ============================
    def _build_menu(self):
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="🍅 开始番茄钟",
                               command=self._start_pomodoro)
        # 记下番茄钟那一项的位置：右键时要按当前状态改写它的文字
        # （早先写死 entryconfig(0)，菜单一加项就会改错地方）
        self._pomo_item = self._menu.index("end")
        self._menu.add_command(label="⏱ 自定义番茄钟时长…",
                               command=self._custom_pomodoro)
        self._menu.add_command(label="⏸ 暂停 / 继续番茄钟",
                               command=self._pause_pomodoro)
        self._menu.add_command(label="⏹ 结束番茄钟",
                               command=self._stop_pomodoro)
        self._menu.add_separator()
        self._menu.add_command(label="物理引擎：开/关",
                               command=self._toggle_physics)
        self._menu.add_command(label="系统联动：开/关",
                               command=self._toggle_monitor)
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
        # 菜单项文字跟随用户设置的时长
        try:
            mins = getattr(self._master, "pomo_minutes", 45)
            running = bool(getattr(self._master, "pomodoro", None))
            self._menu.entryconfig(self._pomo_item,
                                   label=("⏹ 番茄钟进行中…" if running
                                          else f"🍅 开始番茄钟（{mins} 分钟）"))
        except (tk.TclError, AttributeError):
            pass
        self._menu.tk_popup(e.x_root, e.y_root)

    def _cfg_set(self, key, val):
        cfg = getattr(self._master, "cfg", None)
        if cfg is not None:
            cfg.set_setting(key, val)

    def _toggle_physics(self):
        self._physics_on = not self._physics_on
        self._cfg_set("pet_physics", self._physics_on)
        self._bubble.say("重力已" + ("恢复！" if self._physics_on else "关闭~"),
                         2500)

    def _toggle_monitor(self):
        self._monitor_on = not self._monitor_on
        self._cfg_set("pet_monitor", self._monitor_on)
        self._bubble.say("系统联动已" + ("开启" if self._monitor_on else "关闭"),
                         2500)

    def set_speed(self, period, amplitude, remember=True):
        """运行时改浮动速度：period 越大越慢，amplitude 是上下各多少像素。

        remember=True 时写进 config.json，下次召唤墨墨还是这个节奏。

        参数存在实例上（早先写的是模块级全局，会带到下一次召唤，而且两个
        墨墨会互相干扰）。
        """
        self._float_period = float(period)
        self._float_amp = float(amplitude)
        self._start = time.monotonic()
        if remember:
            self._cfg_set("pet_float_period", period)
            self._cfg_set("pet_float_amplitude", amplitude)

    def set_full_through(self, enabled):
        self._full_through = enabled
        set_full_through(self._hwnd, enabled)
        if getattr(self, "_bubble", None) is not None:
            set_full_through(hwnd_of(self._bubble), enabled)

    def _bubble_colors(self):
        """气泡配色：跟随主窗口主题。"""
        cfg = getattr(self._master, "cfg", None)
        theme = cfg.get_setting("theme", "light") if cfg else "light"
        try:
            from gui.theme import THEMES
            c = THEMES.get(theme, THEMES["light"])
            return {"text": c["text"],
                    "bubble_bg": c.get("menu_bg", "#ffffff"),
                    "bubble_outline": c.get("divider", "#c8c8c8")}
        except Exception:
            return {"text": "#222222", "bubble_bg": "#ffffff",
                    "bubble_outline": "#c8c8c8"}

    def on_close(self):
        """收起桌宠（通知主窗口同步按钮状态）。"""
        self._alive = False
        try:
            self._bubble.destroy()
        except Exception:
            pass
        try:
            cb = getattr(self._master, "_on_pet_closed", None)
            if cb:
                cb()
        except Exception:
            pass
        self.destroy()

    # ---------- 兜底章鱼 ----------
    def _fallback_photo(self):
        size = self._size
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
