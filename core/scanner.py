# -*- coding: utf-8 -*-
"""桌面项扫描模块：扫描桌面上的文件、文件夹和快捷方式。"""
import os
from dataclasses import dataclass, field

if os.name == "nt":
    import ctypes

    _FILE_ATTRIBUTE_HIDDEN = 0x2
    _FILE_ATTRIBUTE_SYSTEM = 0x4

    def _is_hidden(path: str) -> bool:
        """Windows 下判断是否为隐藏/系统文件（如 desktop.ini）。"""
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        except Exception:
            return False
        if attrs == -1:  # INVALID_FILE_ATTRIBUTES
            return False
        return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))
else:
    def _is_hidden(path: str) -> bool:
        return os.path.basename(path).startswith(".")


@dataclass
class DesktopItem:
    """桌面上的一个项目（文件 / 文件夹 / 快捷方式）。"""
    name: str                    # 显示名称
    path: str                    # 完整路径
    kind: str = "file"           # file / dir / shortcut
    category: str = ""           # 所属分类名，空串表示未分类

    @property
    def display_name(self) -> str:
        name = self.name
        if self.kind == "shortcut" and name.lower().endswith(".lnk"):
            name = name[:-4]
        if self.kind == "shortcut" and name.lower().endswith(".url"):
            name = name[:-4]
        return name


def get_desktop_paths() -> list:
    """获取当前用户的桌面路径（含公共桌面）。"""
    home = os.path.expanduser("~")
    paths = [os.path.join(home, "Desktop")]
    public = os.path.join(os.environ.get("PUBLIC", os.path.join(home, "..", "Public")), "Desktop")
    if os.path.isdir(public):
        paths.append(public)
    return [p for p in paths if os.path.isdir(p)]


def scan_desktop() -> list:
    """扫描桌面，返回 DesktopItem 列表。

    同一个桌面内不会重复；用户桌面与公共桌面的同名项目是两份不同的东西，
    所以都保留（早先按 name 全局去重会让后者被前者顶掉，整理时就会漏项）。
    """
    items = []
    for desktop in get_desktop_paths():
        seen_here = set()
        for entry in os.scandir(desktop):
            if entry.name in seen_here:
                continue
            seen_here.add(entry.name)
            if _is_hidden(entry.path):
                continue
            if entry.name.lower().endswith((".lnk", ".url")):
                kind = "shortcut"
            elif entry.is_dir():
                kind = "dir"
            else:
                kind = "file"
            items.append(DesktopItem(name=entry.name, path=entry.path, kind=kind))
    items.sort(key=lambda i: (i.display_name.lower(), i.path.lower()))
    return items
