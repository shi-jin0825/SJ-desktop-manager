# -*- coding: utf-8 -*-
"""GUI 模块：手机桌面风格的分类管理界面。"""
import base64
import math
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
ICON_SIZE = 48      # 普通磁贴图标尺寸（px）

# 分类文件夹预览（手机文件夹式：3×3 缩略图标）
FOLDER_PREVIEW = 70     # 预览画布边长（px）
PREVIEW_ICON = 20       # 预览内单个小图标边长（px）
PREVIEW_GAP = 2         # 小图标间距（px）
PREVIEW_PAD = 3         # 预览区外边距（px）
PREVIEW_COLS = 3
MAX_PREVIEW = PREVIEW_COLS ** 2
FOLDER_BG = "#dfe7f5"
FOLDER_BG_HOVER = "#c9d7ef"
FOLDER_PANEL = "#ffffff"


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


def rounded_rect(canvas, x1, y1, x2, y2, r=12, **kw):
    """在 Canvas 上画圆角矩形（tkinter 没有原生圆角矩形）。"""
    pts = []
    for cx, cy, start in ((x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270),
                          (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90)):
        for i in range(11):
            a = math.radians(start + i * 9)
            pts += (cx + r * math.cos(a), cy + r * math.sin(a))
    return canvas.create_polygon(pts, smooth=True, **kw)


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
        self.title("墨墨桌面管理助手")
        self.geometry("1000x640")
        self.configure(bg="#eef1f6")
        self.config_mgr = ConfigManager()
        self.items = []
        self._photos = []
        self._pet = None          # 桌面悬浮宠物窗口（None = 未召唤）

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
        self._pet_btn = tk.Button(bar, text="🐙 桌面宠物",
                                  font=("Microsoft YaHei", 10),
                                  relief="flat", bg="#ffffff", padx=12, pady=4,
                                  activebackground="#e5e5ea",
                                  command=self._toggle_pet)
        self._pet_btn.pack(side="left", padx=4)

    # ---------- 桌面悬浮宠物 ----------
    def _toggle_pet(self):
        """召唤 / 收起桌面上独立悬浮的墨墨（真透明 + 鼠标穿透 + 上下浮动）。"""
        if getattr(self, "_pet", None) is not None:
            try:
                self._pet.on_close()
            except Exception:
                pass
            return
        from gui.pet import DesktopPet
        self._pet = DesktopPet(self)
        self._pet_btn.config(text="🐙 收起宠物")

    def _on_pet_closed(self):
        """桌宠被收起时（右键菜单 / 按钮）回调。"""
        self._pet = None
        self._pet_btn.config(text="🐙 桌面宠物")

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
        """手机桌面式文件夹磁贴：在磁贴上直接预览分类里的前 9 个图标。"""
        inner = [i for i in self.items if i.category == category]
        previews = inner[:MAX_PREVIEW]

        frame = tk.Frame(self.grid_frame, width=TILE_SIZE, height=TILE_H,
                         bg=FOLDER_BG, highlightthickness=0)
        frame.grid_propagate(False)
        frame.grid(row=idx // COLS, column=idx % COLS, padx=8, pady=8)

        canvas = tk.Canvas(frame, width=FOLDER_PREVIEW, height=FOLDER_PREVIEW,
                           bg=FOLDER_BG, highlightthickness=0)
        canvas.pack(pady=(6, 0))
        rounded_rect(canvas, 1, 1, FOLDER_PREVIEW - 1, FOLDER_PREVIEW - 1,
                     r=12, fill=FOLDER_PANEL, outline="#c9d7ef")

        if previews:
            for i, item in enumerate(previews):
                row, col = divmod(i, PREVIEW_COLS)
                x = PREVIEW_PAD + col * (PREVIEW_ICON + PREVIEW_GAP) + PREVIEW_ICON // 2
                y = PREVIEW_PAD + row * (PREVIEW_ICON + PREVIEW_GAP) + PREVIEW_ICON // 2
                mini = self._mini_icon(item.path)
                if mini:
                    canvas.create_image(x, y, image=mini)
                else:  # 拿不到图标时的占位块
                    canvas.create_rectangle(x - PREVIEW_ICON // 2 + 2, y - PREVIEW_ICON // 2 + 2,
                                            x + PREVIEW_ICON // 2 - 2, y + PREVIEW_ICON // 2 - 2,
                                            fill="#e5e5ea", outline="#d0d0d8")
        else:
            canvas.create_text(FOLDER_PREVIEW // 2, FOLDER_PREVIEW // 2,
                               text="空", fill="#a3a3ad",
                               font=("Microsoft YaHei", 12, "bold"))

        label = tk.Label(frame, text=f"{short_name(category)} ({count})",
                         bg=FOLDER_BG, fg="#333333",
                         font=("Microsoft YaHei", 9), cursor="hand2")
        label.pack(pady=(4, 0))

        menu = tk.Menu(frame, tearoff=0)
        menu.add_command(label="删除此分类",
                         command=lambda: self._delete_category(category))

        open_cmd = lambda e=None: self._open_category(category)
        popup = lambda e: menu.tk_popup(e.x_root, e.y_root)
        enter = lambda e: self._hover_tile(frame, (canvas, label), FOLDER_BG_HOVER)
        leave = lambda e: self._hover_tile(frame, (canvas, label), FOLDER_BG)
        for w in (frame, canvas, label):
            w.bind("<Button-1>", open_cmd)
            w.bind("<Button-3>", popup)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _mini_icon(self, path: str):
        """取某个路径图标的缩略版（20×20）PhotoImage。"""
        return make_photo(icon_png(path, PREVIEW_ICON), self._photos)

    @staticmethod
    def _hover_tile(frame, children, color):
        frame.configure(bg=color)
        for w in children:
            w.configure(bg=color)

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
