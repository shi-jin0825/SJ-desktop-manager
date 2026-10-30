# -*- coding: utf-8 -*-
"""图标提取模块：获取文件/文件夹/快捷方式在系统中的真实图标。

实现说明（Windows，纯标准库）：
    1. 优先走 Shell 的 IShellItemImageFactory（SHCreateItemFromParsingName +
       GetImage(SIIGBF_ICONONLY)），能正确解析 .lnk 快捷方式（含 Steam/UWP 应用）
       的目标图标，直接返回带 alpha 的 32 位 HBITMAP；
    2. 失败时回退 SHGetFileInfoW + DrawIconEx；
    3. 像素（BGRA）用 zlib + struct 编码为 PNG，交给 tkinter 的 PhotoImage
       显示（Tk 8.6 原生支持 PNG），全程无需 Pillow。

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
FILE_ATTRIBUTE_NORMAL = 0x000000080
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


def _png_from_bgra(buf: bytes, w: int, h: int) -> bytes:
    """把 BGRA 像素流编码为 RGBA 的 PNG（Windows 位图是 BGRA，需交换 R/B 通道）。"""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        row = buf[y * stride:(y + 1) * stride]
        raw.append(0)  # filter type 0
        for x in range(w):
            b, g, r, a = row[x * 4:x * 4 + 4]
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body +
                struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _hbitmap_to_png(hbmp, ) -> bytes:
    """把 32 位 HBITMAP 转成 PNG 字节。"""
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
    return _png_from_bgra(buf.raw[:w * h * 4], w, h)


def _icon_via_factory(path: str, size: int):
    """IShellItemImageFactory::GetImage —— 解析快捷方式最可靠。"""
    _ensure_com()
    p = ctypes.c_void_p()
    hr = _SHCreateItemFromParsingName(str(path), None,
                                      ctypes.byref(_IID_IShellItemImageFactory),
                                      ctypes.byref(p))
    if hr != 0 or not p.value:
        return None
    try:
        # vtable: [0]QueryInterface [1]AddRef [2]Release [3]GetImage
        vtbl = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p)).contents,
                           ctypes.POINTER(ctypes.c_void_p))
        GetImage = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, _SIZE, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p))(vtbl[3])
        hbmp = ctypes.c_void_p()
        hr = GetImage(p, _SIZE(size, size), SIIGBF_ICONONLY, ctypes.byref(hbmp))
        if hr != 0 or not hbmp.value:
            return None
        try:
            return _hbitmap_to_png(hbmp)
        finally:
            _gdi32.DeleteObject(hbmp)
    finally:
        Release = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[2])
        Release(p)


def _hicon_to_png(hicon, size: int):
    """SHGetFileInfo 路线：把 HICON 绘制到 32 位 DIB 再转 PNG（回退方案）。"""
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
        return None
    old = _gdi32.SelectObject(memdc, bmp)
    ctypes.memset(bits, 0, size * size * 4)   # 透明底
    ok = _user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
    png = None
    if ok:
        png = _png_from_bgra(ctypes.string_at(bits, size * size * 4), size, size)
    _gdi32.SelectObject(memdc, old)
    _gdi32.DeleteObject(bmp)
    _gdi32.DeleteDC(memdc)
    _user32.ReleaseDC(0, hdc)
    return png


def _icon_via_shgetfileinfo(path: str, attrs: int, size: int):
    """回退方案：SHGetFileInfoW 取 HICON。attrs 非 0 时启用 USEFILEATTRIBUTES。"""
    sfi = SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_LARGEICON
    if attrs:
        flags |= SHGFI_USEFILEATTRIBUTES
    res = _shell32.SHGetFileInfoW(path, attrs, ctypes.byref(sfi),
                                  ctypes.sizeof(SHFILEINFOW), flags)
    if not res or not sfi.hIcon:
        return None
    try:
        return _hicon_to_png(sfi.hIcon, size)
    finally:
        _user32.DestroyIcon(sfi.hIcon)


_CACHE = {}


def icon_png(path: str, size: int = 48):
    """取某个路径的真实图标 PNG 字节；取不到返回 None。"""
    if not _WIN:
        return None
    key = (os.path.abspath(path).lower(), size)
    if key in _CACHE:
        return _CACHE[key]
    png = None
    try:
        png = _icon_via_factory(path, size)
        if png is None:
            png = _icon_via_shgetfileinfo(str(path), 0, min(size, 32))
    except Exception:
        png = None
    _CACHE[key] = png
    return png


def folder_icon_png(size: int = 48):
    """取系统文件夹图标 PNG 字节（用于分类文件夹磁贴）。"""
    if not _WIN:
        return None
    key = ("<folder>", size)
    if key in _CACHE:
        return _CACHE[key]
    png = None
    try:
        # 用一个真实存在的目录取文件夹图标
        png = _icon_via_factory(os.path.expanduser("~"), size)
        if png is None:
            png = _icon_via_shgetfileinfo("folder", FILE_ATTRIBUTE_DIRECTORY, 32)
    except Exception:
        png = None
    _CACHE[key] = png
    return png


def clear_cache():
    _CACHE.clear()
