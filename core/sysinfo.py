# -*- coding: utf-8 -*-
"""系统监控数据采集：CPU 占用率、物理内存、网络速率（Windows，纯标准库）。

实现说明（不用 psutil，只用 ctypes 调 Win32）：
    1. CPU：GetSystemTimes 取 idle / kernel / user 累计时间，两次采样求差；
       kernel 时间本身包含 idle，故 占用率 = (Δkernel + Δuser - Δidle) / (Δkernel + Δuser)
    2. 内存：GlobalMemoryStatusEx 取总物理内存、可用物理内存与内存负载
    3. 网速：iphlpapi.GetIfTable 取各网卡累计收发字节数，两次采样求差 / 间隔；
       计数器是 32 位会回绕，差值为负时补 2^32

首次调用只建立基准（返回 None），之后每次调用返回与上一次采样之间的速率。
"""
import ctypes
import os
import time
from ctypes import wintypes

_WIN = (os.name == "nt")

if _WIN:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        def __init__(self):
            self.dwLength = ctypes.sizeof(self)
            super().__init__()

    # ---- GetIfTable 用到的结构 ----
    IF_TYPE_SOFTWARE_LOOPBACK = 24
    IF_OPER_STATUS_UP = 1
    MAX_IF = 64

    class MIB_IFROW(ctypes.Structure):
        _fields_ = [
            ("wszName", ctypes.c_wchar * 256),
            ("dwIndex", wintypes.DWORD),
            ("dwType", wintypes.DWORD),
            ("dwMtu", wintypes.DWORD),
            ("dwSpeed", wintypes.DWORD),
            ("dwPhysAddrLen", wintypes.DWORD),
            ("bPhysAddr", ctypes.c_ubyte * 8),
            ("dwAdminStatus", wintypes.DWORD),
            ("dwOperStatus", wintypes.DWORD),
            ("dwInOctets", wintypes.DWORD),
            ("dwInUcastPkts", wintypes.DWORD),
            ("dwInNUcastPkts", wintypes.DWORD),
            ("dwInDiscards", wintypes.DWORD),
            ("dwInErrors", wintypes.DWORD),
            ("dwInUnknownProtos", wintypes.DWORD),
            ("dwOutOctets", wintypes.DWORD),
            ("dwOutUcastPkts", wintypes.DWORD),
            ("dwOutNUcastPkts", wintypes.DWORD),
            ("dwOutDiscards", wintypes.DWORD),
            ("dwOutErrors", wintypes.DWORD),
            ("dwOutQLen", wintypes.DWORD),
            ("dwDescrLen", wintypes.DWORD),
            # 实测 sizeof(MIB_IFROW) = 860（bDescr 在 SDK 中按 260 字节对齐），
            # 若写成 256 会让 ctypes 算出 856，导致 table[] 步长错位、从第二个
            # 网卡开始全部解析成垃圾。
            ("bDescr", ctypes.c_ubyte * 260),
        ]

    class MIB_IFTABLE(ctypes.Structure):
        _fields_ = [("dwNumEntries", wintypes.DWORD),
                    ("table", MIB_IFROW * MAX_IF)]


def _ft_value(ft) -> int:
    """FILETIME -> 64 位整数。"""
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


# ---------------- CPU ----------------
_cpu_state = {"idle": 0, "kernel": 0, "user": 0}


def cpu_percent():
    """CPU 占用率（0~100）；首次调用只建立基准，返回 None。"""
    if not _WIN:
        return None
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not _kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                                    ctypes.byref(user)):
        return None
    i, k, u = _ft_value(idle), _ft_value(kernel), _ft_value(user)
    st = _cpu_state
    if st["idle"] == 0:                     # 第一次：只记录基准
        st.update(idle=i, kernel=k, user=u)
        return None
    d_idle, d_kernel, d_user = i - st["idle"], k - st["kernel"], u - st["user"]
    st.update(idle=i, kernel=k, user=u)
    total = d_kernel + d_user
    if total <= 0:
        return 0.0
    busy = max(0, total - d_idle)
    return max(0.0, min(100.0, busy / total * 100.0))


def cpu_count():
    """逻辑处理器数量。"""
    return os.cpu_count() or 1


# ---------------- 内存 ----------------
def mem_info():
    """物理内存：总量 / 可用 / 已用 / 负载百分比。"""
    if not _WIN:
        return None
    ms = MEMORYSTATUSEX()
    if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        return None
    total, avail = ms.ullTotalPhys, ms.ullAvailPhys
    return {"total": total, "avail": avail,
            "used": max(0, total - avail),
            "load": ms.dwMemoryLoad}


# ---------------- 网络 ----------------
def _if_rows():
    """取网卡列表（失败返回空列表）。"""
    if not _WIN:
        return []
    size = wintypes.DWORD(ctypes.sizeof(MIB_IFTABLE))
    tbl = MIB_IFTABLE()
    res = _iphlpapi.GetIfTable(ctypes.byref(tbl), ctypes.byref(size), True)
    if res == 0:
        n = min(tbl.dwNumEntries, MAX_IF)
        return list(tbl.table)[:n]
    if size.value > ctypes.sizeof(MIB_IFTABLE):     # 接口数超过预分配
        buf = ctypes.create_string_buffer(size.value)
        size2 = wintypes.DWORD(size.value)
        if _iphlpapi.GetIfTable(buf, ctypes.byref(size2), True) != 0:
            return []
        n = min(wintypes.DWORD.from_buffer(buf, 0).value, MAX_IF)
        rows = (MIB_IFROW * n).from_buffer(buf, 4)
        return list(rows)[:n]
    return []


def net_counters():
    """网卡累计收发字节数 -> (接收, 发送)，排除回环接口。

    优先只统计「已连接」的网卡；若一个已连接的都没有（虚拟机 / 无网络环境），
    退化为统计全部非回环网卡，避免永远显示 0。
    """
    rows = [r for r in _if_rows()
            if r.dwIndex and r.dwType != IF_TYPE_SOFTWARE_LOOPBACK]
    up = [r for r in rows if r.dwOperStatus == IF_OPER_STATUS_UP]
    use = up if up else rows
    return sum(r.dwInOctets for r in use), sum(r.dwOutOctets for r in use)


def _delta(cur: int, prev: int) -> int:
    """32 位计数器回绕处理。"""
    d = cur - prev
    if d < 0:
        d += 2 ** 32
    return max(0, d)


_net_state = {"t": 0.0, "rx": 0, "tx": 0}


def net_speed():
    """网速（字节/秒）-> (下载, 上传)；首次调用只建立基准，返回 None。"""
    if not _WIN:
        return None
    now = time.perf_counter()
    rx, tx = net_counters()
    st = _net_state
    if st["t"] == 0.0:
        st["t"], st["rx"], st["tx"] = now, rx, tx
        return None
    dt = now - st["t"]
    if dt <= 0:
        return None
    down = _delta(rx, st["rx"]) / dt
    up = _delta(tx, st["tx"]) / dt
    st["t"], st["rx"], st["tx"] = now, rx, tx
    return down, up


def prime():
    """建立采样基准（页面启动时调用一次，之后第一次刷新就有真实值）。"""
    cpu_percent()
    net_speed()


# ---------------- 格式化 ----------------
def fmt_bytes(n) -> str:
    """字节数 -> 人类可读（1024 进制）。"""
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_speed(bps) -> str:
    """字节/秒 -> "1.2 MB/s" 形式。"""
    if bps is None:
        return "—"
    return fmt_bytes(bps) + "/s"
