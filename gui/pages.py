# -*- coding: utf-8 -*-
"""右侧主内容区的页面：首页（桌面网格）/ 分类 / 统计 / 设置。

每个页面都是 tk.Frame，由 gui.app.App（主框架）按需创建并切换。
页面统一通过 self.app 访问主题配色、配置和桌宠等全局能力。
"""
import os
import tkinter as tk
from tkinter import messagebox, simpledialog

from core.scanner import scan_desktop, get_desktop_paths
from core.icons import icon_png
from core import sysinfo
from gui.theme import (DEFAULT_THEME, THEMES, THEME_NAMES, get_theme, style_menu)
from gui.widgets import (open_target, make_photo, rounded_rect, short_name,
                         center_window, hline, stat_bar, shrink)

# ---- 磁贴尺寸 ----
TILE_SIZE = 96      # 单元格宽度（px）
TILE_H = 100        # 单元格高度（px）
COLS = 8            # 默认每行数量（窗口宽度变化时会自适应）
MIN_COLS = 4        # 每行最少数量
MAX_COLS = 16       # 每行最多数量（窗口放大时自动增加）
TILE_PADX = 8
TILE_PADY = 8
ICON_SIZE = 48      # 磁贴图标尺寸（px）

# ---- 分类文件夹 3×3 预览 ----
FOLDER_PREVIEW = 70
PREVIEW_ICON = 20
PREVIEW_GAP = 2
PREVIEW_PAD = 3
PREVIEW_COLS = 3
MAX_PREVIEW = PREVIEW_COLS ** 2

APP_VERSION = "v0.6"
KIND_LABEL = {"shortcut": "快捷方式", "dir": "文件夹", "file": "文件"}


class CategoryWindow(tk.Toplevel):
    """某个分类文件夹的内容窗口。"""

    def __init__(self, master, category, items, config, on_change, theme=None):
        super().__init__(master)
        c = theme or get_theme(DEFAULT_THEME)
        self.C = c
        self.title(f"📁 {category}")
        center_window(self, 560, 400, master)
        self.configure(bg=c["dialog_bg"])
        self.category = category
        self.cfg = config
        self.on_change = on_change
        self._photos = []

        tk.Label(self, text=f"📁 {category}（{len(items)} 项）",
                 font=("Microsoft YaHei", 14, "bold"),
                 bg=c["dialog_bg"], fg=c["text"]).pack(pady=10)

        frame = tk.Frame(self, bg=c["dialog_bg"])
        frame.pack(fill="both", expand=True, padx=10, pady=5)
        frame.grid_columnconfigure(tuple(range(COLS)), weight=1)

        if not items:
            tk.Label(frame, text="空空如也，右键桌面上的项目可移入此分类",
                     bg=c["dialog_bg"], fg=c["text_muted"]).grid(
                row=0, column=0, columnspan=COLS, pady=40)

        for idx, item in enumerate(items):
            icon = make_photo(icon_png(item.path, ICON_SIZE), self._photos)
            if icon:
                btn = tk.Button(frame, image=icon, text=short_name(item.display_name),
                                compound="top", font=("Microsoft YaHei", 9),
                                width=90, height=86, relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            else:
                btn = tk.Button(frame, text=f"📄\n{short_name(item.display_name)}",
                                font=("Microsoft YaHei", 9),
                                width=10, height=4, relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            btn.grid(row=idx // COLS, column=idx % COLS, padx=6, pady=6)
            menu = tk.Menu(btn, tearoff=0)
            menu.add_command(label="移出分类",
                             command=lambda n=item.name: self._remove(n))
            style_menu(menu, c)
            btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    def _remove(self, item_name: str):
        """把项目移出当前分类，并同步刷新调用方。"""
        self.cfg.unassign(item_name)
        if self.on_change:
            self.on_change()
        self.destroy()


class BasePage(tk.Frame):
    """页面基类：统一背景、主题、配置入口。"""

    key = "base"
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        self.app = app
        self.C = app.C
        super().__init__(master, bg=self.C["app_bg"])
        self.cfg = app.config_mgr
        self._photos = []
        self._build()

    # 子类实现
    def _build(self):
        pass

    def refresh(self):
        pass

    def _toolbar(self, buttons):
        """页面顶部的一条操作按钮（(文字, 命令) 列表）。"""
        c = self.C
        bar = tk.Frame(self, bg=c["app_bg"])
        bar.pack(fill="x", padx=16, pady=(12, 6))
        for text, cmd in buttons:
            tk.Button(bar, text=text, font=("Microsoft YaHei", 10),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      padx=12, pady=4, activebackground=c["panel_active"],
                      activeforeground=c["text"], bd=0,
                      command=cmd).pack(side="left", padx=(0, 8))
        return bar


# ======================================================================
# 1. 首页：桌面网格
# ======================================================================
class DesktopPage(BasePage):
    key = "home"
    title = "🏠 桌面首页"
    subtitle = "像手机桌面一样管理你的桌面图标"

    def __init__(self, master, app):
        self.items = []
        self.cols = COLS
        self._cols_cfg = 0
        self._relayout_job = None
        self._scrollable = False
        super().__init__(master, app)

    def _build(self):
        c = self.C
        self._toolbar([
            ("🔄 刷新 (F5)", self.refresh),
            ("📂 新建分类", self._add_category),
            ("🗂 管理分类", self._manage_categories),
            ("🖥 打开桌面", self._open_desktop),
            ("🐙 桌面宠物" if not self.app.pet_active() else "🐙 收起宠物",
             self._pet_cmd),
        ])
        container = tk.Frame(self, bg=c["app_bg"])
        container.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.canvas = tk.Canvas(container, bg=c["app_bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical",
                                 command=self.canvas.yview,
                                 width=14, borderwidth=0, relief="flat",
                                 elementborderwidth=0, highlightthickness=0,
                                 troughcolor=c["scroll_trough"],
                                 bg=c["scroll_thumb"],
                                 activebackground=c["scroll_thumb_active"],
                                 jump=1)
        self.scrollbar = scrollbar
        scrollbar.bind("<Enter>", lambda e: self._hover_scrollbar(True))
        scrollbar.bind("<Leave>", lambda e: self._hover_scrollbar(False))
        self.grid_frame = tk.Frame(self.canvas, bg=c["app_bg"])
        self._grid_win = self.canvas.create_window((0, 0), window=self.grid_frame,
                                                   anchor="nw")
        self.grid_frame.bind("<Configure>", self._on_grid_configure)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y", padx=(6, 0))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.refresh()

    def _pet_cmd(self):
        self.app._toggle_pet()

    # ---- 自适应布局 ----
    def _on_grid_configure(self, event=None):
        ch = self.canvas.winfo_height()
        fh = self.grid_frame.winfo_reqheight()
        if ch > 1 and 0 < fh < ch:
            y = (ch - fh) // 2
            self.canvas.coords(self._grid_win, 0, y)
            self.canvas.configure(
                scrollregion=(0, 0, self.grid_frame.winfo_width(), ch))
        else:
            self.canvas.coords(self._grid_win, 0, 0)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_resize(self, event=None):
        w = event.width if event is not None and event.width > 1 \
            else self.canvas.winfo_width()
        if w <= 1:
            return
        self.canvas.itemconfigure(self._grid_win, width=w)
        cols = self._cols_for_width(w)
        if cols != self.cols:
            self.cols = cols
            if self._relayout_job is not None:
                self.after_cancel(self._relayout_job)
            self._relayout_job = self.after(150, self._do_relayout)

    def _do_relayout(self):
        self._relayout_job = None
        self.refresh()

    def _cols_for_width(self, width: int) -> int:
        per = TILE_SIZE + TILE_PADX * 2 + 4
        return max(MIN_COLS, min(MAX_COLS, width // per))

    def _configure_columns(self, cols: int):
        top = max(cols, self._cols_cfg, COLS)
        for i in range(top):
            self.grid_frame.grid_columnconfigure(
                i, weight=1 if i < cols else 0, minsize=0)
        self._cols_cfg = cols

    @staticmethod
    def _cell(idx: int, cols: int, total: int):
        """第 idx 个磁贴的 (行, 列)。

        排不满一行时整行居中；够排满一行就从左往右排，后续行顶到最前面。
        """
        if total <= 0:
            return 0, 0
        if total < cols:
            return 0, (cols - total) // 2 + idx
        return idx // cols, idx % cols

    def _update_scrollbar(self):
        sb = getattr(self, "scrollbar", None)
        if sb is None:
            return
        c = self.C
        ch = self.canvas.winfo_height()
        fh = self.grid_frame.winfo_reqheight()
        self._scrollable = ch > 1 and fh > ch
        sb.configure(troughcolor=c["scroll_trough"],
                     bg=c["scroll_thumb"] if self._scrollable else c["scroll_trough"])

    def _hover_scrollbar(self, on: bool):
        if getattr(self, "_scrollable", False):
            self.scrollbar.configure(
                bg=self.C["scroll_thumb_active"] if on else self.C["scroll_thumb"])

    # ---- 渲染 ----
    def refresh(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self._photos = []
        self.items = scan_desktop()
        for item in self.items:
            item.category = self.cfg.get_category(item.name)

        w = self.canvas.winfo_width()
        if w > 1:
            self.canvas.itemconfigure(self._grid_win, width=w)
            self.cols = self._cols_for_width(w)

        categories = self.cfg.categories
        total = len(categories) + sum(1 for i in self.items if not i.category)
        cols = self.cols
        self._configure_columns(cols)

        idx = 0
        for cat in categories:
            count = sum(1 for i in self.items if i.category == cat)
            row, col = self._cell(idx, cols, total)
            self._make_folder_tile(row, col, cat, count)
            idx += 1
        for item in self.items:
            if not item.category:
                row, col = self._cell(idx, cols, total)
                self._make_item_tile(row, col, item)
                idx += 1
        self._on_grid_configure()
        self.app.update_topbar(self.subtitle + f" · 共 {len(self.items)} 项")

    def _mini_icon(self, path: str):
        """文件夹预览用的小图标：系统可能返回比请求大的图，缩到预览尺寸。"""
        return shrink(make_photo(icon_png(path, PREVIEW_ICON), self._photos),
                      PREVIEW_ICON, self._photos)

    @staticmethod
    def _hover_tile(frame, children, color):
        frame.configure(bg=color)
        for w in children:
            w.configure(bg=color)

    def _make_folder_tile(self, row, col, category, count):
        c = self.C
        inner = [i for i in self.items if i.category == category]
        previews = inner[:MAX_PREVIEW]

        frame = tk.Frame(self.grid_frame, width=TILE_SIZE, height=TILE_H,
                         bg=c["folder_bg"], highlightthickness=0)
        frame.grid_propagate(False)
        frame.grid(row=row, column=col, padx=TILE_PADX, pady=TILE_PADY)

        canvas = tk.Canvas(frame, width=FOLDER_PREVIEW, height=FOLDER_PREVIEW,
                           bg=c["folder_bg"], highlightthickness=0)
        canvas.pack(pady=(6, 0))
        rounded_rect(canvas, 1, 1, FOLDER_PREVIEW - 1, FOLDER_PREVIEW - 1,
                     r=12, fill=c["folder_panel"], outline=c["folder_panel_outline"])

        if previews:
            for i, item in enumerate(previews):
                r, cc = divmod(i, PREVIEW_COLS)
                x = PREVIEW_PAD + cc * (PREVIEW_ICON + PREVIEW_GAP) + PREVIEW_ICON // 2
                y = PREVIEW_PAD + r * (PREVIEW_ICON + PREVIEW_GAP) + PREVIEW_ICON // 2
                mini = self._mini_icon(item.path)
                if mini:
                    canvas.create_image(x, y, image=mini)
                else:
                    canvas.create_rectangle(x - PREVIEW_ICON // 2 + 2, y - PREVIEW_ICON // 2 + 2,
                                            x + PREVIEW_ICON // 2 - 2, y + PREVIEW_ICON // 2 - 2,
                                            fill=c["placeholder"],
                                            outline=c["placeholder_outline"])
        else:
            canvas.create_text(FOLDER_PREVIEW // 2, FOLDER_PREVIEW // 2,
                               text="空", fill=c["empty_text"],
                               font=("Microsoft YaHei", 12, "bold"))

        label = tk.Label(frame, text=f"{short_name(category)} ({count})",
                         bg=c["folder_bg"], fg=c["text"],
                         font=("Microsoft YaHei", 9), cursor="hand2")
        label.pack(pady=(4, 0))

        menu = tk.Menu(frame, tearoff=0)
        menu.add_command(label="打开分类",
                         command=lambda: self._open_category(category))
        menu.add_command(label="重命名分类",
                         command=lambda: self._rename_category(category))
        menu.add_separator()
        menu.add_command(label="删除此分类",
                         command=lambda: self._delete_category(category))
        style_menu(menu, c)

        open_cmd = lambda e=None: self._open_category(category)
        popup = lambda e: menu.tk_popup(e.x_root, e.y_root)
        enter = lambda e: self._hover_tile(frame, (canvas, label), c["folder_bg_hover"])
        leave = lambda e: self._hover_tile(frame, (canvas, label), c["folder_bg"])
        for w in (frame, canvas, label):
            w.bind("<Button-1>", open_cmd)
            w.bind("<Button-3>", popup)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _make_item_tile(self, row, col, item):
        c = self.C
        icon = make_photo(icon_png(item.path, ICON_SIZE), self._photos)
        if icon:
            btn = tk.Button(self.grid_frame,
                            image=icon, text=short_name(item.display_name),
                            compound="top", font=("Microsoft YaHei", 9),
                            width=TILE_SIZE, height=TILE_H, relief="flat",
                            bg=c["panel_bg"], fg=c["text"],
                            activebackground=c["panel_active"],
                            activeforeground=c["text"],
                            command=lambda p=item.path: open_target(p))
        else:
            emoji = {"dir": "🗂", "shortcut": "🧩", "file": "📄"}.get(item.kind, "📄")
            btn = tk.Button(self.grid_frame,
                            text=f"{emoji}\n{short_name(item.display_name)}",
                            font=("Microsoft YaHei", 9),
                            width=11, height=5, relief="flat",
                            bg=c["panel_bg"], fg=c["text"],
                            activebackground=c["panel_active"],
                            activeforeground=c["text"],
                            command=lambda p=item.path: open_target(p))
        btn.grid(row=row, column=col, padx=TILE_PADX, pady=TILE_PADY)
        menu = tk.Menu(btn, tearoff=0)
        for cat in self.cfg.categories:
            menu.add_command(label=f"移入「{cat}」",
                             command=lambda n=item.name, cc=cat: self._assign(n, cc))
        menu.add_separator()
        menu.add_command(label="移出当前分类", command=lambda: self._unassign(item.name))
        style_menu(menu, c)
        btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    # ---- 动作 ----
    def _open_category(self, category):
        items = [i for i in self.items if i.category == category]
        CategoryWindow(self.app, category, items, self.cfg,
                       on_change=self.refresh, theme=self.C)

    def _assign(self, item_name, category):
        self.cfg.assign(item_name, category)
        self.refresh()

    def _unassign(self, item_name):
        self.cfg.unassign(item_name)
        self.refresh()

    def _add_category(self):
        name = simpledialog.askstring("新建分类", "分类名称：", parent=self.app)
        if name is not None:
            if not self.cfg.add_category(name):
                messagebox.showwarning("提示", "分类名称为空或已存在", parent=self.app)
            self.refresh()

    def _rename_category(self, category):
        new = simpledialog.askstring("重命名分类", "新的分类名称：",
                                     initialvalue=category, parent=self.app)
        if new is None:
            return
        if not self.cfg.rename_category(category, new):
            if (new or "").strip() != category:
                messagebox.showwarning("提示", "分类名称为空或已存在", parent=self.app)
            return
        self.refresh()

    def _delete_category(self, category):
        if messagebox.askyesno("删除分类",
                               f"删除分类「{category}」？\n其中的项目将回到未分类状态。",
                               parent=self.app):
            self.cfg.remove_category(category)
            self.refresh()

    def _manage_categories(self):
        """分类管理器（弹窗）：新建 / 重命名 / 删除。"""
        c = self.C
        win = tk.Toplevel(self.app)
        win.title("管理分类")
        win.transient(self.app)
        center_window(win, 330, 380, self.app)
        win.configure(bg=c["dialog_bg"])
        win.resizable(False, False)
        win.grab_set()

        top = tk.Frame(win, bg=c["dialog_bg"])
        top.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        tk.Label(top, text="分类列表（括号内为项目数）",
                 font=("Microsoft YaHei", 10), bg=c["dialog_bg"], fg=c["text"],
                 anchor="w").pack(fill="x")

        body = tk.Frame(top, bg=c["dialog_bg"])
        body.pack(fill="both", expand=True, pady=6)
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        lst = tk.Listbox(body, font=("Microsoft YaHei", 10), relief="solid",
                         bd=1, activestyle="none", height=10,
                         bg=c["panel_bg"], fg=c["text"],
                         selectbackground=c["list_sel"],
                         selectforeground=c["text"],
                         highlightthickness=0, yscrollcommand=scroll.set)
        lst.pack(side="left", fill="both", expand=True)
        scroll.config(command=lst.yview)

        def count_of(cat):
            return sum(1 for v in self.cfg.data["assignments"].values() if v == cat)

        def reload(keep=None):
            lst.delete(0, "end")
            for cat in self.cfg.categories:
                lst.insert("end", f"{cat}  ({count_of(cat)})")
            if keep is not None and keep < lst.size():
                lst.selection_set(keep)
                lst.see(keep)

        def selected():
            sel = lst.curselection()
            return self.cfg.categories[sel[0]] if sel else None

        def do_add():
            name = simpledialog.askstring("新建分类", "分类名称：", parent=win)
            if name is None:
                return
            if not self.cfg.add_category(name):
                messagebox.showwarning("提示", "分类名称为空或已存在", parent=win)
                return
            reload(self.cfg.categories.index(name.strip()))
            self.refresh()

        def do_rename():
            old = selected()
            if old is None:
                messagebox.showinfo("提示", "请先选择一个分类", parent=win)
                return
            new = simpledialog.askstring("重命名分类", "新的分类名称：",
                                         initialvalue=old, parent=win)
            if new is None:
                return
            if not self.cfg.rename_category(old, new):
                if (new or "").strip() != old:
                    messagebox.showwarning("提示", "分类名称为空或已存在", parent=win)
                return
            reload(self.cfg.categories.index(new.strip()))
            self.refresh()

        def do_delete():
            cat = selected()
            if cat is None:
                messagebox.showinfo("提示", "请先选择一个分类", parent=win)
                return
            if messagebox.askyesno(
                    "删除分类",
                    f"删除分类「{cat}」？\n其中的项目将回到未分类状态。", parent=win):
                self.cfg.remove_category(cat)
                reload()
                self.refresh()

        bar = tk.Frame(win, bg=c["dialog_bg"])
        bar.pack(fill="x", padx=12, pady=8)
        for text, cmd in (("➕ 新建", do_add), ("✏️ 重命名", do_rename),
                          ("🗑 删除", do_delete)):
            tk.Button(bar, text=text, font=("Microsoft YaHei", 9),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"],
                      activeforeground=c["text"], padx=8, pady=4, bd=0,
                      command=cmd).pack(side="left", padx=3)
        tk.Button(bar, text="关闭", font=("Microsoft YaHei", 9), relief="flat",
                  bg=c["panel_bg"], fg=c["text"],
                  activebackground=c["panel_active"],
                  activeforeground=c["text"], padx=10, pady=4, bd=0,
                  command=win.destroy).pack(side="right")

        lst.bind("<Double-Button-1>", lambda e: do_rename())
        reload()
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def _open_desktop(self):
        open_target(get_desktop_paths()[0])


# ======================================================================
# 2. 分类页：分类卡片管理
# ======================================================================
class CategoriesPage(BasePage):
    key = "categories"
    title = "🗂 分类管理"
    subtitle = "新建、重命名、删除分类，并查看每个分类里的内容"

    def _build(self):
        c = self.C
        self._toolbar([("➕ 新建分类", self._add),
                       ("🔄 刷新", self.refresh)])
        self.body = tk.Frame(self, bg=c["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.refresh()

    def refresh(self):
        c = self.C
        for w in self.body.winfo_children():
            w.destroy()
        self._photos = []
        self.items = scan_desktop()
        for item in self.items:
            item.category = self.cfg.get_category(item.name)

        if not self.cfg.categories:
            tk.Label(self.body, text="还没有分类，点右上角「➕ 新建分类」创建第一个",
                     bg=c["app_bg"], fg=c["text_muted"],
                     font=("Microsoft YaHei", 11)).pack(pady=40)
            self.app.update_topbar("暂无分类")
            return

        for cat in self.cfg.categories:
            self._card(cat)
        self.app.update_topbar(f"{len(self.cfg.categories)} 个分类 · "
                               f"{len(self.items)} 个桌面项目")

    def _card(self, category):
        c = self.C
        inner = [i for i in self.items if i.category == category]
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=12, pady=10)
        card.pack(fill="x", pady=6)

        # 左侧：2×2 图标预览
        pv = tk.Canvas(card, width=48, height=48, bg=c["card_bg"],
                       highlightthickness=0)
        pv.pack(side="left", padx=(0, 12))
        rounded_rect(pv, 1, 1, 47, 47, r=10, fill=c["folder_panel"],
                     outline=c["divider"])
        for i, item in enumerate(inner[:4]):
            r, cc = divmod(i, 2)
            mini = shrink(make_photo(icon_png(item.path, 20), self._photos),
                          20, self._photos)
            if mini:
                pv.create_image(13 + cc * 22, 13 + r * 22, image=mini)

        mid = tk.Frame(card, bg=c["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        tk.Label(mid, text=f"📁 {category}", bg=c["card_bg"], fg=c["text"],
                 font=("Microsoft YaHei", 12, "bold"), anchor="w").pack(fill="x")
        names = "、".join(short_name(i.display_name, 10) for i in inner[:6])
        if len(inner) > 6:
            names += f" 等 {len(inner)} 项"
        tk.Label(mid, text=names if names else "（空分类）",
                 bg=c["card_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill="x")

        btns = tk.Frame(card, bg=c["card_bg"])
        btns.pack(side="right")
        for text, cmd in (("打开", lambda: self._open(category)),
                          ("重命名", lambda: self._rename(category)),
                          ("删除", lambda: self._delete(category))):
            tk.Button(btns, text=text, font=("Microsoft YaHei", 9),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"], bd=0,
                      padx=10, pady=3, command=cmd).pack(side="left", padx=3)

    def _open(self, category):
        items = [i for i in self.items if i.category == category]
        CategoryWindow(self.app, category, items, self.cfg,
                       on_change=self.refresh, theme=self.C)

    def _add(self):
        name = simpledialog.askstring("新建分类", "分类名称：", parent=self.app)
        if name is None:
            return
        if not self.cfg.add_category(name):
            messagebox.showwarning("提示", "分类名称为空或已存在", parent=self.app)
        self.refresh()

    def _rename(self, old):
        new = simpledialog.askstring("重命名分类", "新的分类名称：",
                                     initialvalue=old, parent=self.app)
        if new is None:
            return
        if not self.cfg.rename_category(old, new):
            if (new or "").strip() != old:
                messagebox.showwarning("提示", "分类名称为空或已存在", parent=self.app)
            return
        self.refresh()

    def _delete(self, category):
        if messagebox.askyesno("删除分类",
                               f"删除分类「{category}」？\n其中的项目将回到未分类状态。",
                               parent=self.app):
            self.cfg.remove_category(category)
            self.refresh()


# ======================================================================
# 3. 统计页
# ======================================================================
class StatsPage(BasePage):
    key = "stats"
    title = "📊 数据统计"
    subtitle = "桌面整理情况的概览"

    def _build(self):
        self._toolbar([("🔄 刷新", self.refresh)])
        self.body = tk.Frame(self, bg=self.C["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.refresh()

    def refresh(self):
        c = self.C
        for w in self.body.winfo_children():
            w.destroy()
        items = scan_desktop()
        for i in items:
            i.category = self.cfg.get_category(i.name)
        done = sum(1 for i in items if i.category)
        total = len(items)

        # 概览数字卡片
        grid = tk.Frame(self.body, bg=c["app_bg"])
        grid.pack(fill="x")
        for i in range(4):
            grid.grid_columnconfigure(i, weight=1)
        for idx, (num, label) in enumerate(
                ((total, "桌面项目"), (done, "已归类"),
                 (total - done, "未归类"), (len(self.cfg.categories), "分类数"))):
            card = tk.Frame(grid, bg=c["card_bg"], highlightthickness=1,
                            highlightbackground=c["divider"], padx=14, pady=12)
            card.grid(row=0, column=idx, padx=6, pady=6, sticky="nsew")
            tk.Label(card, text=str(num), bg=c["card_bg"], fg=c["accent"],
                     font=("Microsoft YaHei", 20, "bold")).pack()
            tk.Label(card, text=label, bg=c["card_bg"], fg=c["sidebar_muted"],
                     font=("Microsoft YaHei", 9)).pack()

        # 分类分布
        self._section("分类分布")
        if total:
            for cat in self.cfg.categories:
                n = sum(1 for i in items if i.category == cat)
                self._row(cat, n, total)
            n = total - done
            if n:
                self._row("未归类", n, total)
        else:
            tk.Label(self.body, text="桌面上没有可统计的项目",
                     bg=c["app_bg"], fg=c["text_muted"]).pack(anchor="w")

        # 类型分布
        self._section("类型分布")
        for kind in ("shortcut", "dir", "file"):
            n = sum(1 for i in items if i.kind == kind)
            self._row(KIND_LABEL.get(kind, kind), n, total)

        self.app.update_topbar(f"已归类 {done}/{total} 项")

    def _section(self, text):
        c = self.C
        tk.Label(self.body, text=text, bg=c["app_bg"], fg=c["text"],
                 font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        hline(self.body, c["divider"], pady=(0, 8))

    def _row(self, name, n, total):
        c = self.C
        row = tk.Frame(self.body, bg=c["app_bg"])
        row.pack(fill="x", pady=3)
        tk.Label(row, text=name, bg=c["app_bg"], fg=c["text"],
                 font=("Microsoft YaHei", 10), width=12, anchor="w").pack(side="left")
        stat_bar(row, (n / total) if total else 0, c, width=260, height=10)
        pct = f"{n / total * 100:.0f}%" if total else "0%"
        tk.Label(row, text=f"{n} 项 · {pct}", bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=10)


# ======================================================================
# 4. 系统监控页：CPU / 内存 / 网速（每秒刷新）
# ======================================================================
class SystemPage(BasePage):
    key = "system"
    title = "📈 系统监控"
    subtitle = "CPU 占用率、内存剩余与实时网速"
    INTERVAL = 1000        # 刷新间隔（毫秒）
    HISTORY = 60           # 折线图保留的采样点数
    GRAPH_H = 130          # 折线图高度
    METER_W = 210          # 卡片内进度条宽度

    def _build(self):
        c = self.C
        self._history = []
        self._job = None

        bar = self._toolbar([("🔄 立即刷新", self._tick)])
        tk.Label(bar, text="每 1 秒自动刷新 · 数据来自 Windows 系统接口",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9)).pack(side="left")

        body = tk.Frame(self, bg=c["app_bg"])
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        grid = tk.Frame(body, bg=c["app_bg"])
        grid.pack(fill="x")
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1)
        self._cpu_val, self._cpu_meter, self._cpu_sub = self._card(grid, 0, "CPU 占用率")
        self._mem_val, self._mem_meter, self._mem_sub = self._card(grid, 1, "内存剩余")
        self._net_val, self._net_meter, self._net_sub = self._card(grid, 2, "实时网速")

        tk.Label(body, text=f"CPU 使用率（最近 {self.HISTORY} 秒）",
                 bg=c["app_bg"], fg=c["text"],
                 font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        self.graph = tk.Canvas(body, height=self.GRAPH_H, bg=c["card_bg"],
                               highlightthickness=1,
                               highlightbackground=c["divider"])
        self.graph.pack(fill="x")

        sysinfo.prime()                       # 建立采样基准
        self._draw_graph()                    # 先画空网格
        self._job = self.after(self.INTERVAL, self._tick)

    def _card(self, parent, col, title):
        """一张指标卡：标题 + 大数值 + 进度条 + 补充说明。"""
        c = self.C
        card = tk.Frame(parent, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=14, pady=12)
        card.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")
        tk.Label(card, text=title, bg=c["card_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill="x")
        val = tk.Label(card, text="—", bg=c["card_bg"], fg=c["accent"],
                       font=("Microsoft YaHei", 20, "bold"), anchor="w")
        val.pack(fill="x", pady=(4, 2))
        meter = tk.Canvas(card, width=self.METER_W, height=10,
                          bg=c["stat_bar_bg"], highlightthickness=0, bd=0)
        meter.pack(anchor="w", pady=4)
        sub = tk.Label(card, text="", bg=c["card_bg"], fg=c["sidebar_muted"],
                       font=("Microsoft YaHei", 9), anchor="w")
        sub.pack(fill="x")
        return val, meter, sub

    def _set_meter(self, meter, ratio):
        meter.delete("all")
        r = 0.0 if ratio <= 0 else (1.0 if ratio >= 1 else ratio)
        if r > 0:
            meter.create_rectangle(0, 0, max(2, int(self.METER_W * r)), 10,
                                   fill=self.C["stat_bar"], outline="")

    def _tick(self):
        """一次采样：更新三张卡片与折线图。"""
        c = self.C
        cpu = sysinfo.cpu_percent()
        if cpu is None:
            cpu = 0.0
        self._history.append(cpu)
        del self._history[:-self.HISTORY]

        mem = sysinfo.mem_info()
        speed = sysinfo.net_speed()

        self._cpu_val.config(text=f"{cpu:.0f}%")
        self._set_meter(self._cpu_meter, cpu / 100.0)
        self._cpu_sub.config(text=f"逻辑处理器 {sysinfo.cpu_count()} 个")

        if mem:
            self._mem_val.config(text=sysinfo.fmt_bytes(mem["avail"]))
            self._set_meter(self._mem_meter,
                            (mem["used"] / mem["total"]) if mem["total"] else 0)
            self._mem_sub.config(
                text=f"已用 {sysinfo.fmt_bytes(mem['used'])} / "
                     f"共 {sysinfo.fmt_bytes(mem['total'])}（{mem['load']}%）")
        else:
            self._mem_val.config(text="—")
            self._mem_sub.config(text="无法读取内存信息")

        if speed:
            down, up, ifname = speed
            self._net_val.config(text="↓ " + sysinfo.fmt_speed(down))
            self._set_meter(self._net_meter, max(down, up, 1.0) / (10 * 1024 * 1024))
            rx, tx, _ = sysinfo.net_counters()
            who = f"{ifname} · " if ifname else ""
            self._net_sub.config(text=f"↑ {sysinfo.fmt_speed(up)}\n"
                                      f"{who}累计 ↓{sysinfo.fmt_bytes(rx)} ↑{sysinfo.fmt_bytes(tx)}")
        else:
            self._net_val.config(text="↓ —")
            self._net_sub.config(text="采样中…")

        self._draw_graph()
        self.app.update_topbar(f"CPU {cpu:.0f}% · "
                               + (f"内存可用 {sysinfo.fmt_bytes(mem['avail'])}" if mem else ""))
        self._job = self.after(self.INTERVAL, self._tick)

    def _draw_graph(self):
        """画 CPU 折线图（含 0/50/100% 网格线）。"""
        c = self.C
        cv = self.graph
        w = max(240, cv.winfo_width())
        h = self.GRAPH_H
        cv.configure(width=w)
        cv.delete("all")
        y0, y1 = 12, h - 12          # 留上下边距
        span = y1 - y0
        # 网格线
        for pct in (0, 50, 100):
            y = y1 - span * pct / 100.0
            cv.create_line(40, y, w - 8, y, fill=c["divider"])
            cv.create_text(34, y, text=f"{pct}%", anchor="e",
                           fill=c["sidebar_muted"], font=("Microsoft YaHei", 7))
        hist = self._history
        if len(hist) >= 2:
            step = (w - 48) / float(self.HISTORY - 1)
            pts = []
            for i, v in enumerate(hist):
                x = 40 + i * step
                y = y1 - span * min(100.0, max(0.0, v)) / 100.0
                pts.append((x, y))
            poly = list(pts) + [(pts[-1][0], y1), (pts[0][0], y1)]
            cv.create_polygon(poly, fill=c["stat_bar_bg"], outline="")
            cv.create_line([p for pt in pts for p in pt], fill=c["stat_bar"], width=2)
            cv.create_oval(pts[-1][0] - 3, pts[-1][1] - 3,
                           pts[-1][0] + 3, pts[-1][1] + 3,
                           fill=c["stat_bar"], outline="")
            cv.create_text(w - 8, 12, text=f"当前 {hist[-1]:.0f}%", anchor="ne",
                           fill=c["text"], font=("Microsoft YaHei", 9, "bold"))
        else:
            cv.create_text(w // 2, h // 2, text="采集中…", fill=c["sidebar_muted"],
                           font=("Microsoft YaHei", 10))

    def destroy(self):
        """页面销毁时停掉定时任务，避免回调打到已销毁的控件。"""
        job = getattr(self, "_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._job = None
        super().destroy()


# ======================================================================
# 5. 设置页
# ======================================================================
class SettingsPage(BasePage):
    key = "settings"
    title = "⚙ 设置"
    subtitle = "外观、桌面宠物与侧边栏"

    def _build(self):
        c = self.C
        self.body = tk.Frame(self, bg=c["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=12)

        self._section("外观主题")
        self.var = tk.StringVar(value=self.app.theme_name)
        for key in ("light", "dark"):
            tk.Radiobutton(self.body, text=THEME_NAMES[key], value=key,
                           variable=self.var, font=("Microsoft YaHei", 10),
                           bg=c["app_bg"], fg=c["text"],
                           selectcolor=c["panel_bg"],
                           activebackground=c["app_bg"],
                           activeforeground=c["text"],
                           highlightthickness=0, bd=0,
                           command=self._pick_theme).pack(anchor="w", pady=2)
        chips = tk.Frame(self.body, bg=c["app_bg"])
        chips.pack(anchor="w", pady=8)
        for name, key in (("背景", "app_bg"), ("磁贴", "panel_bg"),
                          ("卡片", "card_bg"), ("强调", "accent")):
            tk.Label(chips, text=name, width=6, font=("Microsoft YaHei", 8),
                     bg=c[key], fg=c["text"], padx=4, pady=6).pack(side="left", padx=3)

        self._section("桌面宠物")
        pet_row = tk.Frame(self.body, bg=c["app_bg"])
        pet_row.pack(anchor="w", pady=4)
        pet_text = "🐙 收起宠物" if self.app.pet_active() else "🐙 召唤宠物"
        pet_btn = tk.Button(pet_row, text=pet_text, font=("Microsoft YaHei", 10),
                            relief="flat", bg=c["panel_bg"], fg=c["text"],
                            activebackground=c["panel_active"], bd=0,
                            padx=12, pady=4, command=lambda: self._pet(pet_btn))
        pet_btn.pack(side="left")
        tk.Label(pet_row, text="墨墨会悬浮在桌面上，可拖动、点击会笑",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=10)

        self._section("侧边栏")
        sb_row = tk.Frame(self.body, bg=c["app_bg"])
        sb_row.pack(anchor="w", pady=4)
        tk.Button(sb_row, text="⇔ 折叠 / 展开", font=("Microsoft YaHei", 10),
                  relief="flat", bg=c["panel_bg"], fg=c["text"],
                  activebackground=c["panel_active"], bd=0, padx=12, pady=4,
                  command=self.app.toggle_sidebar).pack(side="left")
        tk.Label(sb_row, text="折叠后只显示图标，状态会自动记住",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=10)

        self._section("关于")
        tk.Label(self.body,
                 text=f"墨墨桌面管理助手 {APP_VERSION}\n"
                      "纯 Python 标准库实现（tkinter），无需任何第三方依赖。",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=("Microsoft YaHei", 9), justify="left",
                 anchor="w").pack(anchor="w")

        self.app.update_topbar(f"当前主题：{THEME_NAMES[self.app.theme_name]}")

    def _section(self, text):
        c = self.C
        tk.Label(self.body, text=text, bg=c["app_bg"], fg=c["text"],
                 font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        hline(self.body, c["divider"], pady=(0, 8))

    def _pick_theme(self):
        self.app._apply_theme(self.var.get())

    def _pet(self, btn):
        self.app._toggle_pet()
        btn.config(text="🐙 收起宠物" if self.app.pet_active() else "🐙 召唤宠物")


PAGES = (DesktopPage, CategoriesPage, StatsPage, SystemPage, SettingsPage)
PAGE_BY_KEY = {p.key: p for p in PAGES}
