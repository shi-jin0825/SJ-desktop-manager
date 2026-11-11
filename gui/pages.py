# -*- coding: utf-8 -*-
"""右侧主内容区的页面：首页（桌面网格）/ 分类 / 统计 / 设置。

每个页面都是 tk.Frame，由 gui.app.App（主框架）按需创建并切换。
页面统一通过 self.app 访问主题配色、配置和桌宠等全局能力。
"""
import calendar
import datetime as dt
import json
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from core.scanner import scan_desktop, get_desktop_paths
from core.icons import icon_png
from core import countdown as cd
from core import hotkey
from core.undo import UndoStack
from gui import category_ops
from gui.theme import (DEFAULT_THEME, THEMES, THEME_NAMES, get_theme, style_menu)
from gui.fonts import font
from gui.tokens import BAR_H, BTN_H_SM, FS, SP, px
from gui.widgets import (open_target, make_photo, rounded_rect, short_name,
                         center_window, dialog_header, fit_text, hline,
                         stat_bar, shrink, ModernButton, hover_card,
                         RoundedCheck, ScrolledFrame)

# ---- 磁贴尺寸（基准值；网格变宽时整体按倍率放大） ----
# 全部过 px()：高 DPI 下 Tk 把字号放大了，磁贴 / 图标不同步的话文字装不下
TILE_SIZE = px(96)      # 磁贴基准宽度（px）
TILE_H = px(108)        # 磁贴基准高度（px）（磁贴统一尺寸，hover 放大不会推挤邻居）
COLS = 8            # 默认每行数量（窗口宽度变化时会自适应）
MIN_COLS = 4        # 每行最少数量
MAX_COLS = 16       # 每行最多数量（窗口放大时自动增加）
TILE_PADX = px(8)
TILE_PADY = px(8)
ICON_SIZE = px(48)      # 磁贴图标基准尺寸（px）
ICONS_PER_TICK = 6  # 每帧最多提取几个系统图标（懒加载，防止首屏卡顿）
TILE_HOVER = px(6)      # 鼠标悬停时磁贴放大的像素数

# 自适应缩放：窗口放大时磁贴跟着长大（以前只加列数，磁贴永远 96px）
REF_GRID_W = px(640)    # 基准网格宽度：这个宽度下磁贴正好是基准尺寸
TILE_SCALE_POW = 0.75   # 宽度→倍率曲线：1.0=完全线性，越小越偏向「多排几列」
TILE_GROW = 1.75        # 磁贴最大放大倍率（顶到上限后就只加列、不再变大）
TILE_SHRINK = 0.72      # 窗口缩到最小时磁贴的最小倍率（再小就看不清图标了）
# 手动档位：写成基准的倍数（以前 normal=100 比基准 96 还大 4px，是孤值）
TILE_PRESETS = {"small": int(TILE_SIZE * 0.88),    # 84
                "normal": TILE_SIZE,               # 96
                "large": int(TILE_SIZE * 1.38)}    # 132


def tile_scale(width: int) -> float:
    """磁贴放大倍率：宽度比的 0.75 次方，封顶 TILE_GROW。

    首页磁贴和分类窗口卡片共用这一条曲线。以前各算各的（首页 0.75 次方
    上限 1.75x，分类窗口是线性、上限 1.4x、基准 560），结果两个窗口同时
    开着时分类卡片反而比首页磁贴还大——明明该是「首页 > 分类」的层级。
    """
    s = (max(240.0, float(width)) / REF_GRID_W) ** TILE_SCALE_POW
    return max(TILE_SHRINK, min(TILE_GROW, s))

# ---- 分类文件夹窗口内的卡片 ----
CAT_TILE_W = px(90)         # 卡片基准宽度（px）
CAT_TILE_H = px(86)         # 卡片基准高度（px）
CAT_COLS = 8            # 基准列数
CAT_MIN_COLS = 3
CAT_MAX_COLS = 12

# ---- 分类文件夹 3×3 预览 ----
FOLDER_PREVIEW = px(70)
PREVIEW_ICON = px(20)
PREVIEW_GAP = px(2)
PREVIEW_PAD = 3
PREVIEW_COLS = 3
MAX_PREVIEW = PREVIEW_COLS ** 2

UNDO_DEPTH = 10         # 「撤销上一步」最多记住几步整理操作

APP_VERSION = "v1.13.1"      # 设置页「关于」显示；发版时跟着更新日志一起改
KIND_LABEL = {"shortcut": "快捷方式", "dir": "文件夹", "file": "文件"}


class CategoryWindow(tk.Toplevel):
    """某个分类文件夹的内容窗口。"""

    def __init__(self, master, category, items, config, on_change, theme=None):
        super().__init__(master)
        c = theme or get_theme(DEFAULT_THEME)
        self.C = c
        self.title(f"📁 {category}")
        self.configure(bg=c["dialog_bg"])
        self.category = category
        self.cfg = config
        self.on_change = on_change
        self._photos = []
        self.items = list(items)
        self.cols = CAT_COLS
        self.tile_w = CAT_TILE_W
        self.tile_h = CAT_TILE_H
        self._relayout_job = None
        # 窗口大小跟着主窗口：主窗口放大后这个窗口还是小窗口那点尺寸会很突兀
        mw = mh = 0
        try:
            if master is not None and master.winfo_ismapped():
                mw, mh = master.winfo_width(), master.winfo_height()
        except tk.TclError:
            pass
        center_window(self,
                      max(px(560), min(px(1100), int(mw * 0.72) if mw else px(560))),
                      max(px(400), min(px(820), int(mh * 0.78) if mh else px(400))),
                      master)

        self.head = tk.Label(self, text="", font=font(FS["lg"], "bold"),
                             bg=c["dialog_bg"], fg=c["text"])
        self.head.pack(pady=SP["md"])
        self.frame = tk.Frame(self, bg=c["dialog_bg"])
        self.frame.pack(fill="both", expand=True, padx=SP["md"], pady=SP["xs"])
        self.frame.bind("<Configure>", self._on_resize)
        self._render()

    def _on_resize(self, event=None):
        """分类窗口被拉大：内容跟着重排（列数 + 卡片尺寸），不再固定 8 列。"""
        w = event.width if event is not None and event.width > 1 \
            else self.frame.winfo_width()
        if w <= 1:
            return
        cols, tile_w = self._plan(w)
        if cols == self.cols and tile_w == self.tile_w:
            return
        self.cols, self.tile_w = cols, tile_w
        self.tile_h = int(round(CAT_TILE_H * tile_w / float(CAT_TILE_W)))
        if self._relayout_job is not None:
            self.after_cancel(self._relayout_job)
        self._relayout_job = self.after(150, self._do_relayout)

    @staticmethod
    def _plan(width):
        """和首页磁贴共用 tile_scale 曲线（见模块顶部说明）。"""
        tile_w = int(round(CAT_TILE_W * tile_scale(width)))
        per = tile_w + SP["md"]
        cols = max(CAT_MIN_COLS, min(CAT_MAX_COLS, width // per))
        return cols, tile_w

    def _do_relayout(self):
        self._relayout_job = None
        self._render()

    def _render(self):
        """重建网格内容（移出某项后原地刷新，不再直接关窗）。"""
        c = self.C
        for w in self.frame.winfo_children():
            w.destroy()
        self._photos = []
        items = self.items
        self.head.config(text=f"📁 {self.category}（{len(items)} 项）")
        cols = self.cols
        icon_size = max(32, int(round(ICON_SIZE * self.tile_w / float(CAT_TILE_W)
                                      / 2.0)) * 2)
        fs = max(FS["xs"], min(FS["md"],
                               int(round(FS["xs"] * self.tile_w
                                         / float(CAT_TILE_W)))))
        self.frame.grid_columnconfigure(tuple(range(cols)), weight=1)

        if not items:
            tk.Label(self.frame, text="空空如也，右键桌面上的项目可移入此分类",
                     bg=c["dialog_bg"], fg=c["text_muted"]).grid(
                row=0, column=0, columnspan=cols, pady=SP["xxl"])
            return

        for idx, item in enumerate(items):
            icon = make_photo(icon_png(item.path, icon_size), self._photos)
            # 名字按磁贴像素宽截断；不给 Button 传字符单位的 width/height
            #（塞像素值会撑大内容画布，文字两边被裁），尺寸由 grid 槽位管
            tname = fit_text(item.display_name,
                             tkfont.Font(font=font(fs)),
                             max(px(20), self.tile_w - px(16)))
            if icon:
                btn = tk.Button(self.frame, image=icon,
                                text=tname,
                                compound="top", font=font(fs),
                                relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            else:
                btn = tk.Button(self.frame, text=f"📄\n{tname}",
                                font=font(fs),
                                relief="flat",
                                bg=c["panel_bg"], fg=c["text"],
                                activebackground=c["panel_active"],
                                command=lambda p=item.path: open_target(p))
            btn.grid(row=idx // cols, column=idx % cols, padx=SP["sm"], pady=SP["sm"])
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

    BTN_W = 156         # 按钮估宽：用来算一行能放几个（自动换行用，跟着大按钮走）

    def _card_buttons(self, parent, actions, side="right"):
        """卡片里的按钮：和工具栏同一套胶囊按钮语言，只是小一号。

        以前卡片里用的是原生 tk.Button（直角、纯色、9 号字），和工具栏的
        渐变胶囊并排出现时，同一个界面里像两个不同的 App。
        actions: [(文字, 命令)] 或 [(文字, 命令, 是否主操作)]
        """
        c = self.C
        row = tk.Frame(parent, bg=c["card_bg"])
        row.pack(side=side, anchor="n")
        for item in actions:
            text, cmd = item[0], item[1]
            primary = item[2] if len(item) > 2 else False
            ModernButton(row, text=text, command=cmd, c=c, primary=primary,
                         height=BTN_H_SM, padx=SP["md"],
                         font=font(FS["sm"]), icon_size=16,
                         bg=c["card_bg"]).pack(side="left", padx=SP["xs"])
        return row

    def _scroll_body(self, padx=SP["lg"], pady=(SP["none"], SP["md"]),
                     center=False):
        """建一个可滚动的内容区，返回容器（真正的内容往它的 .body 里塞）。

        长页面（设置 / 倒计时 / 分类 / 统计 / 监控）内容超过一屏时，
        以前是直接被切掉且滚不动——只有首页自己带了一套 Canvas 滚动。
        """
        sc = ScrolledFrame(self, self.C, center=center, padx=padx, pady=pady)
        sc.pack(fill="both", expand=True)
        return sc

    def _toolbar(self, buttons, primary=None):
        """页面顶部的一条胶囊渐变按钮（(文字, 命令) 或 (图标, 文字, 命令)）。

        primary 传文字时，那个按钮会用强调色渐变（视觉主操作）。
        """
        c = self.C
        host = tk.Frame(self, bg=c["app_bg"])
        host.pack(fill="x", padx=SP["lg"], pady=(SP["md"], SP["sm"]))
        items = []
        for item in buttons:
            if len(item) == 3:
                icon, text, cmd = item
            else:
                text, cmd = item
                icon = None
            items.append((icon, text, cmd, text == primary))
        self._button_row(host, items)
        return host

    def _button_row(self, parent, items):
        """一排会自动换行的按钮：(图标, 文字, 命令, 是否主操作)。

        以前固定一行 pack 到底，窗口缩小时右边的按钮直接被挤出可视区。
        现在按容器宽度决定每行放几个，窄窗口自动折行。
        """
        grid = tk.Frame(parent, bg=self.C["app_bg"])
        # 必须 expand：空容器请求宽度是 0，不撑开的话它永远量不到宽度，
        # 按钮也就永远不会创建（先有宽度才有按钮，不是先有按钮才有宽度）
        grid.pack(side="left", fill="x", expand=True)
        state = {"n": 0}

        def relayout(_=None):
            w = grid.winfo_width()
            if w <= 1:
                return
            n = max(1, min(len(items), w // self.BTN_W))
            if n == state["n"] and grid.winfo_children():
                return
            state["n"] = n
            for child in grid.winfo_children():
                child.destroy()
            for i, (icon, text, cmd, primary) in enumerate(items):
                ModernButton(grid, text=text, command=cmd, c=self.C,
                             icon=icon, primary=primary).grid(
                    row=i // n, column=i % n, padx=(SP["none"], SP["md"]), pady=(SP["none"], SP["sm"]),
                    sticky="w")

        grid.bind("<Configure>", relayout)
        return grid


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
        # 当前这一轮渲染实际用的尺寸（随网格宽度缩放，见 _apply_metrics）
        self.tile_w = TILE_SIZE
        self.tile_h = TILE_H
        self.icon_size = ICON_SIZE
        self.tile_hover = TILE_HOVER
        self.preview = FOLDER_PREVIEW
        self.preview_icon = PREVIEW_ICON
        self.preview_gap = PREVIEW_GAP
        self.preview_pad = PREVIEW_PAD
        self.preview_r = 12
        self.tile_font = 9
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
        self.sel_host.pack(fill="x", padx=SP["lg"], after=self.winfo_children()[0])
        self._build_selbar()
        # 内容区：可滚动（和设置 / 统计等长页面共用一套滚动容器）
        sc = ScrolledFrame(self, c, center=True, padx=SP["lg"], pady=(SP["none"], SP["md"]))
        sc.pack(fill="both", expand=True)
        self.canvas = sc.canvas
        self.scrollbar = sc.scrollbar
        self.grid_frame = sc.body
        self._grid_win = sc._win
        self.grid_frame.bind("<Configure>", self._on_grid_configure)
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
                                  font=font(FS["sm"], "bold"))
        self.sel_label.pack(anchor="w", pady=(SP["none"], SP["xs"]))

        self.sel_menu = tk.Menu(self, tearoff=0)
        style_menu(self.sel_menu, c)
        # 窄窗口下按钮会自动折行，不会挤成一团或跑出可视区
        self._button_row(bar, [
            ("folder", "移入分类 ▾", self._popup_move, True),
            ("close", "移出分类", self._unassign_selected, False),
            ("refresh", "撤销上一步", self._undo, False),
            ("close", "取消选择", self._clear_selection, False),
        ])

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
            self.selbar.pack(fill="x", pady=(SP["none"], SP["sm"]))
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
        cols, tile_w = self._plan(w)
        # 列数或磁贴尺寸变了才重排：拖动窗口时每次像素变化都重建网格会卡
        if cols != self.cols or tile_w != self.tile_w:
            self.cols = cols
            self._apply_metrics(tile_w)
            if self._relayout_job is not None:
                self.after_cancel(self._relayout_job)
            self._relayout_job = self.after(150, self._do_relayout)

    def _do_relayout(self):
        self._relayout_job = None
        self.refresh(rescan=False)      # 只是换列数/尺寸，桌面内容没变，不用重扫

    def _plan(self, width):
        """按网格可用宽度算 (每行几列, 磁贴宽度)。

        窗口放大时磁贴要跟着长大，而不是只多排几列、磁贴还是小窗口那点尺寸：
          1. 先按宽度算放大倍率（宽度比的 0.75 次方，大屏上不至于夸张）——
             磁贴尺寸只跟宽度有关，所以拖动窗口时它是单调变大的；
          2. 再按这个尺寸算能排几列，多余宽度由 grid 均分成磁贴间的均匀间距，
             不会挤在右边留一大块空白；
          3. 间距大到看着太散时才多加一列（列数变了磁贴尺寸不变，
             所以不会出现「窗口拉宽、磁贴反而变小」的回落）。
        """
        pad = TILE_PADX * 2 + 4
        avail = max(MIN_COLS * (TILE_SIZE + TILE_PADX * 2), width - 4)
        preset = str(self.cfg.get_setting("tile_size", "auto") or "auto").lower()
        if preset in TILE_PRESETS:
            # 手动档位：尺寸定死，只按宽度决定排几列
            tile_w = TILE_PRESETS[preset]
        else:
            tile_w = int(round(TILE_SIZE * tile_scale(avail)))
        tile_w = int(min(TILE_SIZE * TILE_GROW,
                         max(TILE_SIZE * TILE_SHRINK, tile_w)))
        cols = max(MIN_COLS, min(MAX_COLS, avail // (tile_w + pad)))
        while cols < MAX_COLS and avail // cols - pad > int(tile_w * 1.3):
            cols += 1
        return cols, tile_w

    def _apply_metrics(self, tile_w):
        """磁贴宽定了，图标 / 预览 / 字号等比跟着变。"""
        s = tile_w / float(TILE_SIZE)
        self.tile_w = tile_w
        self.tile_h = int(round(TILE_H * s))
        self.icon_size = max(24, int(round(ICON_SIZE * s / 2.0)) * 2)
        self.tile_hover = max(4, int(round(TILE_HOVER * s)))
        self.preview = int(round(FOLDER_PREVIEW * s))
        self.preview_icon = max(8, int(round(PREVIEW_ICON * s)))
        self.preview_gap = max(1, int(round(PREVIEW_GAP * s)))
        self.preview_pad = max(2, int(round(PREVIEW_PAD * s)))
        self.preview_r = max(8, int(round(12 * s)))
        self.tile_font = max(8, min(14, int(round(9 * s))))

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
            self.cols, tile_w = self._plan(w)
            self._apply_metrics(tile_w)

        total = len(categories) + sum(1 for i in items if not i.category)
        cols = self.cols
        self._configure_columns(cols)

        if total == 0 and query:
            box = tk.Frame(self.grid_frame, bg=self.C["app_bg"])
            box.pack(pady=SP["xxl"])
            tk.Label(box, text="🔍", bg=self.C["app_bg"], fg=self.C["text"],
                     font=font(FS["hero"])).pack()
            tk.Label(box, text=f"没有找到与「{self.app.query}」匹配的项目",
                     bg=self.C["app_bg"], fg=self.C["sidebar_muted"],
                     font=font(FS["sm"])).pack(pady=(SP["sm"], SP["none"]))
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
                        width=self.tile_w + TILE_PADX * 2,
                        height=self.tile_h + TILE_PADY * 2, bg=self.C["app_bg"])
        slot.grid_propagate(False)
        slot.grid(row=row, column=col)
        return slot

    def _shadow(self, slot):
        """磁贴下方那一层「淡阴影」，hover 时才显形。"""
        sh = tk.Frame(slot, width=self.tile_w + self.tile_hover,
                      bg=self.C["app_bg"],
                      height=self.tile_h + self.tile_hover)
        sh.place(relx=0.5, rely=0.5, anchor="center", y=3)
        return sh

    def _mini_icon(self, path: str):
        """文件夹预览用的小图标：系统可能返回比请求大的图，缩到预览尺寸。"""
        return shrink(make_photo(icon_png(path, self.preview_icon), self._photos),
                      self.preview_icon, self._photos)

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
        frame = tk.Frame(slot, width=self.tile_w, height=self.tile_h,
                         bg=c["folder_bg"], highlightthickness=0)
        frame.pack_propagate(False)      # 磁贴尺寸固定，内容不把它撑变形
        frame.place(relx=0.5, rely=0.5, anchor="center",
                    width=self.tile_w, height=self.tile_h)

        canvas = tk.Canvas(frame, width=self.preview, height=self.preview,
                           bg=c["folder_bg"], highlightthickness=0)
        canvas.pack(pady=(SP["sm"], SP["none"]))
        rounded_rect(canvas, 1, 1, self.preview - 1, self.preview - 1,
                     r=self.preview_r, fill=c["folder_panel"],
                     outline=c["folder_panel_outline"])

        if previews:
            for i, item in enumerate(previews):
                r, cc = divmod(i, PREVIEW_COLS)
                x = (self.preview_pad
                     + cc * (self.preview_icon + self.preview_gap)
                     + self.preview_icon // 2)
                y = (self.preview_pad
                     + r * (self.preview_icon + self.preview_gap)
                     + self.preview_icon // 2)
                mini = self._mini_icon(item.path)
                if mini:
                    canvas.create_image(x, y, image=mini)
                else:
                    canvas.create_rectangle(
                        x - self.preview_icon // 2 + 2,
                        y - self.preview_icon // 2 + 2,
                        x + self.preview_icon // 2 - 2,
                        y + self.preview_icon // 2 - 2,
                        fill=c["placeholder"],
                        outline=c["placeholder_outline"])
        else:
            canvas.create_text(self.preview // 2, self.preview // 2,
                               text="空", fill=c["empty_text"],
                               # 跟着磁贴缩放（以前写死 12，小窗口下比图标还大）
                               font=font(max(FS["xs"],
                                             int(round(self.tile_font * 1.4))),
                                         "bold"))

        label = tk.Label(frame, text=f"{self._fit_tile_name(category)} ({count})",
                         bg=c["folder_bg"], fg=c["text"],
                         font=font(self.tile_font), cursor="hand2",
                         wraplength=self.tile_w - px(10), justify="center")
        label.pack(pady=(SP["xs"], SP["none"]))

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
                                  grow=self.tile_hover, shadow=shadow, slot=slot)
        for w in (frame, canvas, label):
            w.bind("<Button-1>", open_cmd)
            w.bind("<Button-3>", popup)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _fit_tile_name(self, name, fnt=None):
        """磁贴名字按磁贴实际像素宽度截断（超长加省略号）。

        short_name() 按字数截到 12：英文 12 个字符还很窄，可窗口宽、磁贴
        被压小时 6 个汉字都放不下——名字比磁贴宽就被按钮硬裁掉两头。
        这里跟着 self.tile_w 走，磁贴多宽名字就截到多宽。
        """
        if fnt is None:
            fnt = tkfont.Font(font=font(self.tile_font))
        return fit_text(name, fnt, max(px(20), self.tile_w - px(16)))

    def _make_item_tile(self, row, col, item):
        c = self.C
        slot = self._slot(row, col)
        shadow = self._shadow(slot)
        name = self._fit_tile_name(item.display_name)
        emoji = {"dir": "🗂", "shortcut": "🧩", "file": "📄"}.get(item.kind, "📄")
        # 先占位（emoji + 透明图保证尺寸稳定），真实图标由 _pump_icons 异步补上。
        # master 必须显式给 slot：PhotoImage 不带 master 时挂默认根，
        # 单测/多窗口场景默认根可能不是本页所在的解释器，报
        # TclError: image "pyimageN" doesn't exist
        blank = tk.PhotoImage(master=slot, width=self.icon_size, height=self.icon_size)
        self._photos.append(blank)
        # 注意不要给 tk.Button 传 width/height：那两个参数的单位是「字符」，
        # 塞像素值进去会把按钮的内容画布撑到巨大，place 只露出中间一条，
        # 文字就在两边被裁掉（「Microsoft E…」变成「icrosoft E」）。显示
        # 尺寸由下面 place 的像素参数决定，内容自适应、居中即可。
        btn = tk.Button(slot, image=blank, text=f"{emoji}\n{name}",
                        compound="top", font=font(self.tile_font),
                        relief="flat",
                        bg=c["panel_bg"], fg=c["text"],
                        activebackground=c["panel_active"],
                        activeforeground=c["text"])
        btn.place(relx=0.5, rely=0.5, anchor="center",
                  width=self.tile_w, height=self.tile_h)
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
                                  grow=self.tile_hover, shadow=shadow, slot=slot)
        btn.bind("<Enter>", enter)
        btn.bind("<Leave>", leave)
        # 排进图标加载队列（取不到系统图标时就一直用 emoji 占位）
        self._queue_icon(item.path, self.icon_size,
                         self._tile_icon_setter(btn, name))

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
        center_window(win, px(330), px(380), self.app)
        win.configure(bg=c["dialog_bg"])
        win.resizable(False, False)
        win.grab_set()

        dialog_header(win, c, "管理分类", "分类列表（括号内为项目数）")
        top = tk.Frame(win, bg=c["dialog_bg"])
        top.pack(fill="both", expand=True, padx=SP["xl"],
                 pady=(SP["xs"], SP["none"]))

        body = tk.Frame(top, bg=c["dialog_bg"])
        body.pack(fill="both", expand=True, pady=SP["sm"])
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        lst = tk.Listbox(body, font=font(FS["sm"]), relief="solid",
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
        bar.pack(fill="x", padx=SP["md"], pady=SP["sm"])
        for icon, text, cmd, primary in (
                ("folder", "新建", do_add, True),
                ("gear", "重命名", do_rename, False),
                ("close", "删除", do_delete, False)):
            ModernButton(bar, text=text, command=cmd, c=c, icon=icon,
                         primary=primary).pack(side="left", padx=SP["xs"])
        ModernButton(bar, text="关闭", command=win.destroy, c=c,
                     ).pack(side="right")

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
        self.body = self._scroll_body().body
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
            tk.Label(self.body, text="还没有分类，点上方工具栏的「📁 新建分类」"
                                     "创建第一个",
                     bg=c["app_bg"], fg=c["text_muted"],
                     font=font(FS["sm"])).pack(pady=SP["xxl"])
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
                        highlightbackground=c["divider"], padx=SP["md"], pady=SP["md"])
        card.pack(fill="x", pady=SP["sm"])

        # 左侧：2×2 图标预览
        pv = tk.Canvas(card, width=48, height=48, bg=c["card_bg"],
                       highlightthickness=0)
        pv.pack(side="left", padx=(SP["none"], SP["md"]))
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
                 font=font(FS["md"], "bold"), anchor="w").pack(fill="x")
        names = "、".join(short_name(i.display_name, 10) for i in inner[:6])
        if len(inner) > 6:
            names += f" 等 {len(inner)} 项"
        names_lab = tk.Label(mid, text=names if names else "（空分类）",
                             bg=c["card_bg"], fg=c["sidebar_muted"],
                             font=font(FS["xs"]), anchor="w", wraplength=200,
                             justify="left")
        names_lab.pack(fill="x")
        # 项目名太长会把右侧按钮挤出卡片：让名字随卡片宽度折行
        names_lab.bind("<Configure>", lambda e, l=names_lab:
                       l.configure(wraplength=max(80, e.width - SP["lg"])))

        self._card_buttons(card, (
            ("打开", lambda: self._open(category), True),
            ("重命名", lambda: self._rename(category)),
            ("删除", lambda: self._delete(category)),
        ))

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
        self.body = self._scroll_body().body
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
                            highlightbackground=c["divider"], padx=SP["lg"], pady=SP["md"])
            card.grid(row=0, column=idx, padx=SP["sm"], pady=SP["sm"], sticky="nsew")
            tk.Label(card, text=str(num), bg=c["card_bg"], fg=c["accent"],
                     font=font(FS["xl"], "bold")).pack()
            tk.Label(card, text=label, bg=c["card_bg"], fg=c["sidebar_muted"],
                     font=font(FS["xs"])).pack()

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

        # 专注与计划：番茄轮数 / 累计专注 / 计划完成率
        self._section("专注与计划")
        st = self.cfg.get_setting("pomo_stats") or {}
        if not isinstance(st, dict):
            st = {}
        try:
            sessions = int(st.get("sessions") or 0)
            focus_min = int(st.get("focus_minutes") or 0)
        except (TypeError, ValueError):
            sessions, focus_min = 0, 0
        if sessions:
            tk.Label(self.body,
                     text=(f"🍅 完成 {sessions} 轮番茄钟 · 累计专注 "
                           f"{focus_min // 60} 小时 {focus_min % 60} 分钟"),
                     bg=c["app_bg"], fg=c["text"],
                     font=font(FS["sm"])).pack(anchor="w", pady=SP["xs"])
        else:
            tk.Label(self.body, text="🍅 还没有完成过番茄钟 · 时间管理页开始第一轮",
                     bg=c["app_bg"], fg=c["text_muted"],
                     font=font(FS["sm"])).pack(anchor="w", pady=SP["xs"])
        plans = self.cfg.plans
        if plans:
            done_plans = sum(1 for p in plans if p.get("done"))
            self._row("计划完成", done_plans, len(plans))

        self.app.update_topbar(f"已归类 {done}/{total} 项")

    def _section(self, text):
        c = self.C
        tk.Label(self.body, text=text, bg=c["app_bg"], fg=c["text"],
                 font=font(FS["sm"], "bold"), anchor="w").pack(
            fill="x", pady=(SP["lg"], SP["xs"]))
        hline(self.body, c["divider"], pady=(SP["none"], SP["sm"]))

    def _row(self, name, n, total):
        c = self.C
        row = tk.Frame(self.body, bg=c["app_bg"])
        row.pack(fill="x", pady=SP["xs"])
        tk.Label(row, text=name, bg=c["app_bg"], fg=c["text"],
                 font=font(FS["sm"]), width=12, anchor="w").pack(side="left")
        stat_bar(row, (n / total) if total else 0, c, width=260, stretch=True)
        pct = f"{n / total * 100:.0f}%" if total else "0%"
        tk.Label(row, text=f"{n} 项 · {pct}", bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=SP["md"])


# ======================================================================
# 4. 时间管理：日程计划 + 倒数日
# ======================================================================
class CountdownDialog(tk.Toplevel):
    """新建 / 编辑一条倒计时的弹窗。"""

    WIDTH, HEIGHT = px(430), px(330)

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

        dialog_header(self, c, self.title(),
                      "设定一个重要的日子，墨墨会一直帮你数着")

        form = tk.Frame(self, bg=c["dialog_bg"])
        form.pack(fill="x", padx=SP["xl"])

        self.var_title = tk.StringVar(value=self.item.get("title", ""))
        self.var_date = tk.StringVar(
            value=self.item.get("date") or cd.fmt_date(cd.today()))
        self.var_note = tk.StringVar(value=self.item.get("note", ""))
        self.var_repeat = tk.BooleanVar(value=bool(self.item.get("repeat")))

        self._row(form, "标题", self.var_title, 0)
        self._date_row(form, 1)
        self._row(form, "备注", self.var_note, 3)

        RoundedCheck(self, c, text="每年循环（生日 / 纪念日）",
                     variable=self.var_repeat,
                     bg=c["dialog_bg"]).pack(anchor="w", padx=SP["xl"],
                                             pady=(SP["sm"], SP["none"]))

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=SP["lg"])
        ModernButton(btns, text="保存", command=self._save, c=c, primary=True,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])
        ModernButton(btns, text="取消", command=self.destroy, c=c,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _row(self, parent, label, var, row):
        c = self.C
        tk.Label(parent, text=label, width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=row, column=0, pady=SP["sm"])
        tk.Entry(parent, textvariable=var, width=28,
                 font=font(FS["md"]), relief="flat",
                 bg=c["panel_bg"], fg=c["text"],
                 insertbackground=c["text"],
                 highlightthickness=1,
                 highlightbackground=c["divider"]).grid(
            row=row, column=1, sticky="ew", pady=SP["sm"], padx=(SP["sm"], SP["none"]))
        parent.grid_columnconfigure(1, weight=1)

    def _date_row(self, parent, row):
        """日期改为年 / 月 / 日三个滚轮（Spinbox），天数上限随年月自动调整。"""
        c = self.C
        tk.Label(parent, text="日期", width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=row, column=0, pady=SP["sm"])
        cell = tk.Frame(parent, bg=c["dialog_bg"])
        cell.grid(row=row, column=1, sticky="ew", pady=SP["sm"], padx=(SP["sm"], SP["none"]))

        today = cd.today()
        cur = cd.parse_date(self.item.get("date")) or today
        lo_year = min(1970, cur.year)

        kw = dict(font=font(FS["md"]), width=5, justify="center",
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
                 font=font(FS["xs"])).pack(side="left", padx=(SP["xs"], SP["sm"]))
        self.spin_m.pack(side="left")
        tk.Label(cell, text="月", bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=(SP["xs"], SP["sm"]))
        self.spin_d.pack(side="left")
        tk.Label(cell, text="日", bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=(SP["xs"], SP["sm"]))

        tk.Button(cell, text="今天", font=font(FS["xs"]),
                  relief="flat", bg=c["panel_bg"], fg=c["sidebar_muted"],
                  activebackground=c["panel_active"], bd=0, padx=SP["sm"], pady=SP["xs"],
                  command=self._set_today).pack(side="left")

        self._week_label = tk.Label(parent, text="", bg=c["dialog_bg"],
                                    fg=c["sidebar_muted"],
                                    font=font(FS["xs"]))
        self._week_label.grid(row=row + 1, column=1, sticky="w", padx=(SP["sm"], SP["none"]))
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


# ---- 日程计划 ----
class PlanDialog(tk.Toplevel):
    """新建 / 编辑一条日程计划的弹窗。

    和倒计时弹窗同构，差别只在两点：
      · 日期可空——勾选「不限定日期」后这条就是随时可做的待办；
      · 不编辑完成状态（完成 / 重做在卡片勾选框上直接点）。
    """

    WIDTH, HEIGHT = px(430), px(380)

    def __init__(self, master, theme, item=None, on_save=None):
        super().__init__(master)
        c = theme
        self.C = c
        self.item = item or {}
        self.on_save = on_save
        self.title("编辑计划" if item else "新建计划")
        center_window(self, self.WIDTH, self.HEIGHT, master)
        self.configure(bg=c["dialog_bg"])
        self.transient(master)
        self.grab_set()

        dialog_header(self, c, self.title(),
                      "给自己排一件事：定个日子，做完打个勾")

        form = tk.Frame(self, bg=c["dialog_bg"])
        form.pack(fill="x", padx=SP["xl"])

        self.var_title = tk.StringVar(value=self.item.get("title", ""))
        self.var_note = tk.StringVar(value=self.item.get("note", ""))
        # 新建默认定在今天（滚轮已就位）；编辑时按原数据（无日期的待办保持勾选）
        self.var_nodate = tk.BooleanVar(
            value=bool(self.item.get("id")) and not bool(self.item.get("date")))

        self._row(form, "内容", self.var_title, 0)
        self._date_row(form, 1)
        self._row(form, "备注", self.var_note, 3)

        RoundedCheck(self, c, text="不限定日期（随时可做的待办）",
                     variable=self.var_nodate, command=self._sync_nodate,
                     bg=c["dialog_bg"]).pack(anchor="w", padx=SP["xl"],
                                             pady=(SP["sm"], SP["none"]))

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=SP["lg"])
        ModernButton(btns, text="保存", command=self._save, c=c, primary=True,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])
        ModernButton(btns, text="取消", command=self.destroy, c=c,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    # 表单行与倒计时弹窗同款
    def _row(self, parent, label, var, row):
        c = self.C
        tk.Label(parent, text=label, width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=row, column=0, pady=SP["sm"])
        tk.Entry(parent, textvariable=var,
                 font=font(FS["md"]), relief="flat",
                 bg=c["panel_bg"], fg=c["text"],
                 insertbackground=c["text"],
                 highlightthickness=1,
                 highlightbackground=c["divider"]).grid(
            row=row, column=1, sticky="ew", pady=SP["sm"],
            padx=(SP["sm"], SP["none"]))
        parent.grid_columnconfigure(1, weight=1)

    def _date_row(self, parent, row):
        """年 / 月 / 日滚轮（默认今天或已有日期），实时显示星期与倒计时。"""
        c = self.C
        tk.Label(parent, text="日期", width=5, anchor="w",
                 bg=c["dialog_bg"], fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=row, column=0, pady=SP["sm"])
        self._date_cell = tk.Frame(parent, bg=c["dialog_bg"])
        self._date_cell.grid(row=row, column=1, sticky="ew", pady=SP["sm"],
                             padx=(SP["sm"], SP["none"]))

        today = cd.today()
        cur = cd.parse_date(self.item.get("date")) or today

        kw = dict(font=font(FS["md"]), width=5, justify="center",
                  relief="flat", bd=0, bg=c["panel_bg"], fg=c["text"],
                  buttonbackground=c["panel_bg"],
                  insertbackground=c["text"],
                  highlightthickness=1,
                  highlightbackground=c["divider"],
                  highlightcolor=c["accent"])

        self.var_y = tk.StringVar(value=str(cur.year))
        self.var_m = tk.StringVar(value=str(cur.month))
        self.var_d = tk.StringVar(value=str(cur.day))
        self.spin_y = tk.Spinbox(self._date_cell, from_=1970,
                                 to=today.year + 60,
                                 textvariable=self.var_y, **kw)
        self.spin_m = tk.Spinbox(self._date_cell, from_=1, to=12, wrap=True,
                                 textvariable=self.var_m, **kw)
        self.spin_d = tk.Spinbox(self._date_cell, from_=1, to=31, wrap=True,
                                 textvariable=self.var_d, **kw)
        # 三个滚轮都建好后才挂监听，否则构造 spinbox 时会提前触发回调
        for v in (self.var_y, self.var_m, self.var_d):
            v.trace_add("write", self._sync_date)

        self.spin_y.pack(side="left")
        tk.Label(self._date_cell, text="年", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left",
                                          padx=(SP["xs"], SP["sm"]))
        self.spin_m.pack(side="left")
        tk.Label(self._date_cell, text="月", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left",
                                          padx=(SP["xs"], SP["sm"]))
        self.spin_d.pack(side="left")
        tk.Label(self._date_cell, text="日", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left",
                                          padx=(SP["xs"], SP["sm"]))

        self._week_label = tk.Label(parent, text="", bg=c["dialog_bg"],
                                    fg=c["sidebar_muted"],
                                    font=font(FS["xs"]))
        self._week_label.grid(row=row + 1, column=1, sticky="w",
                              padx=(SP["sm"], SP["none"]))
        self._sync_date()
        self._sync_nodate()

    def _sync_nodate(self):
        """「不限定日期」勾选后禁用滚轮并收起星期提示。"""
        state = "disabled" if self.var_nodate.get() else "normal"
        for sp in (self.spin_y, self.spin_m, self.spin_d):
            sp.config(state=state)
        if self.var_nodate.get():
            self._week_label.config(text="不限日期 · 随时可做")
        else:
            self._sync_date()

    def _sync_date(self, *_):
        """滚轮变化时重算：天数上限、纠正越界、同步星期与倒计时文案。"""
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
        self._week_label.config(
            text=f"{cd.weekday_cn(date)} · 还有 "
                 f"{cd.days_until(date, cd.today())} 天"
                 if date > cd.today()
                 else (cd.weekday_cn(date) + " · 就是今天"
                       if date == cd.today()
                       else cd.weekday_cn(date)))

    def _save(self):
        title = self.var_title.get().strip()
        if not title:
            messagebox.showwarning("提示", "请填写计划内容", parent=self)
            return
        if self.var_nodate.get():
            date = ""
        else:
            d = cd.parse_date("-".join((self.var_y.get(),
                                        self.var_m.get(),
                                        self.var_d.get())))
            if d is None:
                messagebox.showwarning("提示", "日期无效，请重新选择",
                                       parent=self)
                return
            date = cd.fmt_date(d)
        if self.on_save:
            self.on_save({"title": title, "date": date,
                          "note": self.var_note.get()})
        self.destroy()


# ---- 番茄钟 ----
POMO_PRESETS = (15, 25, 45, 60, 90)   # 常用专注时长（分钟）


class PomodoroDialog(tk.Toplevel):
    """🍅 番茄钟：自定义专注时长 / 休息时长（滚轮选择）。"""

    W, H = px(400), px(300)

    def __init__(self, master, app, on_start=None):
        super().__init__(master)
        self.app = app
        self.on_start = on_start
        c = self.C = get_theme(getattr(app, "theme_name", DEFAULT_THEME))
        self.title("🍅 番茄钟")
        center_window(self, self.W, self.H, master)
        self.configure(bg=c["dialog_bg"])
        self.resizable(False, False)

        dialog_header(self, c, "🍅 自定义番茄钟",
                      "选好时长后墨墨会捧着书陪你，头顶显示剩余时间")

        grid = tk.Frame(self, bg=c["dialog_bg"])
        grid.pack(fill="x", padx=SP["xl"], pady=(SP["lg"], SP["sm"]))
        grid.grid_columnconfigure(1, weight=1)

        kw = dict(font=font(FS["md"]), width=5, justify="center",
                  relief="flat", bd=0, bg=c["panel_bg"], fg=c["text"],
                  buttonbackground=c["panel_bg"],
                  insertbackground=c["text"],
                  highlightthickness=1,
                  highlightbackground=c["divider"],
                  highlightcolor=c["accent"])

        tk.Label(grid, text="专注", anchor="w", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=0, column=0, pady=SP["sm"])
        self.spin_focus = tk.Spinbox(grid, from_=app.POMO_MIN, to=app.POMO_MAX,
                                     **kw)
        self.spin_focus.delete(0, "end")
        self.spin_focus.insert(0, str(app.pomo_minutes))
        self.spin_focus.grid(row=0, column=1, sticky="w", padx=(SP["sm"], SP["none"]))
        tk.Label(grid, text="分钟", bg=c["dialog_bg"], fg=c["text"],
                 font=font(FS["sm"])).grid(row=0, column=2,
                                                    sticky="w", padx=SP["sm"])

        tk.Label(grid, text="休息", anchor="w", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["sm"])).grid(row=1, column=0, pady=SP["sm"])
        self.spin_break = tk.Spinbox(grid, from_=app.POMO_MIN, to=app.POMO_MAX,
                                     **kw)
        self.spin_break.delete(0, "end")
        self.spin_break.insert(0, str(app.pomo_break))
        self.spin_break.grid(row=1, column=1, sticky="w", padx=(SP["sm"], SP["none"]))
        tk.Label(grid, text="分钟", bg=c["dialog_bg"], fg=c["text"],
                 font=font(FS["sm"])).grid(row=1, column=2,
                                                    sticky="w", padx=SP["sm"])

        preset = tk.Frame(self, bg=c["dialog_bg"])
        preset.pack(fill="x", padx=SP["xl"], pady=(SP["xs"], SP["sm"]))
        tk.Label(preset, text="常用：", bg=c["dialog_bg"],
                 fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left")
        for m in POMO_PRESETS:
            tk.Button(preset, text=f"{m} 分钟", font=font(FS["xs"]),
                      relief="flat", bg=c["panel_bg"], fg=c["text"],
                      activebackground=c["panel_active"], bd=0,
                      padx=SP["sm"], pady=SP["xs"],
                      command=lambda mm=m: self._set_focus(mm)).pack(
                side="left", padx=SP["xs"])

        self.var_remember = tk.BooleanVar(value=True)
        RoundedCheck(self, c, text="记住为默认时长（下次直接开始）",
                     variable=self.var_remember,
                     bg=c["dialog_bg"]).pack(anchor="w", padx=SP["xl"],
                                             pady=(SP["xs"], SP["xs"]))

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=(SP["md"], SP["lg"]))
        ModernButton(btns, text="开始专注", command=self._ok, c=c, primary=True,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])
        ModernButton(btns, text="取消", command=self.destroy, c=c,
                     bg=c["dialog_bg"]).pack(side="left", padx=SP["sm"])

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

    W, H = px(380), px(230)

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

        dialog_header(self, c, "⌨ 自定义全局热键",
                      "直接按下你想要的组合键（例如 Ctrl+Alt+M）")

        self.var = tk.StringVar(value=hotkey.combo_text(self.mod, self.vk))
        tk.Label(self, textvariable=self.var,
                 font=("Consolas", 18, "bold"),
                 bg=c["panel_bg"], fg=c["accent"], width=18,
                 pady=SP["sm"]).pack(pady=SP["lg"])
        self.hint = tk.Label(self, text="等待按键…", bg=c["dialog_bg"],
                             fg=c["sidebar_muted"],
                             font=font(FS["xs"]))
        self.hint.pack()

        btns = tk.Frame(self, bg=c["dialog_bg"])
        btns.pack(pady=(SP["md"], SP["md"]))
        ModernButton(btns, text="保存", command=self._save, c=c,
                     primary=True).pack(side="left", padx=SP["sm"])
        ModernButton(btns, text="清除", command=self._clear,
                     c=c).pack(side="left", padx=SP["sm"])
        ModernButton(btns, text="取消", command=self.destroy,
                     c=c).pack(side="left", padx=SP["sm"])

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
    key = "countdowns"            # 历史遗留 key，改名后不动（config 兼容）
    title = "时间管理"
    subtitle = "日程计划 + 倒数日：安排要做的事，记住重要的日子"
    REFRESH_MS = 60000        # 每分钟刷新一次，过零点后自动更新

    def __init__(self, master, app):
        self._job = None
        super().__init__(master, app)

    def _build(self):
        paused = bool(self.app.pomodoro and self.app.pomodoro.get("paused"))
        pause_text = "继续番茄钟" if paused else "暂停番茄钟"
        self._toolbar([("calendar", "新建计划", self._add_plan),
                       ("clock", "新建倒计时", self._add),
                       ("grid", "开始番茄钟", self._start_pomo),
                       ("pause" if not paused else "play", pause_text,
                        self._pause_pomo),
                       ("close", "结束番茄钟", self._stop_pomo),
                       ("refresh", "刷新", self.refresh)])
        self.body = self._scroll_body().body
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

    def _pause_pomo(self):
        """暂停 / 继续番茄钟（顶栏和桌宠气泡同步显示状态）。"""
        if not self.app.pomodoro:
            messagebox.showinfo("🍅 番茄钟",
                                "当前没有正在进行的番茄钟～",
                                parent=self.app)
            return
        self.app.pause_or_resume_pomodoro()

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
        # 用户拖过一次排序后按手动顺序展示；否则用「逾期 → 今天 → 未来」智能排序
        if self.cfg.data.get("plans_manual_order"):
            plans = list(self.cfg.plans)
        else:
            plans = sorted(self.cfg.plans, key=cd.plan_sort_key)
        items = sorted(self.cfg.countdowns, key=cd.sort_key)

        self._plan_section(plans)
        hline(self.body, c["divider"], pady=(SP["lg"], SP["xs"]))
        self._countdown_section(items)

        todo = sum(1 for p in plans if not p.get("done"))
        parts = []
        if plans:
            parts.append(f"{todo} 个待办 / 共 {len(plans)} 个计划")
        if items:
            parts.append(f"{len(items)} 个倒数日")
        self.app.update_topbar(" · ".join(parts) if parts else "时间管理")

    # ---- 日程计划 ----
    def _section_title(self, text):
        """区块小标题（日程计划 / 倒数日两段的共同样式）。"""
        tk.Label(self.body, text=text, bg=self.C["app_bg"],
                 fg=self.C["sidebar_muted"], font=font(FS["sm"], "bold"),
                 anchor="w").pack(fill="x", pady=(SP["sm"], SP["xs"]))

    def _plan_section(self, plans):
        c = self.C
        head = tk.Frame(self.body, bg=c["app_bg"])
        head.pack(fill="x", pady=(SP["sm"], SP["xs"]))
        tk.Label(head, text="📋 日程计划", bg=c["app_bg"],
                 fg=c["sidebar_muted"], font=font(FS["sm"], "bold"),
                 anchor="w").pack(side="left")
        if plans:
            tk.Label(head, text="按住卡片可拖动排序", bg=c["app_bg"],
                     fg=c["sidebar_muted"], font=font(FS["xs"])).pack(
                side="right")
        if not plans:
            tk.Label(self.body, text="还没有计划 · 点上方「新建计划」排第一件事",
                     bg=c["app_bg"], fg=c["sidebar_muted"],
                     font=font(FS["xs"])).pack(anchor="w",
                                               pady=(SP["none"], SP["sm"]))
            return
        for item in plans:
            self._plan_card(item)

    def _plan_card(self, item):
        c = self.C
        done = bool(item.get("done"))
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=SP["lg"], pady=SP["md"])
        card.pack(fill="x", pady=SP["xs"])

        self._check_box(card, item).pack(side="left", anchor="n",
                                         padx=(SP["none"], SP["md"]))

        mid = tk.Frame(card, bg=c["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        fg = c["sidebar_muted"] if done else c["text"]
        styles = ("bold", "overstrike") if done else ("bold",)
        title_lab = tk.Label(mid, text=item.get("title", ""), bg=c["card_bg"],
                             fg=fg, font=font(FS["md"], *styles), anchor="w")
        title_lab.pack(fill="x")
        tk.Label(mid, text=self._plan_date_text(item), bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(FS["xs"]),
                 anchor="w").pack(fill="x")
        if item.get("note"):
            note_lab = tk.Label(mid, text=item["note"], bg=c["card_bg"],
                                fg=c["sidebar_muted"], font=font(FS["xs"]),
                                anchor="w", justify="left")
            note_lab.pack(fill="x")
            note_lab.bind("<Configure>", lambda e, l=note_lab:
                          l.configure(wraplength=max(px(80), e.width - SP["sm"])))
        title_lab.bind("<Configure>", lambda e, l=title_lab:
                       l.configure(wraplength=max(px(80), e.width - SP["sm"])))

        # 拖拽排序：按住卡片空白处（不是勾选框 / 按钮）上下拖动换位
        pid = item.get("id")
        card._plan_id = pid
        for w in (card, mid) + tuple(mid.winfo_children()):
            w.bind("<Button-1>", lambda e, p=pid: self._drag_start(e, p))
            w.bind("<B1-Motion>", lambda e, p=pid: self._drag_move(e, p))
            w.bind("<ButtonRelease-1>", lambda e, p=pid: self._drag_drop(e, p))

        acts = (("编辑", lambda pid=pid: self._edit_plan(pid)),
                ("删除", lambda pid=pid: self._delete_plan(pid), True))
        self._card_buttons(card, acts)

    def _check_box(self, parent, item):
        """完成 / 重做勾选框：点一下翻面（公共组件 RoundedCheck）。"""
        var = tk.BooleanVar(value=bool(item.get("done")))

        def toggle():
            self.cfg.update_plan(item.get("id"), done=var.get())
            self.refresh()

        return RoundedCheck(parent, self.C, variable=var, command=toggle,
                            bg=self.C["card_bg"])

    # ---- 拖拽排序 ----
    def _drag_start(self, event, pid):
        card = self._find_plan_card(pid)
        if card is None:
            return
        self._drag = {"id": pid, "card": card,
                      "y0": event.y_root, "start_y": card.winfo_y(),
                      "h": card.winfo_height(), "active": False}

    def _drag_move(self, event, pid):
        drag = getattr(self, "_drag", None)
        if not drag or drag["id"] != pid:
            return
        if not drag["active"]:
            # 超过阈值才算开始拖，避免和「点按选中」打架
            if abs(event.y_root - drag["y0"]) <= px(6):
                return
            drag["active"] = True
            drag["card"].place(relwidth=1, y=drag["start_y"])
            drag["card"].lift()
            drag["card"].configure(cursor="fleur",
                                   highlightbackground=self.C["accent"])
        cards = self._plan_card_widgets()
        if not cards:
            return
        top = cards[0].winfo_y()
        bottom = cards[-1].winfo_y() + cards[-1].winfo_height()
        new_y = drag["start_y"] + (event.y_root - drag["y0"])
        new_y = max(top, min(new_y, bottom - drag["h"]))
        drag["card"].place(y=new_y)

    def _drag_drop(self, event, pid):
        drag = getattr(self, "_drag", None)
        self._drag = None
        if not drag or drag["id"] != pid or not drag.get("active"):
            return
        # 松手位置插到哪张卡片前面（按各卡片纵向中心比较）
        before_id = None
        for w in self._plan_card_widgets():
            if w is drag["card"]:
                continue
            if event.y_root < w.winfo_rooty() + w.winfo_height() / 2:
                before_id = w._plan_id
                break
        self.cfg.move_plan(pid, before_id)
        self.refresh()

    def _find_plan_card(self, pid):
        for w in self._plan_card_widgets():
            if getattr(w, "_plan_id", None) == pid:
                return w
        return None

    def _plan_card_widgets(self):
        """body 里所有计划卡片（按 pack 顺序），区块标题 / 分隔线不算。"""
        return [w for w in self.body.winfo_children()
                if getattr(w, "_plan_id", None) is not None]

    @staticmethod
    def _plan_date_text(item) -> str:
        info = cd.plan_describe(item)
        if info["state"] == "nodate":
            return info["text"]
        when = cd.weekday_cn(info["target"])
        return f"{cd.fmt_date(info['target'])} {when} · {info['text']}"

    # ---- 计划的增删改 ----
    def _add_plan(self):
        PlanDialog(self.app, self.C,
                   on_save=lambda data: self._save_plan(None, data))

    def _edit_plan(self, pid):
        item = self.cfg.get_plan(pid)
        if item is None:
            return
        PlanDialog(self.app, self.C, item=item,
                   on_save=lambda data: self._save_plan(pid, data))

    def _save_plan(self, pid, data):
        if pid:
            self.cfg.update_plan(pid, **data)
        else:
            self.cfg.add_plan(**data)
        self.refresh()

    def _delete_plan(self, pid):
        item = self.cfg.get_plan(pid)
        if item is None:
            return
        if messagebox.askyesno("删除计划",
                               f"删除计划「{item.get('title', '')}」？",
                               parent=self.app):
            self.cfg.remove_plan(pid)
            self.refresh()

    # ---- 倒数日 ----
    def _countdown_section(self, items):
        c = self.C
        self._section_title("⏳ 倒数日")
        if not items:
            tk.Label(self.body, text="还没有倒数日 · 点上方「新建倒计时」"
                                     "记住一个重要的日子",
                     bg=c["app_bg"], fg=c["sidebar_muted"],
                     font=font(FS["xs"])).pack(anchor="w",
                                               pady=(SP["none"], SP["sm"]))
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

    # ---- 卡片 ----
    def _focus_card(self, item):
        """置顶大卡：把最近的日子放大显示，起到提醒作用。"""
        c = self.C
        info = cd.describe(item)
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=2,
                        highlightbackground=c["accent"], padx=SP["lg"], pady=SP["lg"])
        card.pack(fill="x", pady=(SP["sm"], SP["md"]))

        left = tk.Frame(card, bg=c["card_bg"])
        left.pack(side="left", fill="both", expand=True)

        num_color = c["accent"] if info["state"] != "past" else c["sidebar_muted"]
        tk.Label(left, text=self._big_number(info), bg=c["card_bg"],
                 fg=num_color, font=font(FS["hero"], "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(left, text=item.get("title", ""), bg=c["card_bg"], fg=c["text"],
                 font=font(FS["lg"], "bold"), anchor="w").pack(anchor="w")
        tk.Label(left, text=self._date_text(item, info), bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(FS["sm"]),
                 anchor="w").pack(anchor="w", pady=(SP["xs"], SP["none"]))
        if item.get("note"):
            tk.Label(left, text=item["note"], bg=c["card_bg"],
                     fg=c["sidebar_muted"], font=font(FS["xs"]),
                     anchor="w").pack(anchor="w")
        self._progress_row(left, item)
        self._actions(card, item, card)

    def _card(self, item):
        c = self.C
        info = cd.describe(item)
        card = tk.Frame(self.body, bg=c["card_bg"], highlightthickness=1,
                        highlightbackground=c["divider"], padx=SP["lg"], pady=SP["md"])
        card.pack(fill="x", pady=SP["sm"])

        num_color = c["accent"] if info["state"] != "past" else c["sidebar_muted"]
        left = tk.Frame(card, bg=c["card_bg"], width=118)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text=self._big_number(info), bg=c["card_bg"],
                 fg=num_color, font=font(FS["xl"], "bold"),
                 anchor="center").pack(fill="x")

        mid = tk.Frame(card, bg=c["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        title_lab = tk.Label(mid, text=item.get("title", ""), bg=c["card_bg"],
                             fg=c["text"], font=font(FS["md"], "bold"),
                             anchor="w")
        title_lab.pack(fill="x")
        tk.Label(mid, text=self._date_text(item, info), bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(FS["xs"]),
                 anchor="w").pack(fill="x")
        if item.get("note"):
            note_lab = tk.Label(mid, text=item["note"], bg=c["card_bg"],
                                fg=c["sidebar_muted"], font=font(FS["xs"]),
                                anchor="w", wraplength=200, justify="left")
            note_lab.pack(fill="x")
            # 备注写长了会把右侧按钮挤出卡片：随卡片宽度折行
            note_lab.bind("<Configure>", lambda e, l=note_lab:
                          l.configure(wraplength=max(80, e.width - SP["sm"])))
        title_lab.bind("<Configure>", lambda e, l=title_lab:
                       l.configure(wraplength=max(80, e.width - SP["sm"])))
        self._progress_row(mid, item)
        self._actions(card, item, card)

    def _actions(self, parent, item, card=None):
        """卡片右侧的编辑 / 删除按钮（置顶大卡和普通卡片共用）。

        card 非空时，整张卡片及其子控件再挂一个右键菜单，方便直接操作。
        """
        c = self.C
        cid = item.get("id")
        # 注意：必须用默认参数锁住 cid，否则 lambda 捕获循环变量会删错条目
        acts = (("编辑", lambda cid=cid: self._edit(cid)),
                ("删除", lambda cid=cid: self._delete(cid), True))
        self._card_buttons(parent, acts)

        if card is None:
            return
        menu = tk.Menu(card, tearoff=0)
        style_menu(menu, c)
        # acts 里可能有第三元素（是否主操作，_card_buttons 用），这里只取前两个
        for text, cmd, *_ in acts:
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
        row.pack(fill="x", pady=(SP["sm"], SP["none"]))
        stat_bar(row, ratio, c, width=260, stretch=True)
        tk.Label(row, text=f"{ratio * 100:.0f}%", bg=c["card_bg"],
                 fg=c["sidebar_muted"], font=font(FS["xs"])).pack(
            side="left", padx=SP["sm"])

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
# 5. 设置页
# ======================================================================
class SettingsPage(BasePage):
    key = "settings"
    title = "设置"
    subtitle = "外观、桌面宠物与侧边栏"

    def _build(self):
        c = self.C
        self.body = self._scroll_body(pady=SP["md"]).body

        self._section("外观主题")
        self.var = tk.StringVar(value=self.app.theme_name)
        for key in ("light", "dark"):
            tk.Radiobutton(self.body, text=THEME_NAMES[key], value=key,
                           variable=self.var, font=font(FS["sm"]),
                           bg=c["app_bg"], fg=c["text"],
                           selectcolor=c["panel_bg"],
                           activebackground=c["app_bg"],
                           activeforeground=c["text"],
                           highlightthickness=0, bd=0,
                           command=self._pick_theme).pack(anchor="w", pady=SP["xs"])
        chips = tk.Frame(self.body, bg=c["app_bg"])
        chips.pack(anchor="w", pady=SP["sm"])
        for name, key in (("背景", "app_bg"), ("磁贴", "panel_bg"),
                          ("卡片", "card_bg"), ("强调", "accent")):
            tk.Label(chips, text=name, width=6, font=font(FS["xs"]),
                     bg=c[key], fg=c["text"], padx=SP["xs"], pady=SP["sm"]).pack(side="left", padx=SP["xs"])

        self._section("首页磁贴尺寸")
        tile_row = tk.Frame(self.body, bg=c["app_bg"])
        tile_row.pack(anchor="w", pady=SP["xs"])
        self._tile_var = tk.StringVar(
            value=str(self.cfg.get_setting("tile_size", "auto") or "auto"))
        for val, text in (("auto", "随窗口自适应"), ("small", "小"),
                          ("normal", "标准"), ("large", "大")):
            tk.Radiobutton(tile_row, text=text, value=val,
                           variable=self._tile_var, font=font(FS["sm"]),
                           bg=c["app_bg"], fg=c["text"],
                           selectcolor=c["panel_bg"],
                           activebackground=c["app_bg"],
                           activeforeground=c["text"],
                           highlightthickness=0, bd=0,
                           command=self._pick_tile_size).pack(
                side="left", padx=(SP["none"], SP["md"]))
        tk.Label(self.body, text="自适应：窗口拉大时磁贴跟着变大（图标、"
                                 "文件夹预览、文字一同比放大）；"
                                 "也可以固定成小 / 标准 / 大。",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(anchor="w")

        self._section("桌面宠物")
        pet_row = tk.Frame(self.body, bg=c["app_bg"])
        pet_row.pack(anchor="w", pady=SP["xs"])
        pet_text = "收起宠物" if self.app.pet_active() else "召唤宠物"
        self._pet_btn = ModernButton(
            pet_row, text=pet_text, command=lambda: self._pet(self._pet_btn),
            c=c, icon="pet", primary=not self.app.pet_active())
        self._pet_btn.pack(side="left")
        tk.Label(pet_row, text="墨墨会悬浮在桌面上：可拖拽抛掷（重力弹跳）、"
                               "点击摸头会开心",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=SP["md"])

        pomo_row = tk.Frame(self.body, bg=c["app_bg"])
        pomo_row.pack(anchor="w", pady=SP["xs"])
        running = bool(self.app.pomodoro)
        pomo_text = "结束番茄钟" if running else "开始番茄钟"
        spin_kw = dict(font=font(FS["sm"]), width=4, justify="center",
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
                     font=font(FS["xs"])).pack(side="left", padx=(SP["xs"], SP["sm"]))
        ModernButton(pomo_row, text=pomo_text, command=self._toggle_pomodoro,
                     c=c, icon="clock", primary=not running).pack(side="left")
        self.var_pomo_break = tk.IntVar(value=self.app.pomo_break)
        if not running:
            self.spin_pomo_break = tk.Spinbox(
                pomo_row, from_=self.app.POMO_MIN, to=self.app.POMO_MAX,
                textvariable=self.var_pomo_break, **spin_kw)
            self.spin_pomo_break.pack(side="left", padx=(SP["md"], SP["none"]))
            tk.Label(pomo_row, text="分钟休息", bg=c["app_bg"],
                     fg=c["text"], font=font(FS["xs"])).pack(
                side="left", padx=(SP["xs"], SP["xs"]))
        tk.Label(pomo_row,
                 text=("专注结束后墨墨会收起倒计时、提醒你休息"
                       if running else
                       "自定义专注时长：开启后墨墨捧书陪你，头顶倒计时"),
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=SP["md"])

        monitor_row = tk.Frame(self.body, bg=c["app_bg"])
        monitor_row.pack(anchor="w", pady=SP["xs"])
        self._monitor_var = tk.BooleanVar(
            value=bool(self.app.cfg.get_setting("pet_monitor", True)))
        RoundedCheck(monitor_row, c,
                     text="系统状态联动（CPU 高冒汗 / 内存不足疲惫 / 网速快奔跑）",
                     variable=self._monitor_var, command=self._toggle_monitor,
                     bg=c["app_bg"]).pack(side="left")

        self._section("全局热键")
        hk_top = tk.Frame(self.body, bg=c["app_bg"])
        hk_top.pack(anchor="w", pady=SP["xs"])
        self._hk_var = tk.BooleanVar(
            value=bool(self.app.cfg.get_setting("hotkey_enabled", True)))
        RoundedCheck(hk_top, c, text="启用全局热键（窗口隐藏时也能一键呼出）",
                     variable=self._hk_var, command=self._toggle_hotkey,
                     bg=c["app_bg"]).pack(side="left")

        hk_row = tk.Frame(self.body, bg=c["app_bg"])
        hk_row.pack(anchor="w", pady=SP["xs"])
        tk.Label(hk_row, text="当前：", bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left")
        tk.Label(hk_row, text=self.app.hotkey_text(), bg=c["app_bg"],
                 fg=c["accent"], font=font(FS["sm"], "bold")).pack(
            side="left", padx=(SP["none"], SP["md"]))
        ModernButton(hk_row, text="修改快捷键", command=self._pick_hotkey,
                     c=c, icon="gear", primary=True).pack(side="left",
                                                          padx=(SP["none"], SP["sm"]))
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
                 font=font(FS["xs"]), anchor="w",
                 justify="left").pack(fill="x", pady=(SP["xs"], SP["none"]))

        self._section("侧边栏")
        sb_row = tk.Frame(self.body, bg=c["app_bg"])
        sb_row.pack(anchor="w", pady=SP["xs"])
        ModernButton(sb_row, text="折叠 / 展开", command=self.app.toggle_sidebar,
                     c=c, icon="collapse").pack(side="left")
        tk.Label(sb_row, text="折叠后只显示图标，状态会自动记住",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"])).pack(side="left", padx=SP["md"])

        self._section("数据管理")
        data_row = tk.Frame(self.body, bg=c["app_bg"])
        data_row.pack(anchor="w", pady=SP["xs"])
        ModernButton(data_row, text="导出配置", command=self._export_config,
                     c=c, icon="folder").pack(side="left",
                                              padx=(SP["none"], SP["sm"]))
        ModernButton(data_row, text="导入配置", command=self._import_config,
                     c=c, icon="refresh").pack(side="left",
                                               padx=(SP["none"], SP["sm"]))
        ModernButton(data_row, text="清理配置", command=self._clean_config,
                     c=c, icon="close").pack(side="left")
        tk.Label(self.body,
                 text="配置 = 分类 / 计划 / 倒计时 / 主题 / 番茄钟设置。\n"
                      "清理前会自动备份为 config.json.bak；导入会先校验格式。",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"]), justify="left",
                 anchor="w").pack(anchor="w")

        self._section("关于")
        tk.Label(self.body,
                 text=f"墨墨桌面管理助手 {APP_VERSION}\n"
                      "纯 Python 标准库实现（tkinter），无需任何第三方依赖。",
                 bg=c["app_bg"], fg=c["sidebar_muted"],
                 font=font(FS["xs"]), justify="left",
                 anchor="w").pack(anchor="w")

        self.app.update_topbar(f"当前主题：{THEME_NAMES[self.app.theme_name]}")

    # ---- 数据管理：导出 / 导入 / 清理 ----
    def _export_config(self):
        from tkinter import filedialog
        if not os.path.isfile(self.cfg.path):
            messagebox.showinfo("导出配置", "还没有 config.json，无需导出～",
                                parent=self.app)
            return
        path = filedialog.asksaveasfilename(
            parent=self.app, defaultextension=".json",
            initialfile="momo-config-backup.json",
            filetypes=[("JSON 配置", "*.json")],
            title="导出配置到…")
        if not path:
            return
        try:
            import shutil
            shutil.copyfile(self.cfg.path, path)
        except OSError as e:
            messagebox.showerror("导出失败", str(e), parent=self.app)
            return
        messagebox.showinfo("导出完成", f"配置已导出到：\n{path}", parent=self.app)

    def _import_config(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self.app, filetypes=[("JSON 配置", "*.json")],
            title="选择要导入的配置文件")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showerror("导入失败", "文件读不了或不是合法 JSON：\n%s" % e,
                                 parent=self.app)
            return
        if not isinstance(data, dict):
            messagebox.showerror("导入失败", "文件内容不是配置对象（顶层必须是 {}）",
                                 parent=self.app)
            return
        if not messagebox.askyesno(
                "导入配置", "将用该文件替换当前全部分类 / 计划 / 倒计时 / 设置，\n"
                           "当前配置会先备份为 config.json.bak。继续？",
                parent=self.app):
            return
        if not self.cfg.replace_all(data):
            messagebox.showerror("导入失败", "配置格式非法，未做修改。",
                                 parent=self.app)
            return
        self.app._apply_theme(self.cfg.get_setting("theme", "light"))
        messagebox.showinfo("导入完成", "配置已导入并生效。", parent=self.app)

    def _clean_config(self):
        if not messagebox.askyesno(
                "清理配置", "将清空全部分类 / 计划 / 倒计时 / 设置并恢复默认\n"
                           "（会先备份为 config.json.bak）。确定？",
                parent=self.app):
            return
        if not self.cfg.replace_all({}):
            return
        self.app._apply_theme("light")
        messagebox.showinfo("清理完成", "已恢复默认配置。", parent=self.app)

    def _section(self, text):
        c = self.C
        tk.Label(self.body, text=text, bg=c["app_bg"], fg=c["text"],
                 font=font(FS["sm"], "bold"), anchor="w").pack(
            fill="x", pady=(SP["lg"], SP["xs"]))
        hline(self.body, c["divider"], pady=(SP["none"], SP["sm"]))

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

    def _pick_tile_size(self):
        """改磁贴尺寸档位：写进配置，并让已缓存的首页立刻重排一次。"""
        self.cfg.set_setting("tile_size", self._tile_var.get())
        page = getattr(self.app, "_pages", {}).get("home")
        if page is not None:
            page.refresh(rescan=False)

    def _pet(self, btn=None):
        """召唤 / 收起桌宠，并把按钮文字同步过来。"""
        self.app._toggle_pet()
        if btn is not None:
            btn.set_text("收起宠物" if self.app.pet_active() else "召唤宠物")


PAGES = (DesktopPage, CategoriesPage, StatsPage,
         CountdownPage, SettingsPage)
PAGE_BY_KEY = {p.key: p for p in PAGES}
