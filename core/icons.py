# -*- coding: utf-8 -*-
"""图标提取模块：获取文件/文件夹/快捷方式在系统中的真实图标。

实现说明（Windows，纯标准库）：
    1. 优先走 Shell 的 IShellItemImageFactory（SHCreateItemFromParsingName +
       GetImage(SIIGBF_ICONONLY)），能正确解析 .lnk 快捷方式（含 Steam/UWP 应用）
       的目标图标，直接返回带 alpha 的 32 位 HBITMAP；
    2. 失败时回退 SHGetFileInfoW + DrawIconEx；
    3. 像素统一转成 RGBA，可输出 PNG（zlib + struct 编码）供 tkinter 显示，
       也可取原始像素用于合成自定义图标（如 .ico 生成）。

非 Windows 平台返回 None，GUI 回退到 emoji。
"""
import ctypes
import os
import struct
import zlib

try:
    from ctypes import wintypes
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _WIN = True
except (ImportError, OSError, AttributeError):  # pragma: no cover
    _WIN = False

# ---- Win32 常量 ----
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_DIRECTORY = 0x000000010
DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0
SIIGBF_ICONONLY = 0x4
COINIT_APARTMENTTHREADED = 0x2

_IID_IShellItemImageFactory = None
if _WIN:
    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    _IID_IShellItemImageFactory = _GUID(
        0xBCC18B79, 0xBA16, 0x442F,
        (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ("hIcon", wintypes.HICON),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", wintypes.DWORD),
            ("szDisplayName", wintypes.WCHAR * 260),
            ("szTypeName", wintypes.WCHAR * 80),
        ]

    class _BMIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BMI(ctypes.Structure):
        _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wintypes.DWORD * 3)]

    class _SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    _SHCreateItemFromParsingName = _shell32.SHCreateItemFromParsingName
    _SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p)]

_COM_INITED = False


def _ensure_com():
    """在当前线程初始化 COM（SHCreateItemFromParsingName 前置条件）。"""
    global _COM_INITED
    if not _COM_INITED:
        _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        _COM_INITED = True


# ---------------- 像素编码 ----------------
def png_from_rgba(buf: bytes, w: int, h: int) -> bytes:
    """把 RGBA 像素流编码为 PNG。"""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0
        raw += buf[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body +
                struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _bgra_to_rgba(buf: bytes) -> bytes:
    """Windows 位图是 BGRA，交换 R/B 通道得到 RGBA。"""
    out = bytearray(len(buf))
    for i in range(0, len(buf), 4):
        b, g, r, a = buf[i:i + 4]
        out[i:i + 4] = bytes((r, g, b, a))
    return bytes(out)


# ---------------- 原始像素提取 ----------------
def _bitmap_bgra(hbmp):
    """32 位 HBITMAP -> (w, h, BGRA bytes)；失败返回 None。"""
    class _BM(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                    ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                    ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort),
                    ("bmBits", ctypes.c_void_p)]
    bm = _BM()
    if not _gdi32.GetObjectW(hbmp, ctypes.sizeof(_BM), ctypes.byref(bm)):
        return None
    w, h = bm.bmWidth, bm.bmHeight
    if not w or not h:
        return None
    bmi = _BMI()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h   # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = _user32.GetDC(0)
    _gdi32.GetDIBits(hdc, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    _user32.ReleaseDC(0, hdc)
    return w, h, buf.raw[:w * h * 4]


def _rgba_via_factory(path: str, size: int):
    """IShellItemImageFactory::GetImage —— 解析快捷方式最可靠。"""
    _ensure_com()
    p = ctypes.c_void_p()
    hr = _SHCreateItemFromParsingName(str(path), None,
                                      ctypes.byref(_IID_IShellItemImageFactory),
                                      ctypes.byref(p))
    if hr != 0 or not p.value:
        return None
    vtbl = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p)).contents,
                       ctypes.POINTER(ctypes.c_void_p))
    try:
        # vtable: [0]QueryInterface [1]AddRef [2]Release [3]GetImage
        GetImage = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, _SIZE, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p))(vtbl[3])
        hbmp = ctypes.c_void_p()
        hr = GetImage(p, _SIZE(size, size), SIIGBF_ICONONLY, ctypes.byref(hbmp))
        if hr != 0 or not hbmp.value:
            return None
        try:
            got = _bitmap_bgra(hbmp)
            if not got:
                return None
            w, h, bgra = got
            return w, h, _bgra_to_rgba(bgra)
        finally:
            _gdi32.DeleteObject(hbmp)
    finally:
        Release = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[2])
        Release(p)


def _rgba_via_shgetfileinfo(path: str, attrs: int, size: int):
    """回退方案：SHGetFileInfoW 取 HICON 后画到 32 位 DIB。"""
    sfi = SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_LARGEICON
    if attrs:
        flags |= SHGFI_USEFILEATTRIBUTES
    res = _shell32.SHGetFileInfoW(path, attrs, ctypes.byref(sfi),
                                  ctypes.sizeof(SHFILEINFOW), flags)
    if not res or not sfi.hIcon:
        return None
    hdc = _user32.GetDC(0)
    memdc = _gdi32.CreateCompatibleDC(hdc)
    bmi = _BMI()
    hdr = bmi.bmiHeader
    hdr.biSize = ctypes.sizeof(_BMIH)
    hdr.biWidth = size
    hdr.biHeight = -size          # top-down
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = DIB_RGB_COLORS
    bits = ctypes.c_void_p()
    bmp = _gdi32.CreateDIBSection(memdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                  ctypes.byref(bits), None, 0)
    if not bmp or not bits:
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(0, hdc)
        _user32.DestroyIcon(sfi.hIcon)
        return None
    try:
        _gdi32.SelectObject(memdc, bmp)
        ctypes.memset(bits, 0, size * size * 4)   # 透明底
        ok = _user32.DrawIconEx(memdc, 0, 0, sfi.hIcon, size, size, 0, None, DI_NORMAL)
        if not ok:
            return None
        return size, size, _bgra_to_rgba(ctypes.string_at(bits, size * size * 4))
    finally:
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(0, hdc)
        _user32.DestroyIcon(sfi.hIcon)


_PNG_CACHE = {}
_RGBA_CACHE = {}

# 缓存上限：桌面项极多时不让内存只增不减（超出后丢掉最早用过的那批）
CACHE_LIMIT = 400


def _bump(cache, key, value):
    """写入缓存并在超限时做 LRU 淘汰（dict 保持插入顺序）。"""
    cache.pop(key, None)          # 重新插入到末尾 = 最近使用
    cache[key] = value
    over = len(cache) - CACHE_LIMIT
    if over > 0:
        for k in list(cache)[:over]:
            del cache[k]
    return value


def cache_sizes():
    """当前缓存条目数（调试 / 自检用）。"""
    return {"png": len(_PNG_CACHE), "rgba": len(_RGBA_CACHE)}


def icon_rgba(path: str, size: int = 48):
    """取图标原始像素，返回 (w, h, RGBA bytes)；失败返回 None。"""
    if not _WIN:
        return None
    key = (os.path.abspath(path).lower(), size)
    if key in _RGBA_CACHE:
        got = _RGBA_CACHE.pop(key)      # 命中就挪到末尾（LRU）
        _RGBA_CACHE[key] = got
        return got
    got = None
    try:
        got = _rgba_via_factory(path, size)
        if got is None:
            got = _rgba_via_shgetfileinfo(str(path), 0, min(size, 32))
    except Exception:
        got = None
    _bump(_RGBA_CACHE, key, got)
    return got


def icon_png(path: str, size: int = 48):
    """取某个路径的真实图标 PNG 字节；取不到返回 None。"""
    if not _WIN:
        return None
    key = (os.path.abspath(path).lower(), size)
    if key in _PNG_CACHE:
        png = _PNG_CACHE.pop(key)
        _PNG_CACHE[key] = png
        return png
    got = icon_rgba(path, size)
    return _bump(_PNG_CACHE, key,
                 png_from_rgba(got[2], got[0], got[1]) if got else None)


def folder_icon_png(size: int = 48):
    """取系统文件夹图标 PNG 字节（用于分类文件夹磁贴）。"""
    if not _WIN:
        return None
    key = ("<folder>", size)
    if key in _PNG_CACHE:
        return _PNG_CACHE[key]
    got = None
    try:
        got = icon_rgba(os.path.expanduser("~"), size)
        if got is None:
            got = _rgba_via_shgetfileinfo("folder", FILE_ATTRIBUTE_DIRECTORY, 32)
    except Exception:
        got = None
    return _bump(_PNG_CACHE, key,
                 png_from_rgba(got[2], got[0], got[1]) if got else None)


def clear_cache():
    _PNG_CACHE.clear()
    _RGBA_CACHE.clear()
