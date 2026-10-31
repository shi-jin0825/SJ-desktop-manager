# -*- coding: utf-8 -*-
"""全局热键（Windows）：RegisterHotKey + PeekMessage 轮询，零第三方依赖。

为什么不用 keyboard / pywin32：本项目只依赖标准库。这里直接用 ctypes
调用 Win32：
  · RegisterHotKey 注册系统级热键（窗口隐藏时也能触发）
  · Tk 有自己的消息循环，我们不能用 PeekMessage 乱取消息，否则会把 Tk 的
    事件吃掉；所以每次只按 WM_HOTKEY 过滤取出（PM_REMOVE），其它消息不动。

非 Windows 平台上所有方法都是空操作（返回 False），保证程序不崩。
"""
import ctypes
import sys

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000          # 按住不放不重复触发

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
HOTKEY_ID = 0xCAFE             # 本程序使用的热键 id

_IS_WIN = (sys.platform == "win32")

_VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home",
    0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
    0x2C: "PrtSc", 0x2D: "Ins", 0x2E: "Del",
    0x5B: "Win", 0x5C: "Win", 0x5D: "Menu",
    0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}


def vk_name(vk: int) -> str:
    """虚拟键码 -> 可读名字（Ctrl+Alt+M 里的那个 M）。"""
    vk = int(vk or 0)
    if 65 <= vk <= 90:          # A ~ Z
        return chr(vk)
    if 48 <= vk <= 57:          # 0 ~ 9
        return chr(vk)
    if 96 <= vk <= 105:         # 小键盘
        return "Num" + str(vk - 96)
    if 112 <= vk <= 135:        # F1 ~ F24
        return "F" + str(vk - 111)
    return _VK_NAMES.get(vk, "VK%X" % vk)


def combo_text(mod: int, vk: int) -> str:
    """把 (修饰键, 键码) 拼成 "Ctrl+Alt+M"。"""
    parts = []
    for bit, name in ((MOD_WIN, "Win"), (MOD_CONTROL, "Ctrl"),
                      (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift")):
        if mod & bit:
            parts.append(name)
    parts.append(vk_name(vk))
    return "+".join(parts) if vk else ""


# 默认热键，以及和其它程序冲突时依次尝试的备用组合
DEFAULT_HOTKEY = (MOD_CONTROL | MOD_ALT, ord("M"))
HOTKEY_FALLBACKS = (
    DEFAULT_HOTKEY,
    (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("M")),
    (MOD_CONTROL | MOD_ALT, ord("K")),
    (MOD_CONTROL | MOD_SHIFT, ord("M")),
    (MOD_CONTROL | MOD_ALT, ord("D")),
)


if _IS_WIN:
    from ctypes import wintypes

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt", wintypes.POINT),
                    ("lPrivate", wintypes.DWORD)]

    _u = ctypes.windll.user32
    _u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                  wintypes.UINT, wintypes.UINT]
    _u.RegisterHotKey.restype = wintypes.BOOL
    _u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.UnregisterHotKey.restype = wintypes.BOOL
    _u.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _u.PeekMessageW.restype = wintypes.BOOL


class GlobalHotkey:
    """一个全局热键：注册后在主循环里定时 poll() 即可。"""

    def __init__(self, hwnd=None):
        self.hwnd = hwnd
        self.mod = 0
        self.vk = 0
        self.registered = False
        self.error = ""

    def register(self, mod: int, vk: int, hwnd=None) -> bool:
        if hwnd:
            self.hwnd = hwnd
        self.unregister()
        self.mod, self.vk = int(mod or 0), int(vk or 0)
        if not _IS_WIN or self.hwnd is None or not self.mod or not self.vk:
            self.error = "" if (_IS_WIN and self.mod and self.vk) else "参数不完整"
            return False
        try:
            ok = _u.RegisterHotKey(wintypes.HWND(int(self.hwnd)), HOTKEY_ID,
                                   self.mod | MOD_NOREPEAT, self.vk)
        except Exception as e:      # 极少数环境没有该 API
            self.error = str(e)
            return False
        self.registered = bool(ok)
        self.error = "" if ok else "可能被其它程序占用"
        return self.registered

    def unregister(self):
        if self.registered and _IS_WIN and self.hwnd is not None:
            try:
                _u.UnregisterHotKey(wintypes.HWND(int(self.hwnd)), HOTKEY_ID)
            except Exception:
                pass
        self.registered = False

    def poll(self) -> bool:
        """取一次热键消息（只取 WM_HOTKEY，不动 Tk 的其它消息）。"""
        if not self.registered or not _IS_WIN:
            return False
        hit = False
        try:
            msg = MSG()
            while _u.PeekMessageW(ctypes.byref(msg), None,
                                  WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                    hit = True
        except Exception:
            return False
        return hit

    def text(self) -> str:
        return combo_text(self.mod, self.vk)
