# -*- coding: utf-8 -*-
"""创建/更新 SJ 桌面管理器的桌面快捷方式（含专属图标，目标 pythonw 无黑框）。

用法：
    D:\\Python313\\python.exe tools\\make_shortcut.py

说明：
    - 若桌面已存在同名/旧名快捷方式，则原地更新（不产生重复快捷方式）；
    - 优先名字：SJ 桌面管理器.lnk；兼容旧名：run.bat - 快捷方式.lnk；
    - 图标用 assets/app-grid.ico（tools/make_icon.py 生成）。
"""
import ctypes
import os
import sys
from ctypes import wintypes

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

PYTHONW = r"D:\Python313\pythonw.exe"
MAIN_PY = os.path.join(PROJ, "main.py")
ICON = os.path.join(PROJ, "assets", "app-grid.ico")

GOOD_NAME = "SJ 桌面管理器.lnk"
OLD_NAMES = ("run.bat - 快捷方式.lnk", "run.bat.lnk")

CLSID_ShellLink = (0x00021401, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
IID_IShellLinkW = (0x000214F9, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
IID_IPersistFile = (0x0000010B, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)

# IShellLinkW vtable 槽位（IUnknown 占 0-2）
SLOT_GETPATH = 3
SLOT_SETDESCRIPTION = 7
SLOT_SETWORKDIR = 9
SLOT_SETARGUMENTS = 11
SLOT_SETICONLOCATION = 17
SLOT_SETPATH = 20
# IPersistFile vtable 槽位（IUnknown 占 0-2，GetClassID=3，IsDirty=4）
SLOT_LOAD = 5
SLOT_SAVE = 6


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_tuple(cls, t):
        d1, d2, d3, *rest = t
        return cls(d1, d2, d3, (ctypes.c_ubyte * 8)(*rest))


def _vtbl_func(ptr, index, proto):
    vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p)).contents,
                       ctypes.POINTER(ctypes.c_void_p))
    return proto(ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index])


def _hwnd_result(hr, what):
    if hr != 0:
        raise OSError(f"{what} 失败: HRESULT=0x{hr & 0xFFFFFFFF:08X}")


def refresh_shell():
    """通知资源管理器刷新图标缓存，让新图标立即生效。"""
    shell32 = ctypes.WinDLL("shell32")
    SHCNE_ASSOCCHANGED = 0x08000000
    SHCNE_UPDATEITEM = 0x00002000
    SHCNF_PATHW = 0x0005
    SHCNF_IDLIST = 0x0000
    try:
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW,
                               os.path.join(desktop_dir(), GOOD_NAME), None)
    except OSError:
        pass


def update_shortcut(lnk_path: str, target: str, arguments: str, workdir: str,
                    icon: str, description: str) -> None:
    """创建或更新一个 .lnk 快捷方式。"""
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx(None, 2)  # APARTMENTTHREADED

    p_link = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(GUID.from_tuple(CLSID_ShellLink)), None,
                                1,  # CLSCTX_INPROC_SERVER
                                ctypes.byref(GUID.from_tuple(IID_IShellLinkW)),
                                ctypes.byref(p_link))
    _hwnd_result(hr, "CoCreateInstance(IShellLinkW)")
    if not p_link.value:
        raise OSError("CoCreateInstance 返回空指针")

    WSTR = wintypes.LPCWSTR
    _HRESULT = ctypes.HRESULT
    try:
        v = lambda i, proto: _vtbl_func(p_link, i, proto)
        # 若文件已存在则载入原内容（失败也没关系，按新建处理）
        p_pf = ctypes.c_void_p()
        QueryInterface = v(0, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID),
                                                 ctypes.POINTER(ctypes.c_void_p)))
        hr = QueryInterface(p_link, ctypes.byref(GUID.from_tuple(IID_IPersistFile)),
                            ctypes.byref(p_pf))
        _hwnd_result(hr, "QueryInterface(IPersistFile)")
        try:
            Load = _vtbl_func(p_pf, SLOT_LOAD, ctypes.WINFUNCTYPE(
                _HRESULT, ctypes.c_void_p, WSTR, wintypes.DWORD))
            hr = Load(p_pf, lnk_path, 0)   # STGM_READ
            print(f"  Load({os.path.basename(lnk_path)}): "
                  f"{'成功' if hr == 0 else f'HRESULT=0x{hr & 0xFFFFFFFF:08X}（按新建处理）'}")
        finally:
            Release = _vtbl_func(p_pf, 2, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p))
            Release(p_pf)

        # 逐项写入
        v(SLOT_SETPATH, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, WSTR))(p_link, target)
        v(SLOT_SETARGUMENTS, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, WSTR))(p_link, arguments)
        v(SLOT_SETWORKDIR, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, WSTR))(p_link, workdir)
        v(SLOT_SETICONLOCATION, ctypes.WINFUNCTYPE(
            _HRESULT, ctypes.c_void_p, WSTR, ctypes.c_int))(p_link, icon, 0)
        v(SLOT_SETDESCRIPTION, ctypes.WINFUNCTYPE(
            _HRESULT, ctypes.c_void_p, WSTR))(p_link, description)

        # 保存前读回确认 SetPath 生效
        buf = ctypes.create_unicode_buffer(260)
        GetPath = v(SLOT_GETPATH, ctypes.WINFUNCTYPE(
            _HRESULT, ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD))
        GetPath(p_link, buf, 260, None, 0)
        if buf.value != target:
            raise OSError(f"SetPath 未生效：读到 {buf.value!r}，应为 {target!r}")

        # 保存
        p_pf = ctypes.c_void_p()
        hr = QueryInterface(p_link, ctypes.byref(GUID.from_tuple(IID_IPersistFile)),
                            ctypes.byref(p_pf))
        _hwnd_result(hr, "QueryInterface(IPersistFile)")
        try:
            Save = _vtbl_func(p_pf, SLOT_SAVE, ctypes.WINFUNCTYPE(
                _HRESULT, ctypes.c_void_p, WSTR, wintypes.BOOL))
            hr = Save(p_pf, lnk_path, True)
            _hwnd_result(hr, "IPersistFile::Save")
        finally:
            Release = _vtbl_func(p_pf, 2, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p))
            Release(p_pf)

        # 保存后读回验证
        GetPath(p_link, buf, 260, None, 0)
        print(f"  目标: {buf.value}")
        print(f"  参数: {arguments}")
        print(f"  图标: {icon}")
    finally:
        Release = _vtbl_func(p_link, 2, ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p))
        Release(p_link)


def desktop_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    desktop = desktop_dir()
    # 已存在则优先更新好名字的；否则找旧名；都没有就新建好名字的
    candidates = [os.path.join(desktop, GOOD_NAME)] + \
                 [os.path.join(desktop, n) for n in OLD_NAMES]
    lnk = next((p for p in candidates if os.path.isfile(p)), candidates[0])

    print(f"写入快捷方式：{lnk}")
    update_shortcut(lnk, target=PYTHONW, arguments=f'"{MAIN_PY}"',
                    workdir=PROJ, icon=ICON, description="SJ 桌面管理器")
    refresh_shell()
    print("完成。若桌面图标仍是旧的，按 F5 刷新或重启资源管理器。")


if __name__ == "__main__":
    main()
