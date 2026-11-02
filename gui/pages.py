# -*- coding: utf-8 -*-
"""右侧主内容区的页面：首页（桌面网格）/ 分类 / 统计 / 设置。

每个页面都是 tk.Frame，由 gui.app.App（主框架）按需创建并切换。
页面统一通过 self.app 访问主题配色、配置和桌宠等全局能力。
"""
import calendar
import datetime as dt
import os
import tkinter as tk
from tkinter import messagebox

from core.scanner import scan_desktop, get_desktop_paths
from core.icons import icon_png
from core import sysinfo
from core import countdown as cd
from core import hotkey
from core.undo import UndoStack
from gui import category_ops
from gui.theme import (DEFAULT_THEME, THEMES, THEME_NAMES, get_theme, style_menu)
from gui.fonts import font
from gui.widgets import (open_target, make_photo, rounded_rect, short_name,
                         center_window, hline, stat_bar, shrink,
                         ModernButton, hover_card)

# ---- 磁贴尺寸 ----
TILE_SIZE = 96      # 单元格宽度（px）
TILE_H = 108        # 单元格高度（px）（磁贴统一尺寸，hover 放大不会推挤邻居）
COLS = 8            # 默认每行数量（窗口宽度变化时会自适应）
MIN_COLS = 4        # 每行最少数量
MAX_COLS = 16       # 每行最多数量（窗口放大时自动增加）
TILE_PADX = 8
TILE_PADY = 8
ICON_SIZE = 48      # 磁贴图标尺寸（px）
ICONS_PER_TICK = 6  # 每帧最多提取几个系统图标（懒加载，防止首屏卡顿）
TILE_HOVER = 6      # 鼠标悬停时磁贴放大的像素数

# ---- 分类文件夹 3×3 预览 ----
FOLDER_PREVIEW = 70
PREVIEW_ICON = 20
PREVIEW_GAP = 2
PREVIEW_PAD = 3
PREVIEW_COLS = 3
MAX_PREVIEW = PREVIEW_COLS ** 2

UNDO_DEPTH = 10         # 「撤销上一步」最多记住几步整理操作

APP_VERSION = "v1.0"
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
        self.items = list(items)

        self.head = tk.Label(self, text="", font=font(14, "bold"),
                             bg=c["dialog_bg"], fg=c["text"])
        self.head.pack(pady=10)
        self.frame = tk.Frame(self, bg=c["dialog_bg"])
        self.frame.pack(fill="both", expand=True, padx=10, pady=5)
        self._render()

    def _render(self):
        """重建网格内容（移出某项后原地刷新，不再直接关窗）。"""
        c = self.C
        for w in self.frame.winfo_children():
            w.destroy()
        self._photos = []
        items = self.items
        self.head.config(text=f"📁 {self.category}（{len(items)} 项）")
        self.frame.grid_columnconfigure(tuple(range(COLS)), weight=1)

        if not items:
            tk.Label(self.frame, text="空空如也，右键桌面上的项目可移入此分类",
                     bg=c["dialog_bg"], fg=c["text_muted"]).grid(
                row=0, column=0, columnspan=COLS, pady=40)
            return

        for idx, item in enumerate(items):
            icon = make_photo(icon_png(item.path, ICON_SIZE), self._photos)
            if icon:
                btn = tk.Button(self.frame, image=icon,
                                text=short_name(item.display_name),
                                compound="top", font=font(9),
                                width=90, height=86, relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            else:
                btn = tk.Button(self.frame, text=f"📄\n{short_name(item.display_name)}",
                                font=font(9),
                                width=10, height=4, relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            btn.grid(row=idx // COLS, column=idx % COLS, padx=6, pady=6)
            menu = tk.Menu(btn, tearoff=0)
            menu.add_command(label="打开", command=lambda p=item.path: open_target(p))
            menu.add_command(label="移出分类",
                             command=lambda p=item.path: self._remove(p))
            style_menu(menu, c)
            btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    def _remove(self, item_path: str):
        """把项目移出当前分类：窗口留着，方便继续整理下一项。"""
        self.cfg.unassign(item_path)
        self.items = [i for i in self.items if i.path != item_path]
        self._render()
        if self.on_change:
            self.on_change()


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

    # 页面被切走 / 切回时的钩子：默认就是刷新一次，
    # 子类可以改成更省的做法（比如首页不重扫桌面、监控页停掉定时器）。
    def on_show(self):
        self.refresh()

    def on_hide(self):
        pass

    def _toolbar(self, buttons, primary=None):
        """页面顶部的一条胶囊渐变按钮（(文字, 命令) 或 (图标, 文字, 命令)）。

        primary 传文字时，那个按钮会用强调色渐变（视觉主操作）。
        """
        c = self.C
        bar = tk.Frame(self, bg=c["app_bg"])
        bar.pack(fill="x", padx=16, pady=(12, 6))
        for item in buttons:
            icon = None
            if len(item) == 3:
                icon, text, cmd = item
            else:
                text, cmd = item
            btn = ModernButton(bar, text=text, command=cmd, c=c, icon=icon,
                               primary=(text == primary))
            btn.pack(side="left", padx=(0, 10))
        return bar


# ======================================================================
# 1. 首页：桌面网格
# ======================================================================
class DesktopPage(BasePage):
    key = "home"
    title = "桌面首页"
    subtitle = "像手机桌面一样管理你的桌面图标"

    def __init__(self, master, app):
        self.items = []
        self.cols = COLS
        self._cols_cfg = 0
        self._relayout_job = None
        self._scrollable = False
        self.selected = set()      # 多选：存桌面项路径
        self._anchor = None        # Shift 连选的起点
        self._undo_stack = UndoStack(UNDO_DEPTH)   # 最近几步整理（可连续撤销）
        self._visible_items = []   # 当前过滤后真正显示在网格里的项
        self._icon_queue = []      # 待加载图标队列（懒加载，避免首屏卡顿）
        self._icon_job = None
        super().__init__(master, app)

    def _build(self):
        c = self.C
        self._toolbar([
            ("refresh", "刷新 (F5)", self.refresh),
            ("folder", "新建分类", self._add_category),
            ("grid", "管理分类", self._manage_categories),
            ("monitor", "打开桌面", self._open_desktop),
            ("pet", "桌面宠物" if not self.app.pet_active() else "收起宠物",
             self._pet_cmd),
        ], primary="新建分类")
        # 批量操作条：有选中时才显形（占位框常驻，保证 pack 顺序稳定）
        self.sel_host = tk.Frame(self, bg=c["app_bg"])
        self.sel_host.pack(fill="x", padx=16, after=self.winfo_children()[0])
        self._build_selbar()
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

    def on_show(self):
        """切回首页只重排已有数据，不重新扫描桌面（F5 / 刷新按钮才重扫）。"""
        self.refresh(rescan=not self.items)

    def _pet_cmd(self):
        self.app._toggle_pet()

    # ---- 多选 / 批量整理 ----
    def _build_selbar(self):
        """选中若干磁贴后出现的批量操作条。"""
        c = self.C
        bar = tk.Frame(self.sel_host, bg=c["app_bg"])
        self.selbar = bar
        self.sel_label = tk.Label(bar, text="", bg=c["app_bg"], fg=c["accent"],
                                  font=font(10, "bold"))
        self.sel_label.pack(side="left", padx=(0, 10))

        self.sel_menu = tk.Menu(self, tearoff=0)
        style_menu(self.sel_menu, c)
        ModernButton(bar, text="移入分类 ▾", command=self._popup_move, c=c,
                     icon="folder", primary=True).pack(side="left", padx=(0, 8))
        ModernButton(bar, text="移出分类", command=self._unassign_selected,
                     c=c, icon="close").pack(side="left", padx=(0, 8))
        ModernButton(bar, text="撤销上一步", command=self._undo,
                     c=c, icon="refresh").pack(side="left", padx=(0, 8))
        ModernButton(bar, text="取消选择", command=self._clear_selection,
                     c=c, icon="close").pack(side="left")

    def _popup_move(self):
        if not self.selected:
            messagebox.showinfo("移入分类",
                                "还没选中项目～\n"
                                "Ctrl + 点击磁贴可多选，Shift + 点击可连选一片。",
                                parent=self.app)
            return
        menu = self.sel_menu
        menu.delete(0, "end")
        for cat in self.cfg.categories:
            menu.add_command(label=f"移入「{cat}」（{len(self.selected)} 项）",
                             command=lambda cc=cat: self._assign_selected(cc))
        if not self.cfg.categories:
            menu.add_command(label="（还没有分类）", state="disabled")
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _update_selbar(self):
        """选中项 > 0 时显形；没有选中但还有可撤销的步骤时也留着，
        否则「批量移入 → 选择被清空」之后就再也找不到撤销按钮了。
        """
        n = len(self.selected)
        undo = len(self._undo_stack)
        shown = getattr(self, "_selbar_shown", False)
        if n:
            text = f"已选 {n} 项"
            if undo:
                text += f" · 可撤销 {undo} 步"
        elif undo:
            text = f"上次整理了 {self._undo_stack.last_size} 项 · 可撤销 {undo} 步"
        else:
            text = ""
        self.sel_label.config(text=text)
        want = bool(n or undo)
        if want and not shown:
            self.selbar.pack(fill="x", pady=(0, 6))
            self._selbar_shown = True
        elif not want and shown:
            self.selbar.pack_forget()
            self._selbar_shown = False

    def _toggle_select(self, path, on=None):
        """Ctrl + 点击：把一项加入 / 移出选择。"""
        if on is None:
            on = path not in self.selected
        if on:
            self.selected.add(path)
            self._anchor = path
        else:
            self.selected.discard(path)
        self._refresh_selection()

    def _range_select(self, path):
        """Shift + 点击：从上一个锚点连选到这一项。

        区间只能在「当前可见」的项里算：搜索过滤掉的项不在网格上，把它们
        悄悄加进选中集会让「已选 N 项」和实际看到的高亮对不上。
        """
        paths = [i.path for i in (self._visible_items or self.items)]
        if self._anchor in paths and path in paths:
            a, b = paths.index(self._anchor), paths.index(path)
            for p in paths[min(a, b):max(a, b) + 1]:
                self.selected.add(p)
        else:
            self.selected.add(path)
        self._anchor = path
        self._refresh_selection()

    def _clear_selection(self):
        self.selected.clear()
        self._anchor = None
        self._refresh_selection()

    def _drop_from_selection(self, *paths):
        """单项操作后把这一项移出选中集：它已经不在未分类网格里了，
        留着会让「已选 N 项」虚高。
        """
        for p in paths:
            self.selected.discard(p)
        if self._anchor in paths:
            self._anchor = None

    def _refresh_selection(self):
        """只改磁贴的选中边框，不整页重建（避免闪烁、也保住滚动位置）。"""
        for slot in self.grid_frame.winfo_children():
            for w in slot.winfo_children():
                path = getattr(w, "_item_path", None)
                if not path:
                    continue
                on = path in self.selected
                try:
                    w.configure(highlightthickness=2 if on else 0,
                                highlightbackground=self.C["accent"],
                                highlightcolor=self.C["accent"])
                except tk.TclError:
                    pass
        self._update_selbar()

    def _snapshot(self, paths):
        """记一步可撤销的操作（各项操作前的旧分类），见 core/undo.py。"""
        self._undo_stack.push([(p, self.cfg.get_category(p)) for p in paths])

    def _assign_selected(self, category):
        paths = list(self.selected)
        if not paths:
            return
        self._snapshot(paths)
        self.cfg.assign_batch(paths, category)
        self._clear_selection()
        self.refresh(rescan=False)

    def _unassign_selected(self):
        paths = list(self.selected)
        if not paths:
            return
        self._snapshot(paths)
        self.cfg.unassign_batch(paths)
        self._clear_selection()
        self.refresh(rescan=False)

    def _undo(self):
        """撤销上一步操作（把各项恢复成原来的分类），可连续多步。"""
        step = self._undo_stack.pop()
        if step is None:
            messagebox.showinfo("撤销", "还没有可撤销的操作～", parent=self.app)
            return
        for cat, paths in self._undo_stack.group(step).items():
            if cat:
                self.cfg.assign_batch(paths, cat)
            else:
                self.cfg.unassign_batch(paths)
        self.selected.clear()
        self._anchor = None
        self.refresh(rescan=False)
        self._update_selbar()

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
        self.refresh(rescan=False)      # 只是换列数，桌面内容没变，不用重扫

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
    def refresh(self, rescan=True):
        # 重建网格：旧队列作废（磁贴已经没了，别再往销毁的控件上塞图标）
        self._icon_queue = []
        if self._icon_job is not None:
            try:
                self.after_cancel(self._icon_job)
            except tk.TclError:
                pass
            self._icon_job = None
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self._photos = []
        if rescan or not self.items:
            self.items = scan_desktop()
        # 旧配置（按文件名归类）就地升级成按路径；顺手清掉改名/移动留下的死条目
        self.cfg.migrate_assignments(self.items)
        self.cfg.prune_assignments([i.path for i in self.items])
        for item in self.items:
            item.category = self.cfg.get_category(item.path, item.name)

        # 全局搜索：按名称 / 分类过滤（搜索时不重新扫描桌面，避免卡顿）
        query = (getattr(self.app, "query", "") or "").strip().lower()
        items = self.items
        if query:
            items = [i for i in items
                     if query in (i.name or "").lower()
                     or query in (i.display_name or "").lower()
                     or query in (i.category or "").lower()]
        # 记下这一轮真正画出来的项：Shift 连选的区间以它为准
        self._visible_items = items
        categories = [cat for cat in self.cfg.categories
                      if not query or query in cat.lower()
                      or any(i.category == cat for i in items)]

        w = self.canvas.winfo_width()
        if w > 1:
            self.canvas.itemconfigure(self._grid_win, width=w)
            self.cols = self._cols_for_width(w)

        total = len(categories) + sum(1 for i in items if not i.category)
        cols = self.cols
        self._configure_columns(cols)

        if total == 0 and query:
            box = tk.Frame(self.grid_frame, bg=self.C["app_bg"])
            box.pack(pady=60)
            tk.Label(box, text="🔍", bg=self.C["app_bg"], fg=self.C["text"],
                     font=font(28)).pack()
            tk.Label(box, text=f"没有找到与「{self.app.query}」匹配的项目",
                     bg=self.C["app_bg"], fg=self.C["sidebar_muted"],
                     font=font(11)).pack(pady=(6, 0))
            self._on_grid_configure()
            self.app.update_topbar(f"搜索「{self.app.query}」· 0 个结果")
            return

        idx = 0
        for cat in categories:
            count = sum(1 for i in items if i.category == cat)
            row, col = self._cell(idx, cols, total)
            self._make_folder_tile(row, col, cat, count)
            idx += 1
        for item in items:
            if not item.category:
                row, col = self._cell(idx, cols, total)
                self._make_item_tile(row, col, item)
                idx += 1
        self._on_grid_configure()
        # 网格已经出来了，再慢慢补图标（用户先看到内容，不会干等）
        if self._icon_queue and self._icon_job is None:
            self._icon_job = self.after(30, self._pump_icons)
        if query:
            self.app.update_topbar(f"搜索「{self.app.query}」· {total} 个结果"
                                   f"（共 {len(self.items)} 项）")
        else:
            self.app.update_topbar(self.subtitle + f" · 共 {len(self.items)} 项")

    def open_first(self):
        """回车：打开搜索结果里的第一个（分类窗口 / 直接启动）。"""
        query = (getattr(self.app, "query", "") or "").strip().lower()
        if not query:
            return False
        for cat in self.cfg.categories:
            if query in cat.lower():
                self._open_category(cat)
                return True
        for item in self.items:
            if (query in (item.name or "").lower()
                    or query in (item.display_name or "").lower()
                    or query in (item.category or "").lower()):
                if item.category:
                    self._open_category(item.category)
                else:
                    open_target(item.path)
                return True
        return False

    def _slot(self, row, col):
        """固定尺寸的槽位：磁贴在里面居中，hover 放大时不会推动邻居。"""
        slot = tk.Frame(self.grid_frame,
                        width=TILE_SIZE + TILE_PADX * 2,
                        height=TILE_H + TILE_PADY * 2, bg=self.C["app_bg"])
        slot.grid_propagate(False)
        slot.grid(row=row, column=col)
        return slot

    def _shadow(self, slot):
        """磁贴下方那一层「淡阴影」，hover 时才显形。"""
        sh = tk.Frame(slot, width=TILE_SIZE + TILE_HOVER, bg=self.C["app_bg"],
                      height=TILE_H + TILE_HOVER)
        sh.place(relx=0.5, rely=0.5, anchor="center", y=3)
        return sh

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

        slot = self._slot(row, col)
        shadow = self._shadow(slot)
        frame = tk.Frame(slot, width=TILE_SIZE, height=TILE_H,
                         bg=c["folder_bg"], highlightthickness=0)
        frame.pack_propagate(False)      # 磁贴尺寸固定，内容不把它撑变形
        frame.place(relx=0.5, rely=0.5, anchor="center",
                    width=TILE_SIZE, height=TILE_H)

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
                               font=font(12, "bold"))

        label = tk.Label(frame, text=f"{short_name(category)} ({count})",
                         bg=c["folder_bg"], fg=c["text"],
                         font=font(9), cursor="hand2",
                         wraplength=TILE_SIZE - 10, justify="center")
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
        enter, leave = hover_card(frame, (canvas, label), c,
                                  c["folder_bg"], c["folder_bg_hover"],
                                  grow=TILE_HOVER, shadow=shadow, slot=slot)
        for w in (frame, canvas, label):
            w.bind("<Button-1>", open_cmd)
            w.bind("<Button-3>", popup)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _make_item_tile(self, row, col, item):
        c = self.C
        slot = self._slot(row, col)
        shadow = self._shadow(slot)
        name = short_name(item.display_name)
        emoji = {"dir": "🗂", "shortcut": "🧩", "file": "📄"}.get(item.kind, "📄")
        # 先占位（emoji + 透明图保证尺寸稳定），真实图标由 _pump_icons 异步补上
        blank = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
        self._photos.append(blank)
        btn = tk.Button(slot, image=blank, text=f"{emoji}\n{name}",
                        compound="top", font=font(9),
                        width=TILE_SIZE, height=TILE_H, relief="flat",
                        bg=c["panel_bg"], fg=c["text"],
                        activebackground=c["panel_active"],
                        activeforeground=c["text"])
        btn.place(relx=0.5, rely=0.5, anchor="center",
                  width=TILE_SIZE, height=TILE_H)
        btn._item_path = item.path        # 选中态用路径找回磁贴
        if item.path in self.selected:
            btn.configure(highlightthickness=2, highlightbackground=c["accent"],
                          highlightcolor=c["accent"])
        menu = tk.Menu(btn, tearoff=0)
        if len(self.selected) > 1 and item.path in self.selected:
            for cat in self.cfg.categories:
                menu.add_command(label=f"把选中的 {len(self.selected)} 项移入「{cat}」",
                                 command=lambda cc=cat: self._assign_selected(cc))
            menu.add_separator()
        for cat in self.cfg.categories:
            menu.add_command(label=f"移入「{cat}」",
                             command=lambda p=item.path, cc=cat: self._assign(p, cc))
        menu.add_separator()
        menu.add_command(label="移出当前分类",
                         command=lambda p=item.path: self._unassign(p))
        menu.add_separator()
        menu.add_command(label="打开", command=lambda p=item.path: open_target(p))
        style_menu(menu, c)
        btn.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))
        btn.bind("<Button-1>", lambda e, p=item.path: self._on_tile_click(e, p))
        enter, leave = hover_card(btn, (), c, c["panel_bg"], c["panel_active"],
                                  grow=TILE_HOVER, shadow=shadow, slot=slot)
        btn.bind("<Enter>", enter)
        btn.bind("<Leave>", leave)
        # 排进图标加载队列（取不到系统图标时就一直用 emoji 占位）
        self._queue_icon(item.path, ICON_SIZE, self._tile_icon_setter(btn, name))

    # ---- 图标懒加载 ----
    def _queue_icon(self, path, size, setter):
        self._icon_queue.append((path, size, setter))

    @staticmethod
    def _tile_icon_setter(btn, name):
        def set_icon(photo):
            try:
                btn.configure(image=photo, text=name)
            except tk.TclError:
                pass          # 磁贴已经在这次渲染里被销毁了
        return set_icon

    def _pump_icons(self):
        """每帧只提取几个图标：桌面项很多时不会一上来卡住整个界面。"""
        todo = self._icon_queue
        if not todo:
            self._icon_job = None
            return
        for _ in range(ICONS_PER_TICK):
            if not todo:
                break
            path, size, setter = todo.pop(0)
            photo = make_photo(icon_png(path, size), self._photos)
            if photo is not None:
                setter(photo)
        self._icon_job = self.after(1, self._pump_icons)

    def _on_tile_click(self, event, path):
        """左键：Ctrl / Shift 是框选，平时直接打开（有选中时改为增减选择）。"""
        state = getattr(event, "state", 0)
        if state & 0x0004:                       # Control
            self._toggle_select(path)
        elif state & 0x0001:                     # Shift
            self._range_select(path)
        elif self.selected:
            self._toggle_select(path)
        else:
            open_target(path)

    # ---- 动作 ----
    def _open_category(self, category):
        items = [i for i in self.items if i.category == category]
        CategoryWindow(self.app, category, items, self.cfg,
                       on_change=lambda: self.refresh(rescan=False), theme=self.C)

    def _assign(self, path, category):
        self._snapshot([path])
        self.cfg.assign(path, category)
        self._drop_from_selection(path)
        self.refresh(rescan=False)
        self._update_selbar()

    def _unassign(self, path):
        self._snapshot([path])
        self.cfg.unassign(path)
        self._drop_from_selection(path)
        self.refresh(rescan=False)
        self._update_selbar()

    # ---- 分类增删改：统一走 gui/category_ops 的公共层 ----
    def _add_category(self):
        if category_ops.create_category(self.cfg, self.app) is not None:
            self.refresh(rescan=False)

    def _rename_category(self, category):
        if category_ops.rename_category(self.cfg, category, self.app) is not None:
            self.refresh(rescan=False)

    def _delete_category(self, category):
        if category_ops.delete_category(self.cfg, category, self.app):
            self.refresh(rescan=False)

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
                 font=font(10), bg=c["dialog_bg"], fg=c["text"],
                 anchor="w").pack(fill="x")

        body = tk.Frame(top, bg=c["dialog_bg"])
        body.pack(fill="both", expand=True, pady=6)
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        lst = tk.Listbox(body, font=font(10), relief="solid",
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
            name = category_ops.create_category(self.cfg, win)
            if name is None:
                return
            reload(self.cfg.categories.index(name))
            self.refresh(rescan=False)

        def do_rename():
            old = selected()
            if old is None:
                messagebox.showinfo("提示", "请先选择一个分类", parent=win)
                return
            new = category_ops.rename_category(self.cfg, old, win)
            if new is None:
                return
            reload(self.cfg.categories.index(new))
            self.refresh(rescan=False)

        def do_delete():
            cat = selected()
            if cat is None:
                messagebox.showinfo("提示", "请先选择一个分类", parent=win)
                return
            if category_ops.delete_category(self.cfg, cat, win):
                reload()
                self.refresh(rescan=False)

        bar = tk.Frame(win, bg=c["dialog_bg"])
        bar.pack(fill="x", padx=12, pady=8)
        for icon, text, cmd, primary in (
                ("folder", "新建", do_add, True),
                ("gear", "重命名", do_rename, False),
                ("close", "删除", do_delete, False)):
            ModernButton(bar, text=text, command=cmd, c=c, icon=icon,
                         primary=primary, height=30, padx=13).pack(
                side="left", padx=4)
        ModernButton(bar, text="关闭", command=win.destroy, c=c,
                     height=30).pack(side="right")

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
    title = "分类管理"
    subtitle = "新建、重命名、删除分类，并查看每个分类里的内容"

    def _build(self):
        c = self.C
        self._toolbar([("folder", "新建分类", self._add),
                       ("refresh", "刷新", self.refresh)], primary="新建分类")
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
            item.category = self.cfg.get_category(item.path, item.name)

        if not self.cfg.categories:
            tk.Label(self.body, text="还没有分类，点右上角「➕ 新建分类」创建第一个",
                     bg=c["app_bg"], fg=c["text_muted"],
                     font=font(11)).pack(pady=40)
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
                 font=font(12, "bold"), anchor="w").pack(fill="x")
        names = "、".join(short_name(i.display_name, 10) for i in inner[:6])
        if len(inner) > 6:
            names += f" 等 {len(inner)} 项"
        tk.Label(mid, text=names if names else "（空分类）",
                 bg=c["card_bg"], fg=c["sidebar_muted"],
                 font=font(9), anchor="w").pack(fill="x")

        btns = tk.Frame(card, bg=c["card_bg"])
        btns.pack(side="right")
        for text, cmd in (("打开", lambda: self._open(category)),
                          ("重命名", lambda: self._rename(category)),
                          ("删除", lambda: self._delete(category))):
            tk.Button(btns, text=text, font=font(9),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"], bd=0,
                      padx=10, pady=3, command=cmd).pack(side="left", padx=3)

    def _open(self, category):
        items = [i for i in self.items if i.category == category]
        CategoryWindow(self.app, category, items, self.cfg,
                       on_change=self.refresh, theme=self.C)

    def _add(self):
        if category_ops.create_category(self.cfg, self.app) is not None:
            self.refresh()

    def _rename(self, old):
        if category_ops.rename_category(self.cfg, old, self.app) is not None:
            self.refresh()

    def _delete(self, category):
        if category_ops.delete_category(self.cfg, category, self.app):
            self.refresh()


# ======================================================================
# 3. 统计页
# ======================================================================
class StatsPage(BasePage):
    key = "stats"
    title = "数据统计"
    subtitle = "桌面整理情况的概览"

    def _build(self):
        self._toolbar([("refresh", "刷新", self.refresh)])
        self.body = tk.Frame(self, bg=self.C["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.refresh()

    def refresh(self):
        c = self.C
        for w in self.body.winfo_children():
            w.destroy()
        items = scan_desktop()
        for i in items:
            i.category = self.cfg.get_category(i.path, i.name)
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
                     font=font(20, "bold")).pack()
            tk.Label(card, text=label, bg=c["card_bg"], fg=c["sidebar_muted"],
                     font=font(9)).pack()

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
                 font=font(11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        hline(self.body, c["divider"], pady=(0, 8))

    def _row(self, name, n, total):
        c = self.C
        row = tk.Frame(self.body, bg=c["app_bg"])
        row.pack(fill="x", pady=3)
        tk.Label(row, text=name, bg=c["app_bg"], fg=c["text"],
                 font=font(10), width=12, anchor="w").pack(side="left")
        stat_bar(row, (n / total) if total else 0, c, width=260, height=10)
        pct = f"{n / total * 100:.0f}%" if total else "0%"
        tk.Label(row, text=f"{n} 项 · {pct}", bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=10)


# ======================================================================
# 4. 系统监控页：CPU / 内存 / 网速（每秒刷新）
# ======================================================================
class SystemPage(BasePage):
    key = "system"
    title = "系统监控"
    subtitle = "CPU 占用率、内存剩余与实时网速"
    INTERVAL = 1000        # 刷新间隔（毫秒）
    HISTORY = 60           # 折线图保留的采样点数
    GRAPH_H = 130          # 折线图高度
    METER_W = 210          # 卡片内进度条宽度

    def _build(self):
        c = self.C
        self._history = []
        self._job = None

        bar = self._toolbar([("refresh", "立即刷新", self._tick)])
        tk.Label(bar, text="每 1 秒自动刷新 · 数据来自 Windows 系统接口",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left")

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
                 font=font(11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        self.graph = tk.Canvas(body, height=self.GRAPH_H, bg=c["card_bg"],
                               highlightthickness=1,
                               highlightbackground=c["divider"])
        self.graph.pack(fill="x")

        sysinfo.prime()                       # 建立采样基准
        self._draw_graph()                    # 先画空网格

    def on_show(self):
        """切回本页时重启采样（切走时已停掉，不在后台空转）。"""
        self._start_timer()

    def on_hide(self):
        self._stop_timer()

    def _start_timer(self):
        if self._job is None:
            self._tick()
        return

    def _stop_timer(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _card(self, parent, col, title):
        """一张指标卡：标题 + 大数值 + 进度条 + 补充说明。"""
        c = self.C
        card = tk.Frame(parent, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=14, pady=12)
        card.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")
        tk.Label(card, text=title, bg=c["card_bg"], fg=c["sidebar_muted"],
                 font=font(9), anchor="w").pack(fill="x")
        val = tk.Label(card, text="—", bg=c["card_bg"], fg=c["accent"],
                       font=font(20, "bold"), anchor="w")
        val.pack(fill="x", pady=(4, 2))
        meter = tk.Canvas(card, width=self.METER_W, height=10,
                          bg=c["stat_bar_bg"], highlightthickness=0, bd=0)
        meter.pack(anchor="w", pady=4)
        sub = tk.Label(card, text="", bg=c["card_bg"], fg=c["sidebar_muted"],
                       font=font(9), anchor="w")
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
                           fill=c["sidebar_muted"], font=font(7))
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
                           fill=c["text"], font=font(9, "bold"))
        else:
            cv.create_text(w // 2, h // 2, text="采集中…", fill=c["sidebar_muted"],
                           font=font(10))

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
# 5. 专属倒计时（倒数日）
# ======================================================================
class CountdownDialog(tk.Toplevel):
    """新建 / 编辑一条倒计时的弹窗。"""

    WIDTH, HEIGHT = 430, 330

    def __init__(self, master, theme, item=None, on_save=None):
        super().__init__(master)
        c = theme
        self.C = c
        self.item = item or {}
        self.on_save = on_save
        self.title("编辑倒计时" if item else "新建倒计时")
        center_window(self, self.WIDTH, self.HEIGHT, master)
        self.configure(bg=c["dialog_bg"])
        self.transient(master)
        self.grab_set()

        tk.Label(self, text=self.title(), font=font(13, "bold"),
                 bg=c["dialog_bg"], fg=c["text"]).pack(pady=(14, 12))

        form = tk.Frame(self, bg=c["dialog_bg"])
        form.pack(fill="x", padx=20)

        self.var_title = tk.StringVar(value=self.item.get("title", ""))
        self.var_date = tk.StringVar(
            value=self.item.get("date") or cd.fmt_date(cd.today()))
        self.var_note = tk.StringVar(value=self.item.get("note", ""))
        self.var_repeat = tk.BooleanVar(value=bool(self.item.get("repeat")))

        self._row(form, "标题", self.var_title, 0)
        self._date_row(form, 1)
        self._row(form, "备注", self.var_note, 3)

        tk.Checkbutton(self, text="每年循环（生日 / 纪念日）",
                       variable=self.var_repeat,
                       font=font(9),
                       bg=c["dialog_bg"], fg=c["text"],
                       selectcolor=c["panel_bg"],
                       activebackground=c["dialog_bg"],
                       activeforeground=c["text"],
                       highlightthickness=0, bd=0).pack(anchor="w", padx=20, pady=(8, 0))

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=16)
        tk.Button(btns, text="保存", width=10, font=font(10),
                  relief="flat", bg=c["accent"], fg=c["accent_fg"],
                  activebackground=c["accent"], bd=0, padx=8, pady=4,
                  command=self._save).pack(side="left", padx=6)
        tk.Button(btns, text="取消", width=10, font=font(10),
                  relief="flat", bg=c["panel_bg"], fg=c["text"],
                  activebackground=c["panel_active"], bd=0, padx=8, pady=4,
                  command=self.destroy).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _row(self, parent, label, var, row):
        c = self.C
        tk.Label(parent, text=label, width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(10)).grid(row=row, column=0, pady=6)
        tk.Entry(parent, textvariable=var, width=28,
                 font=font(10), relief="flat",
                 bg=c["panel_bg"], fg=c["text"],
                 insertbackground=c["text"],
                 highlightthickness=1,
                 highlightbackground=c["divider"]).grid(
            row=row, column=1, sticky="ew", pady=6, padx=(8, 0))
        parent.grid_columnconfigure(1, weight=1)

    def _date_row(self, parent, row):
        """日期改为年 / 月 / 日三个滚轮（Spinbox），天数上限随年月自动调整。"""
        c = self.C
        tk.Label(parent, text="日期", width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(10)).grid(row=row, column=0, pady=6)
        cell = tk.Frame(parent, bg=c["dialog_bg"])
        cell.grid(row=row, column=1, sticky="ew", pady=6, padx=(8, 0))

        today = cd.today()
        cur = cd.parse_date(self.item.get("date")) or today
        lo_year = min(1970, cur.year)

        kw = dict(font=font(11), width=5, justify="center",
                  relief="flat", bd=0, bg=c["panel_bg"], fg=c["text"],
                  buttonbackground=c["panel_bg"],
                  insertbackground=c["text"],
                  highlightthickness=1,
                  highlightbackground=c["divider"],
                  highlightcolor=c["accent"])

        self.var_y = tk.StringVar(value=str(cur.year))
        self.var_m = tk.StringVar(value=str(cur.month))
        self.var_d = tk.StringVar(value=str(cur.day))
        self.spin_y = tk.Spinbox(cell, from_=lo_year, to=today.year + 60,
                                 textvariable=self.var_y, **kw)
        self.spin_m = tk.Spinbox(cell, from_=1, to=12, wrap=True,
                                 textvariable=self.var_m, **kw)
        self.spin_d = tk.Spinbox(cell, from_=1, to=31, wrap=True,
                                 textvariable=self.var_d, **kw)
        # 三个滚轮都建好后才挂监听，否则构造 spinbox 时会提前触发回调
        for v in (self.var_y, self.var_m, self.var_d):
            v.trace_add("write", self._sync_date)

        self.spin_y.pack(side="left")
        tk.Label(cell, text="年", bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=(3, 8))
        self.spin_m.pack(side="left")
        tk.Label(cell, text="月", bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=(3, 8))
        self.spin_d.pack(side="left")
        tk.Label(cell, text="日", bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=(3, 8))

        tk.Button(cell, text="今天", font=font(9),
                  relief="flat", bg=c["panel_bg"], fg=c["sidebar_muted"],
                  activebackground=c["panel_active"], bd=0, padx=8, pady=3,
                  command=self._set_today).pack(side="left")

        self._week_label = tk.Label(parent, text="", bg=c["dialog_bg"],
                                    fg=c["sidebar_muted"],
                                    font=font(9))
        self._week_label.grid(row=row + 1, column=1, sticky="w", padx=(8, 0))
        self._sync_date()

    def _set_today(self):
        t = cd.today()
        self.var_y.set(str(t.year))
        self.var_m.set(str(t.month))
        self.var_d.set(str(t.day))

    def _sync_date(self, *_):
        """滚轮变化时重算：天数上限、纠正越界、同步完整日期与星期。"""
        if not hasattr(self, "spin_d"):
            return
        try:
            y = int(float(self.var_y.get()))
            m = int(float(self.var_m.get()))
            d = int(float(self.var_d.get()))
        except (ValueError, tk.TclError):
            return
        try:
            y_max = int(float(self.spin_y.cget("to")))
        except (TypeError, ValueError):
            y_max = 9999
        y = max(1970, min(y_max, y))
        m = max(1, min(12, m))
        last = calendar.monthrange(y, m)[1]
        self.spin_d.config(to=last)
        if d > last:
            d = last
            self.var_d.set(str(d))
        elif d < 1:
            d = 1
            self.var_d.set(str(d))
        try:
            date = dt.date(y, m, d)
        except ValueError:
            return
        self.var_date.set(cd.fmt_date(date))
        self._week_label.config(text=f"{cd.weekday_cn(date)} · 还有 "
                                     f"{cd.days_until(date, cd.today())} 天"
                                     if date > cd.today()
                                     else (cd.weekday_cn(date) + " · 就是今天"
                                           if date == cd.today()
                                           else cd.weekday_cn(date)))

    def _save(self):
        title = self.var_title.get().strip()
        if not title:
            messagebox.showwarning("提示", "请填写倒计时标题", parent=self)
            return
        d = cd.parse_date(self.var_date.get())
        if d is None:
            messagebox.showwarning("提示",
                                   "日期看不懂，请按 2026-12-20 这样的格式填写",
                                   parent=self)
            return
        if self.on_save:
            self.on_save({"title": title, "date": cd.fmt_date(d),
                          "note": self.var_note.get(),
                          "repeat": self.var_repeat.get()})
        self.destroy()


# ---- 番茄钟 ----
POMO_PRESETS = (15, 25, 45, 60, 90)   # 常用专注时长（分钟）


class PomodoroDialog(tk.Toplevel):
    """🍅 番茄钟：自定义专注时长 / 休息时长（滚轮选择）。"""

    W, H = 400, 300

    def __init__(self, master, app, on_start=None):
        super().__init__(master)
        self.app = app
        self.on_start = on_start
        c = self.C = get_theme(getattr(app, "theme_name", DEFAULT_THEME))
        self.title("🍅 番茄钟")
        center_window(self, self.W, self.H, master)
        self.configure(bg=c["dialog_bg"])
        self.resizable(False, False)

        tk.Label(self, text="🍅 自定义番茄钟",
                 font=font(14, "bold"),
                 bg=c["dialog_bg"], fg=c["text"]).pack(pady=(14, 4))
        tk.Label(self, text="选好时长后墨墨会捧着书陪你，头顶显示剩余时间",
                 font=font(9),
                 bg=c["dialog_bg"], fg=c["sidebar_muted"]).pack()

        grid = tk.Frame(self, bg=c["dialog_bg"])
        grid.pack(fill="x", padx=24, pady=(14, 6))
        grid.grid_columnconfigure(1, weight=1)

        kw = dict(font=font(11), width=5, justify="center",
                  relief="flat", bd=0, bg=c["panel_bg"], fg=c["text"],
                  buttonbackground=c["panel_bg"],
                  insertbackground=c["text"],
                  highlightthickness=1,
                  highlightbackground=c["divider"],
                  highlightcolor=c["accent"])

        tk.Label(grid, text="专注", anchor="w", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(10)).grid(row=0, column=0, pady=6)
        self.spin_focus = tk.Spinbox(grid, from_=app.POMO_MIN, to=app.POMO_MAX,
                                     **kw)
        self.spin_focus.delete(0, "end")
        self.spin_focus.insert(0, str(app.pomo_minutes))
        self.spin_focus.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(grid, text="分钟", bg=c["dialog_bg"], fg=c["text"],
                 font=font(10)).grid(row=0, column=2,
                                                    sticky="w", padx=6)

        tk.Label(grid, text="休息", anchor="w", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(10)).grid(row=1, column=0, pady=6)
        self.spin_break = tk.Spinbox(grid, from_=app.POMO_MIN, to=app.POMO_MAX,
                                     **kw)
        self.spin_break.delete(0, "end")
        self.spin_break.insert(0, str(app.pomo_break))
        self.spin_break.grid(row=1, column=1, sticky="w", padx=(8, 0))
        tk.Label(grid, text="分钟", bg=c["dialog_bg"], fg=c["text"],
                 font=font(10)).grid(row=1, column=2,
                                                    sticky="w", padx=6)

        preset = tk.Frame(self, bg=c["dialog_bg"])
        preset.pack(fill="x", padx=24, pady=(4, 6))
        tk.Label(preset, text="常用：", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left")
        for m in POMO_PRESETS:
            tk.Button(preset, text=f"{m} 分钟", font=font(9),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"], bd=0,
                      padx=8, pady=3,
                      command=lambda mm=m: self._set_focus(mm)).pack(
                side="left", padx=3)

        self.var_remember = tk.BooleanVar(value=True)
        tk.Checkbutton(self, text="记住为默认时长（下次直接开始）",
                       variable=self.var_remember,
                       font=font(9),
                       bg=c["dialog_bg"], fg=c["text"],
                       selectcolor=c["panel_bg"],
                       activebackground=c["dialog_bg"],
                       activeforeground=c["text"],
                       highlightthickness=0, bd=0).pack(anchor="w", padx=24,
                                                        pady=(4, 2))

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=(10, 14))
        tk.Button(btns, text="开始专注", font=font(10, "bold"),
                  relief="flat", bg=c["accent"], fg=c["accent_fg"],
                  activebackground=c["accent"], bd=0, padx=18, pady=5,
                  command=self._ok).pack(side="left", padx=6)
        tk.Button(btns, text="取消", font=font(10),
                  relief="flat", bg=c["panel_bg"], fg=c["text"],
                  activebackground=c["panel_active"], bd=0, padx=18, pady=5,
                  command=self.destroy).pack(side="left", padx=6)

        self.spin_focus.focus_set()
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        try:
            self.transient(master)
        except tk.TclError:
            pass
        self.grab_set()

    def _set_focus(self, minutes):
        self.spin_focus.delete(0, "end")
        self.spin_focus.insert(0, str(minutes))

    def _read(self, spin, fallback):
        try:
            return max(self.app.POMO_MIN,
                       min(self.app.POMO_MAX, int(float(spin.get()))))
        except (ValueError, tk.TclError):
            return fallback

    def _ok(self):
        minutes = self._read(self.spin_focus, self.app.pomo_minutes)
        rest = self._read(self.spin_break, self.app.pomo_break)
        if self.var_remember.get():
            self.app.set_pomo_minutes(minutes, rest)
        self.destroy()
        if self.on_start is not None:
            self.on_start(minutes, rest)
        else:
            self.app.start_pomodoro(minutes, rest)


class HotkeyDialog(tk.Toplevel):
    """按下组合键即可设定全局热键（Ctrl / Alt / Shift + 任意键）。"""

    W, H = 380, 230

    def __init__(self, master, app, on_save=None):
        super().__init__(master)
        self.app = app
        self.on_save = on_save
        c = self.C = get_theme(getattr(app, "theme_name", DEFAULT_THEME))
        self.mod = int(app.cfg.get_setting(
            "hotkey_mod", hotkey.MOD_CONTROL | hotkey.MOD_ALT) or 0)
        self.vk = int(app.cfg.get_setting("hotkey_vk", ord("M")) or 0)
        self.title("⌨ 设置全局热键")
        center_window(self, self.W, self.H, master)
        self.configure(bg=c["dialog_bg"])
        self.resizable(False, False)

        tk.Label(self, text="⌨ 自定义全局热键",
                 font=font(14, "bold"),
                 bg=c["dialog_bg"], fg=c["text"]).pack(pady=(14, 4))
        tk.Label(self, text="直接按下你想要的组合键（例如 Ctrl+Alt+M）",
                 font=font(9),
                 bg=c["dialog_bg"], fg=c["sidebar_muted"]).pack()

        self.var = tk.StringVar(value=hotkey.combo_text(self.mod, self.vk))
        tk.Label(self, textvariable=self.var,
                 font=("Consolas", 18, "bold"),
                 bg=c["panel_bg"], fg=c["accent"], width=18,
                 pady=8).pack(pady=14)
        self.hint = tk.Label(self, text="等待按键…", bg=c["dialog_bg"],
                             fg=c["sidebar_muted"],
                             font=font(9))
        self.hint.pack()

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=(10, 12))
        ModernButton(btns, text="保存", command=self._save, c=c,
                     primary=True).pack(side="left", padx=6)
        ModernButton(btns, text="清除", command=self._clear,
                     c=c).pack(side="left", padx=6)
        ModernButton(btns, text="取消", command=self.destroy,
                     c=c).pack(side="left", padx=6)

        self.bind("<KeyPress>", self._on_key)
        self.focus_set()
        try:
            self.transient(master)
        except tk.TclError:
            pass
        self.grab_set()

    def _on_key(self, e):
        if e.keysym == "Escape":
            self.destroy()
            return
        mod = 0
        state = int(getattr(e, "state", 0) or 0)
        if state & 0x0004:
            mod |= hotkey.MOD_CONTROL
        if state & 0x0008 or state & 0x0080:      # Mod1(Alt) / Mod5
            mod |= hotkey.MOD_ALT
        if state & 0x0001:
            mod |= hotkey.MOD_SHIFT
        vk = int(getattr(e, "keycode", 0) or 0)
        if not mod or vk in (16, 17, 18, 91, 92, 93):
            self.hint.config(text="请按住 Ctrl / Alt / Shift 再按一个键")
            return
        self.mod, self.vk = mod, vk
        self.var.set(hotkey.combo_text(mod, vk))
        self.hint.config(text="已捕获，点「保存」生效")

    def _save(self):
        self.destroy()
        if self.on_save is not None:
            self.on_save(self.mod, self.vk)

    def _clear(self):
        self.destroy()
        if self.on_save is not None:
            self.on_save(0, 0)


class CountdownPage(BasePage):
    key = "countdowns"
    title = "专属倒计时"
    subtitle = "倒数日：记住每一个重要的日子"
    REFRESH_MS = 60000        # 每分钟刷新一次，过零点后自动更新

    def __init__(self, master, app):
        self._job = None
        super().__init__(master, app)

    def _build(self):
        c = self.C
        self._toolbar([("calendar", "新建倒计时", self._add),
                       ("clock", "开始番茄钟", self._start_pomo),
                       ("close", "结束番茄钟", self._stop_pomo),
                       ("refresh", "刷新", self.refresh)])
        self.body = tk.Frame(self, bg=c["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.refresh()
        self._job = self.after(self.REFRESH_MS, self._auto)

    def _start_pomo(self):
        """弹出时长设置（滚轴选分钟），确认后开启番茄钟。"""
        PomodoroDialog(self.app, self.app, on_start=self._on_pomo_start)

    def _on_pomo_start(self, minutes, rest):
        self.app.start_pomodoro(minutes, rest)
        messagebox.showinfo(
            "🍅 番茄钟已开始",
            f"专注 {minutes} 分钟，结束后休息 {rest} 分钟！\n"
            "召唤桌宠（⚙ 设置 → 桌面宠物）\n"
            "墨墨会捧着书陪你，头顶显示剩余时间。",
            parent=self.app)

    def _stop_pomo(self):
        """手动结束番茄钟：桌宠头上的倒计时会立刻消失。"""
        if not self.app.pomodoro:
            messagebox.showinfo("🍅 番茄钟",
                                "当前没有正在进行的番茄钟～",
                                parent=self.app)
            return
        self.app.stop_pomodoro()
        messagebox.showinfo("🍅 番茄钟已结束",
                            "已提前结束本轮专注，墨墨收起了倒计时。",
                            parent=self.app)

    def _auto(self):
        self.refresh()
        self._job = self.after(self.REFRESH_MS, self._auto)

    def destroy(self):
        job = getattr(self, "_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._job = None
        super().destroy()

    def refresh(self):
        c = self.C
        for w in self.body.winfo_children():
            w.destroy()
        items = sorted(self.cfg.countdowns, key=cd.sort_key)

        if not items:
            box = tk.Frame(self.body, bg=c["app_bg"])
            box.pack(pady=60)
            tk.Label(box, text="⏳", bg=c["app_bg"], fg=c["text"],
                     font=font(34)).pack()
            tk.Label(box, text="还没有倒计时", bg=c["app_bg"], fg=c["text"],
                     font=font(13, "bold")).pack(pady=(6, 4))
            tk.Label(box, text="点「➕ 新建倒计时」记下第一个重要的日子\n"
                              "（考试、生日、发工资、假期…）",
                     bg=c["app_bg"], fg=c["sidebar_muted"],
                     font=font(9), justify="center").pack()
            self.app.update_topbar("暂无倒计时")
            return

        # 置顶焦点：最近的一个日子
        head = items[0]
        if cd.describe(head)["state"] != "invalid":
            self._focus_card(head)
            rest = items[1:]
        else:
            rest = items
        for item in rest:
            self._card(item)
        self.app.update_topbar(f"{len(items)} 个倒计时 · "
                               f"最近：{head.get('title', '')}")

    # ---- 卡片 ----
    def _focus_card(self, item):
        """置顶大卡：把最近的日子放大显示，起到提醒作用。"""
        c = self.C
        info = cd.describe(item)
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=2,
                        highlightbackground=c["accent"], padx=18, pady=16)
        card.pack(fill="x", pady=(6, 12))

        left = tk.Frame(card, bg=c["card_bg"])
        left.pack(side="left", fill="both", expand=True)

        num_color = c["accent"] if info["state"] != "past" else c["sidebar_muted"]
        tk.Label(left, text=self._big_number(info), bg=c["card_bg"],
                 fg=num_color, font=font(30, "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(left, text=item.get("title", ""), bg=c["card_bg"], fg=c["text"],
                 font=font(14, "bold"), anchor="w").pack(anchor="w")
        tk.Label(left, text=self._date_text(item, info), bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(10),
                 anchor="w").pack(anchor="w", pady=(2, 0))
        if item.get("note"):
            tk.Label(left, text=item["note"], bg=c["card_bg"],
                     fg=c["sidebar_muted"], font=font(9),
                     anchor="w").pack(anchor="w")
        self._progress_row(left, item)
        self._actions(card, item, card)

    def _card(self, item):
        c = self.C
        info = cd.describe(item)
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=14, pady=12)
        card.pack(fill="x", pady=6)

        num_color = c["accent"] if info["state"] != "past" else c["sidebar_muted"]
        left = tk.Frame(card, bg=c["card_bg"], width=118)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text=self._big_number(info), bg=c["card_bg"],
                 fg=num_color, font=font(22, "bold"),
                 anchor="center").pack(fill="x")

        mid = tk.Frame(card, bg=c["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        tk.Label(mid, text=item.get("title", ""), bg=c["card_bg"], fg=c["text"],
                 font=font(12, "bold"), anchor="w").pack(fill="x")
        tk.Label(mid, text=self._date_text(item, info), bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(9),
                 anchor="w").pack(fill="x")
        if item.get("note"):
            tk.Label(mid, text=item["note"], bg=c["card_bg"],
                     fg=c["sidebar_muted"], font=font(9),
                     anchor="w").pack(fill="x")
        self._progress_row(mid, item)
        self._actions(card, item, card)

    def _actions(self, parent, item, card=None):
        """卡片右侧的编辑 / 删除按钮（置顶大卡和普通卡片共用）。

        card 非空时，整张卡片及其子控件再挂一个右键菜单，方便直接操作。
        """
        c = self.C
        cid = item.get("id")
        btns = tk.Frame(parent, bg=c["card_bg"])
        btns.pack(side="right", anchor="n")
        # 注意：必须用默认参数锁住 cid，否则 lambda 捕获循环变量会删错条目
        acts = (("编辑", lambda cid=cid: self._edit(cid)),
                ("删除", lambda cid=cid: self._delete(cid)))
        for text, cmd in acts:
            tk.Button(btns, text=text, font=font(9),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"], bd=0,
                      padx=10, pady=3, command=cmd).pack(side="left", padx=3)

        if card is None:
            return
        menu = tk.Menu(card, tearoff=0)
        style_menu(menu, c)
        for text, cmd in acts:
            menu.add_command(label=text, command=cmd)
        self._bind_menu(card, menu)

    def _bind_menu(self, widget, menu):
        """右键菜单绑定到整张卡片（含所有子控件）。"""
        widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        for w in widget.winfo_children():
            self._bind_menu(w, menu)

    @staticmethod
    def _big_number(info) -> str:
        """卡片左侧的大数字（今天 / 无效日期做特殊显示）。"""
        if info["state"] == "invalid":
            return "?"
        if info["state"] == "today":
            return "今天"
        return f"{abs(info['days'])} 天"

    def _date_text(self, item, info) -> str:
        """目标日期 + 星期 + 循环标记 + 还有/已过说明。"""
        if info["state"] == "invalid":
            return f"日期「{item.get('date', '')}」无法识别，点编辑修正"
        target = info["target"]
        when = cd.weekday_cn(target) if target else ""
        repeat = " · 每年循环" if item.get("repeat") else ""
        return f"{cd.fmt_date(target)} {when}{repeat} · {info['text']}"

    def _progress_row(self, parent, item):
        """完成度进度条（区间算不出来就不画）。"""
        ratio = cd.progress(item)
        if ratio is None:
            return
        c = self.C
        row = tk.Frame(parent, bg=c["card_bg"])
        row.pack(fill="x", pady=(6, 0))
        stat_bar(row, ratio, c, width=260, height=8)
        tk.Label(row, text=f"{ratio * 100:.0f}%", bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(8)).pack(
            side="left", padx=8)

    # ---- 增删改 ----
    def _add(self):
        CountdownDialog(self.app, self.C,
                        on_save=lambda data: self._save(None, data))

    def _edit(self, cid):
        item = self.cfg.get_countdown(cid)
        if item is None:
            return
        CountdownDialog(self.app, self.C, item=item,
                        on_save=lambda data: self._save(cid, data))

    def _save(self, cid, data):
        if cid:
            self.cfg.update_countdown(cid, **data)
        else:
            self.cfg.add_countdown(**data)
        self.refresh()

    def _delete(self, cid):
        item = self.cfg.get_countdown(cid)
        if item is None:
            return
        if messagebox.askyesno("删除倒计时",
                               f"删除「{item.get('title', '')}」？",
                               parent=self.app):
            self.cfg.remove_countdown(cid)
            self.refresh()


# ======================================================================
# 6. 设置页
# ======================================================================
class SettingsPage(BasePage):
    key = "settings"
    title = "设置"
    subtitle = "外观、桌面宠物与侧边栏"

    def _build(self):
        c = self.C
        self.body = tk.Frame(self, bg=c["app_bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=12)

        self._section("外观主题")
        self.var = tk.StringVar(value=self.app.theme_name)
        for key in ("light", "dark"):
            tk.Radiobutton(self.body, text=THEME_NAMES[key], value=key,
                           variable=self.var, font=font(10),
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
            tk.Label(chips, text=name, width=6, font=font(8),
                     bg=c[key], fg=c["text"], padx=4, pady=6).pack(side="left", padx=3)

        self._section("桌面宠物")
        pet_row = tk.Frame(self.body, bg=c["app_bg"])
        pet_row.pack(anchor="w", pady=4)
        pet_text = "收起宠物" if self.app.pet_active() else "召唤宠物"
        self._pet_btn = ModernButton(
            pet_row, text=pet_text, command=lambda: self._pet(self._pet_btn),
            c=c, icon="pet", primary=not self.app.pet_active())
        self._pet_btn.pack(side="left")
        tk.Label(pet_row, text="墨墨会悬浮在桌面上：可拖拽抛掷（重力弹跳）、"
                               "点击摸头会开心",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=10)

        pomo_row = tk.Frame(self.body, bg=c["app_bg"])
        pomo_row.pack(anchor="w", pady=4)
        running = bool(self.app.pomodoro)
        pomo_text = "结束番茄钟" if running else "开始番茄钟"
        spin_kw = dict(font=font(10), width=4, justify="center",
                       relief="flat", bd=0, bg=c["panel_bg"], fg=c["text"],
                       buttonbackground=c["panel_bg"],
                       insertbackground=c["text"],
                       highlightthickness=1,
                       highlightbackground=c["divider"],
                       highlightcolor=c["accent"])
        self.var_pomo = tk.IntVar(value=self.app.pomo_minutes)
        if not running:
            self.spin_pomo = tk.Spinbox(pomo_row, from_=self.app.POMO_MIN,
                                        to=self.app.POMO_MAX,
                                        textvariable=self.var_pomo, **spin_kw)
            self.spin_pomo.pack(side="left")
            tk.Label(pomo_row, text="分钟", bg=c["app_bg"], fg=c["text"],
                     font=font(9)).pack(side="left", padx=(3, 8))
        ModernButton(pomo_row, text=pomo_text, command=self._toggle_pomodoro,
                     c=c, icon="clock", primary=not running).pack(side="left")
        self.var_pomo_break = tk.IntVar(value=self.app.pomo_break)
        if not running:
            self.spin_pomo_break = tk.Spinbox(
                pomo_row, from_=self.app.POMO_MIN, to=self.app.POMO_MAX,
                textvariable=self.var_pomo_break, **spin_kw)
            self.spin_pomo_break.pack(side="left", padx=(12, 0))
            tk.Label(pomo_row, text="分钟休息", bg=c["app_bg"],
                     fg=c["text"], font=font(9)).pack(
                side="left", padx=(3, 4))
        tk.Label(pomo_row,
                 text=("专注结束后墨墨会收起倒计时、提醒你休息"
                       if running else
                       "自定义专注时长：开启后墨墨捧书陪你，头顶倒计时"),
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=10)

        monitor_row = tk.Frame(self.body, bg=c["app_bg"])
        monitor_row.pack(anchor="w", pady=4)
        self._monitor_var = tk.BooleanVar(
            value=bool(self.app.cfg.get_setting("pet_monitor", True)))
        tk.Checkbutton(monitor_row, text="系统状态联动（CPU 高冒汗 / "
                                         "内存不足疲惫 / 网速快奔跑）",
                       variable=self._monitor_var, command=self._toggle_monitor,
                       font=font(9),
                       bg=c["app_bg"], fg=c["text"],
                       selectcolor=c["panel_bg"],
                       activebackground=c["app_bg"],
                       activeforeground=c["text"],
                       highlightthickness=0, bd=0).pack(side="left")

        self._section("全局热键")
        hk_top = tk.Frame(self.body, bg=c["app_bg"])
        hk_top.pack(anchor="w", pady=4)
        self._hk_var = tk.BooleanVar(
            value=bool(self.app.cfg.get_setting("hotkey_enabled", True)))
        tk.Checkbutton(hk_top, text="启用全局热键（窗口隐藏时也能一键呼出）",
                       variable=self._hk_var, command=self._toggle_hotkey,
                       font=font(9),
                       bg=c["app_bg"], fg=c["text"],
                       selectcolor=c["panel_bg"],
                       activebackground=c["app_bg"],
                       activeforeground=c["text"],
                       highlightthickness=0, bd=0).pack(side="left")

        hk_row = tk.Frame(self.body, bg=c["app_bg"])
        hk_row.pack(anchor="w", pady=4)
        tk.Label(hk_row, text="当前：", bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left")
        tk.Label(hk_row, text=self.app.hotkey_text(), bg=c["app_bg"],
                 fg=c["accent"], font=font(10, "bold")).pack(
            side="left", padx=(0, 10))
        ModernButton(hk_row, text="修改快捷键", command=self._pick_hotkey,
                     c=c, icon="gear", primary=True).pack(side="left",
                                                          padx=(0, 8))
        ModernButton(hk_row, text="恢复默认", command=self._reset_hotkey,
                     c=c, icon="refresh").pack(side="left")

        state = "按一下就唤出 / 隐藏主界面，不用再去任务栏找"
        if getattr(self.app, "hk_auto", ""):
            state = "⚠ " + self.app.hk_auto + "（可在上面手动改）"
        elif self._hk_var.get() and self.app.hk.error:
            state = f"⚠ 注册失败：{self.app.hk.error}，请换一个组合试试"
        elif not self._hk_var.get():
            state = "已关闭：只能通过任务栏图标打开主界面"
        tk.Label(self.body, text=state, bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9), anchor="w",
                 justify="left").pack(fill="x", pady=(2, 0))

        self._section("侧边栏")
        sb_row = tk.Frame(self.body, bg=c["app_bg"])
        sb_row.pack(anchor="w", pady=4)
        ModernButton(sb_row, text="折叠 / 展开", command=self.app.toggle_sidebar,
                     c=c, icon="collapse").pack(side="left")
        tk.Label(sb_row, text="折叠后只显示图标，状态会自动记住",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9)).pack(side="left", padx=10)

        self._section("关于")
        tk.Label(self.body,
                 text=f"墨墨桌面管理助手 {APP_VERSION}\n"
                      "纯 Python 标准库实现（tkinter），无需任何第三方依赖。",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(9), justify="left",
                 anchor="w").pack(anchor="w")

        self.app.update_topbar(f"当前主题：{THEME_NAMES[self.app.theme_name]}")

    def _section(self, text):
        c = self.C
        tk.Label(self.body, text=text, bg=c["app_bg"], fg=c["text"],
                 font=font(11, "bold"), anchor="w").pack(
            fill="x", pady=(14, 4))
        hline(self.body, c["divider"], pady=(0, 8))

    def _toggle_pomodoro(self):
        if self.app.pomodoro:
            self.app.stop_pomodoro()
        else:
            # 以页面上的自定义时长开始，并记住为下次默认
            try:
                mins = int(self.var_pomo.get())
                rest = int(self.var_pomo_break.get())
            except (ValueError, tk.TclError):
                mins, rest = self.app.pomo_minutes, self.app.pomo_break
            self.app.set_pomo_minutes(mins, rest)
            self.app.start_pomodoro(mins, rest)
        self.app._show_page("settings", force=True)   # 重建页面以更新按钮文字

    def _pick_hotkey(self):
        """弹出捕获框：按下组合键即可自定义全局热键。"""
        HotkeyDialog(self.app, self.app, on_save=self._save_hotkey)

    def _save_hotkey(self, mod, vk):
        self.app.cfg.set_setting("hotkey_mod", int(mod or 0))
        self.app.cfg.set_setting("hotkey_vk", int(vk or 0))
        self.app.reload_hotkey()
        self.app._show_page("settings", force=True)

    def _reset_hotkey(self):
        # 清掉自定义值，让它回到默认（如果被占用会自动换备用组合）
        self.app.cfg.settings.pop("hotkey_mod", None)
        self.app.cfg.settings.pop("hotkey_vk", None)
        self.app.cfg.save()
        self.app.reload_hotkey()
        self.app._show_page("settings", force=True)

    def _toggle_hotkey(self):
        self.app.cfg.set_setting("hotkey_enabled", self._hk_var.get())
        self.app.reload_hotkey()
        self.app._show_page("settings", force=True)

    def _toggle_monitor(self):
        self.app.cfg.set_setting("pet_monitor", self._monitor_var.get())
        pet = getattr(self.app, "_pet", None)
        if pet is not None:
            pet._monitor_on = self._monitor_var.get()
            if not self._monitor_var.get():
                pet._bubble.hide()
                pet._sys_state = "idle"
                pet._set_face("idle")

    def _pick_theme(self):
        self.app._apply_theme(self.var.get())

    def _pet(self, btn=None):
        """召唤 / 收起桌宠，并把按钮文字同步过来。"""
        self.app._toggle_pet()
        if btn is not None:
            btn.set_text("收起宠物" if self.app.pet_active() else "召唤宠物")


PAGES = (DesktopPage, CategoriesPage, StatsPage, SystemPage,
         CountdownPage, SettingsPage)
PAGE_BY_KEY = {p.key: p for p in PAGES}
