# -*- coding: utf-8 -*-
"""系统监控数据采集：CPU 占用率、物理内存、网络速率（Windows，纯标准库）。

实现说明（不用 psutil，只用 ctypes 调 Win32）：
    1. CPU：GetSystemTimes 取 idle / kernel / user 累计时间，两次采样求差；
       kernel 时间本身包含 idle，故 占用率 = (Δkernel + Δuser - Δidle) / (Δkernel + Δuser)
    2. 内存：GlobalMemoryStatusEx 取总物理内存、可用物理内存与内存负载
    3. 网速：iphlpapi.GetIfTable2 取各网卡累计收发字节数（64 位），两次采样求差 / 间隔。

    注意：旧接口 GetIfTable（MIB_IFROW，32 位计数）在现代 Windows 上经常对
    Wi-Fi / 以太网返回全 0（驱动不再维护那份老统计），所以必须优先用
    GetIfTable2；只有在极老系统（XP/2003）上才回退到 GetIfTable。

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

    # ---- GetIfTable2 用到的结构（64 位计数，Vista+）----
    IF_TYPE_SOFTWARE_LOOPBACK = 24
    IF_TYPE_TUNNEL = 131
    IF_OPER_STATUS_UP = 1
    IF_OPER_STATUS_CONNECTED = 1
    # InterfaceAndOperStatusFlags 位域：bit0 硬件接口 / bit1 过滤接口
    FLAG_HARDWARE = 0x01
    FLAG_FILTER = 0x02

    class MIB_IF_ROW2(ctypes.Structure):
        """网卡信息行。

        真实 sizeof = 1352（实测：相邻两行网卡名在缓冲区中的间隔）。若按 SDK
        文档写成 1336，table[] 步长就会错位，从第二块网卡起全是垃圾数据。

        另外实测确认的字段偏移（相对行首）：
            Alias 28 / Description 542 / Mtu 1124 / Type 1128 / OperStatus 1156
            TransmitLinkSpeed 1192 / ReceiveLinkSpeed 1200
            InOctets 1208 / OutOctets 1280
        因此 In 系列后面有一个保留的 8 字节字段，Out 系列后面同样补一个，
        最终正好 1352 字节。
        """
        _fields_ = [
            ("InterfaceLuid", ctypes.c_ulonglong),
            ("InterfaceIndex", wintypes.DWORD),
            ("InterfaceGuid", ctypes.c_ubyte * 16),
            ("Alias", ctypes.c_wchar * 257),
            ("Description", ctypes.c_wchar * 257),
            ("PhysicalAddressLength", wintypes.DWORD),
            ("PhysicalAddress", ctypes.c_ubyte * 32),
            ("PermanentPhysicalAddress", ctypes.c_ubyte * 32),
            ("Mtu", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TunnelType", wintypes.DWORD),
            ("MediaType", wintypes.DWORD),
            ("PhysicalMediumType", wintypes.DWORD),
            ("AccessType", wintypes.DWORD),
            ("DirectionType", wintypes.DWORD),
            ("Flags", ctypes.c_ubyte),          # 位域实际只占 1 字节
            ("OperStatus", wintypes.DWORD),
            ("AdminStatus", wintypes.DWORD),
            ("MediaConnectState", wintypes.DWORD),
            ("NetworkGuid", ctypes.c_ubyte * 16),
            ("ConnectionType", wintypes.DWORD),
            ("TransmitLinkSpeed", ctypes.c_ulonglong),
            ("ReceiveLinkSpeed", ctypes.c_ulonglong),
            ("InOctets", ctypes.c_ulonglong),
            ("InUcastPkts", ctypes.c_ulonglong),
            ("InNUcastPkts", ctypes.c_ulonglong),
            ("InDiscards", ctypes.c_ulonglong),
            ("InErrors", ctypes.c_ulonglong),
            ("InUnknownProtos", ctypes.c_ulonglong),
            ("InMulticastPkts", ctypes.c_ulonglong),
            ("InBroadcastPkts", ctypes.c_ulonglong),
            ("_rsv_in", ctypes.c_ulonglong),
            ("OutOctets", ctypes.c_ulonglong),
            ("OutUcastPkts", ctypes.c_ulonglong),
            ("OutNUcastPkts", ctypes.c_ulonglong),
            ("OutDiscards", ctypes.c_ulonglong),
            ("OutErrors", ctypes.c_ulonglong),
            ("OutMulticastPkts", ctypes.c_ulonglong),
            ("OutBroadcastPkts", ctypes.c_ulonglong),
            ("OutQLen", ctypes.c_ulonglong),
            ("_rsv_out", ctypes.c_ulonglong),
        ]

    class MIB_IF_TABLE2(ctypes.Structure):
        _fields_ = [("NumEntries", wintypes.DWORD),
                    ("Table", MIB_IF_ROW2 * 1)]

    # ---- GetIfTable（旧 32 位，仅作回退）----
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
            # 若写成 256 会让 ctypes 算出 856，导致 table[] 步长错位。
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
def _if_rows2():
    """GetIfTable2 取网卡列表（失败返回空列表）。

    Windows 自己分配内存，用完后必须 FreeMibTable 释放。
    """
    if not _WIN:
        return []
    try:
        p_tbl = ctypes.POINTER(MIB_IF_TABLE2)
        _iphlpapi.GetIfTable2.argtypes = [ctypes.POINTER(p_tbl)]
        _iphlpapi.GetIfTable2.restype = wintypes.DWORD
        _iphlpapi.FreeMibTable.argtypes = [ctypes.c_void_p]
    except AttributeError:          # 极老系统没有这两个函数
        return []
    tbl = p_tbl()
    if _iphlpapi.GetIfTable2(ctypes.byref(tbl)) != 0:
        return []
    try:
        n = tbl.contents.NumEntries
        if n <= 0:
            return []
        arr = (MIB_IF_ROW2 * n).from_address(
            ctypes.addressof(tbl.contents.Table))
        return list(arr)
    finally:
        _iphlpapi.FreeMibTable(tbl)


def _if_rows():
    """旧接口 GetIfTable（32 位计数），仅在 GetIfTable2 不可用时回退。"""
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


def _iface_name(row) -> str:
    """网卡名：优先 Alias（别名未清零时会连带描述，截断处理）。"""
    name = (row.Alias or "").split("\x00")[0].strip()
    return name[:24] if name else ""


def _pick_iface():
    """挑一块「主力网卡」-> (累计接收, 累计发送, 网卡名)。

    过滤规则：
        - 跳过回环、隧道接口
        - 跳过 WFP / QoS / LightWeight Filter 等「过滤层」接口
          （它们与物理网卡统计同一份流量，累加会重复计数好几倍）
        - 优先已连接（OperStatus=Up）且流量最大的一块
    """
    rows = _if_rows2()
    if rows:
        cands = []
        for r in rows:
            if not r.InterfaceIndex:
                continue
            if r.Type in (IF_TYPE_SOFTWARE_LOOPBACK, IF_TYPE_TUNNEL):
                continue
            if r.Flags & FLAG_FILTER:          # 过滤层接口
                continue
            cands.append(r)
        up = [r for r in cands
              if r.OperStatus == IF_OPER_STATUS_UP
              and r.MediaConnectState == IF_OPER_STATUS_CONNECTED]
        pool = up or cands
        if pool:
            best = max(pool, key=lambda r: r.InOctets + r.OutOctets)
            return best.InOctets, best.OutOctets, _iface_name(best)

    # 回退：旧接口累加非回环网卡
    rows1 = [r for r in _if_rows()
             if r.dwIndex and r.dwType != IF_TYPE_SOFTWARE_LOOPBACK]
    up1 = [r for r in rows1 if r.dwOperStatus == IF_OPER_STATUS_UP]
    use = up1 or rows1
    if use:
        rx = sum(r.dwInOctets for r in use)
        tx = sum(r.dwOutOctets for r in use)
        return rx, tx, _iface_name(use[0]) if use else ""
    return 0, 0, ""


def net_counters():
    """主力网卡的累计收发字节数 -> (接收, 发送, 网卡名)。"""
    return _pick_iface()


def _delta(cur: int, prev: int) -> int:
    """差值（负数说明计数器重置或换了网卡，按 0 处理）。"""
    return max(0, cur - prev)


_net_state = {"t": 0.0, "rx": 0, "tx": 0, "name": ""}


def net_speed():
    """网速（字节/秒）-> (下载, 上传, 网卡名)；首次调用只建立基准，返回 None。"""
    if not _WIN:
        return None
    now = time.perf_counter()
    rx, tx, name = net_counters()
    st = _net_state
    # 首次采样、或主力网卡变了（拔网线 / 换 Wi-Fi）都要重建基准，避免假峰值
    if st["t"] == 0.0 or (name and st["name"] and name != st["name"]):
        st["t"], st["rx"], st["tx"], st["name"] = now, rx, tx, name
        return None
    dt = now - st["t"]
    if dt <= 0:
        return None
    down = _delta(rx, st["rx"]) / dt
    up = _delta(tx, st["tx"]) / dt
    st["t"], st["rx"], st["tx"], st["name"] = now, rx, tx, name
    return down, up, name


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
