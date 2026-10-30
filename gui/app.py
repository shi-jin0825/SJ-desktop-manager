# -*- coding: utf-8 -*-
"""GUI 模块：手机桌面风格的分类管理界面。"""
import base64
import os
import subprocess
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox

from core.scanner import scan_desktop
from core.config import ConfigManager
from core.icons import icon_png, folder_icon_png

TILE_SIZE = 96      # 单元格宽度（px）
TILE_H = 100        # 单元格高度（px）
COLS = 8            # 每行数量
ICON_SIZE = 48      # 图标尺寸（px）


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


def short_name(name: str, limit: int = 12) -> str:
    """超过长度用省略号截断，避免磁贴文字被硬切。"""
    name = name.strip()
    return name if len(name) <= limit else name[:limit - 1] + "…"


class CategoryWindow(tk.Toplevel):
    """某个分类文件夹的内容窗口。"""

    def __init__(self, master, category, items, config, on_change):
        super().__init__(master)
        self.title(f"📁 {category}")
        self.geometry("560x400")
        self.configure(bg="#f2f2f7")
        self.category = category
        self.cfg = config
        self.on_change = on_change
        self._photos = []

        tk.Label(self, text=f"📁 {category}（{len(items)} 项）",
                 font=("Microsoft YaHei", 14, "bold"),
                 bg="#f2f2f7", fg="#333").pack(pady=10)

        frame = tk.Frame(self, bg="#f2f2f7")
        frame.pack(fill="both", expand=True, padx=10, pady=5)
        frame.grid_columnconfigure(tuple(range(COLS)), weight=1)

        if not items:
            tk.Label(frame, text="空空如也，右键桌面上的项目可移入此分类",
                     bg="#f2f2f7", fg="#999").grid(row=0, column=0, columnspan=COLS, pady=40)

        for idx, item in enumerate(items):
            icon = make_photo(icon_png(item.path, ICON_SIZE), self._photos)
            if icon:
                btn = tk.Button(frame, image=icon, text=short_name(item.display_name),
                                compound="top", font=("Microsoft YaHei", 9),
                                width=90, height=86, relief="flat",
                                bg="#ffffff", activebackground="#e5e5ea",
                                command=lambda p=item.path: open_target(p))
            else:
                btn = tk.Button(frame, text=f"📄\n{short_name(item.display_name)}",
                                font=("Microsoft YaHei", 9),
                                width=10, height=4, relief="flat",
                                bg="#ffffff", activebackground="#e5e5ea",
                                command=lambda p=item.path: open_target(p))
            btn.grid(row=idx // COLS, column=idx % COLS, padx=6, pady=6)
            # 右键移出分类
            menu = tk.Menu(btn, tearoff=0)
            menu.add_command(label="移出分类",
                             command=lambda n=item.name: self._remove(n))
            btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    def _remove(self, item_name: str):
        """把项目移出当前分类，并同步刷新主窗口。"""
        self.cfg.unassign(item_name)
        if self.on_change:
            self.on_change()
        self.destroy()


class App(tk.Tk):
    """主窗口：手机桌面式布局。"""

    def __init__(self):
        super().__init__()
        self.title("SJ 桌面管理器")
        self.geometry("1000x640")
        self.configure(bg="#eef1f6")
        self.config_mgr = ConfigManager()
        self.items = []
        self._photos = []

        self._build_toolbar()
        self._build_grid_area()
        self.refresh()
        self.bind("<F5>", lambda e: self.refresh())

    # ---------- 界面搭建 ----------
    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#eef1f6")
        bar.pack(fill="x", padx=10, pady=8)
        for text, cmd in [
            ("🔄 刷新 (F5)", self.refresh),
            ("📂 新建分类", self._add_category),
            ("🗑 管理分类", self._manage_categories),
            ("🖥 打开桌面", self._open_desktop),
        ]:
            tk.Button(bar, text=text, font=("Microsoft YaHei", 10),
                      relief="flat", bg="#ffffff", padx=12, pady=4,
                      activebackground="#e5e5ea",
                      command=cmd).pack(side="left", padx=4)

    def _build_grid_area(self):
        container = tk.Frame(self, bg="#eef1f6")
        container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(container, bg="#eef1f6", highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg="#eef1f6")
        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw", width=960)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # 鼠标滚轮
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    # ---------- 数据与渲染 ----------
    def refresh(self):
        """重新扫描桌面并渲染网格。"""
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self._photos = []          # 释放上一轮的图标引用
        self.items = scan_desktop()
        for item in self.items:
            item.category = self.config_mgr.get_category(item.name)

        for c in range(COLS):
            self.grid_frame.grid_columnconfigure(c, weight=1)

        # 分类文件夹排在最前
        categories = self.config_mgr.categories
        for idx, cat in enumerate(categories):
            count = sum(1 for i in self.items if i.category == cat)
            self._make_folder_tile(idx, cat, count)
        # 未分类项目
        uncategorized = [i for i in self.items if not i.category]
        offset = len(categories)
        for idx, item in enumerate(uncategorized):
            self._make_item_tile(offset + idx, item)

    def _make_folder_tile(self, idx, category, count):
        icon = make_photo(folder_icon_png(ICON_SIZE), self._photos)
        if icon:
            btn = tk.Button(self.grid_frame,
                            image=icon, text=f"{short_name(category)}\n({count})",
                            compound="top", font=("Microsoft YaHei", 9),
                            width=TILE_SIZE, height=TILE_H, relief="flat",
                            bg="#dfe7f5", activebackground="#c9d7ef",
                            command=lambda: self._open_category(category))
        else:
            btn = tk.Button(self.grid_frame,
                            text=f"📁\n{category}\n({count})",
                            font=("Microsoft YaHei", 10),
                            width=11, height=5, relief="flat",
                            bg="#dfe7f5", activebackground="#c9d7ef",
                            command=lambda: self._open_category(category))
        btn.grid(row=idx // COLS, column=idx % COLS, padx=8, pady=8)
        menu = tk.Menu(btn, tearoff=0)
        menu.add_command(label="删除此分类",
                         command=lambda: self._delete_category(category))
        btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    def _make_item_tile(self, idx, item):
        icon = make_photo(icon_png(item.path, ICON_SIZE), self._photos)
        if icon:
            btn = tk.Button(self.grid_frame,
                            image=icon, text=short_name(item.display_name),
                            compound="top", font=("Microsoft YaHei", 9),
                            width=TILE_SIZE, height=TILE_H, relief="flat",
                            bg="#ffffff", activebackground="#e5e5ea",
                            command=lambda p=item.path: open_target(p))
        else:
            emoji = {"dir": "🗂", "shortcut": "🧩", "file": "📄"}.get(item.kind, "📄")
            btn = tk.Button(self.grid_frame,
                            text=f"{emoji}\n{short_name(item.display_name)}",
                            font=("Microsoft YaHei", 9),
                            width=11, height=5, relief="flat",
                            bg="#ffffff", activebackground="#e5e5ea",
                            command=lambda p=item.path: open_target(p))
        btn.grid(row=idx // COLS, column=idx % COLS, padx=8, pady=8)
        menu = tk.Menu(btn, tearoff=0)
        for cat in self.config_mgr.categories:
            menu.add_command(label=f"移入「{cat}」",
                             command=lambda n=item.name, c=cat: self._assign(n, c))
        menu.add_separator()
        menu.add_command(label="移出当前分类", command=lambda: self._unassign(item.name))
        btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    # ---------- 动作 ----------
    def _open_category(self, category):
        items = [i for i in self.items if i.category == category]
        CategoryWindow(self, category, items, self.config_mgr, on_change=self.refresh)

    def _assign(self, item_name, category):
        self.config_mgr.assign(item_name, category)
        self.refresh()

    def _unassign(self, item_name):
        self.config_mgr.unassign(item_name)
        self.refresh()

    def _add_category(self):
        name = simpledialog.askstring("新建分类", "分类名称：", parent=self)
        if name is not None:
            if not self.config_mgr.add_category(name):
                messagebox.showwarning("提示", "分类名称为空或已存在")
            self.refresh()

    def _delete_category(self, category):
        if messagebox.askyesno("删除分类", f"删除分类「{category}」？\n其中的项目将回到未分类状态。"):
            self.config_mgr.remove_category(category)
            self.refresh()

    def _manage_categories(self):
        cats = "\n".join(f"  • {c}" for c in self.config_mgr.categories) or "  （无）"
        if messagebox.askyesno("管理分类", f"当前分类：\n{cats}\n\n是否新建分类？"):
            self._add_category()

    def _open_desktop(self):
        from core.scanner import get_desktop_paths
        open_target(get_desktop_paths()[0])
