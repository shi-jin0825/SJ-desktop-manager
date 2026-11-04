# -*- coding: utf-8 -*-
"""主框架（Shell）：左侧边栏导航 + 右侧主内容区。

布局约定：
    左侧边栏  ── 顶部：用户头像 / 当前用户
              ── 中部：导航菜单（首页 / 分类 / 统计 / 时间管理 / 设置）
              ── 底部：折叠侧边栏、退出
    右侧主区  ── 顶部标题条 + 下方内容区（点击左侧菜单切换页面）

具体页面在 gui/pages.py 里实现，这里只负责路由与全局能力
（主题、桌宠、窗口居中）。
"""
import os
import re
import tkinter as tk
from tkinter import messagebox

from core.config import ConfigManager
from core.icons import icon_png  # noqa: F401（保持与旧引用兼容）
from core import hotkey
from gui.theme import DEFAULT_THEME, THEMES, THEME_NAMES, get_theme
from gui.fonts import font
from gui.tokens import (AVATAR, BTN_H, FS, NAV_H, NAV_H_MIN, NAV_H_SM,
                        NAV_ICON, NAV_ICON_SM, NAV_PAD, SIDEBAR_W,
                        SIDEBAR_W_MINI, SP, TEXT_PAD, TOPBAR_H, px)
from gui.pages import PAGE_BY_KEY, DesktopPage, APP_VERSION
from gui.navicons import IconLabel
from gui.widgets import (center_window, fit_label, load_image_file, hline,
                         ModernButton, RoundedEntry)

APP_TITLE = "墨墨桌面管理助手"
# 窗口尺寸也随 DPI 缩放：字体在高分屏上被 Tk 放大，窗口、下限不同步的话
# 内容根本装不下（v1.9 里侧栏文字被截，就是容器没跟着字走）
WIN_W, WIN_H = px(1120), px(700)
MIN_W, MIN_H = px(560), px(420)   # 能缩到的最小尺寸（和普通软件一样可以缩得很小）
# 窄到这个宽度就自动收起侧边栏，把宽度让给内容区：阈值取「内容区至少还剩
# MIN_W」——栏加宽后 780 会留下过窄的内容区，反而不如收起侧栏。
AUTO_COLLAPSE_W = MIN_W + SIDEBAR_W
NARROW_W = px(700)                # 再窄就藏起标题条里的副标题

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets")

# 导航菜单：(页面 key, 线性图标名, 名称) —— 图标统一由 gui/navicons.py 绘制
NAV_ITEMS = (
    ("home", "home", "首页"),
    ("categories", "grid", "分类管理"),
    ("stats", "chart", "数据统计"),
    ("countdowns", "calendar", "时间管理"),
    ("settings", "gear", "设置"),
)

MOD_LABEL = ((hotkey.MOD_WIN, "Win"), (hotkey.MOD_CONTROL, "Ctrl"),
             (hotkey.MOD_ALT, "Alt"), (hotkey.MOD_SHIFT, "Shift"))


class App(tk.Tk):
    """主窗口：侧边栏 + 内容区。"""

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.config_mgr = ConfigManager()
        self.cfg = self.config_mgr      # 简写别名（桌宠等模块用）
        self.theme_name = self.config_mgr.get_setting("theme", DEFAULT_THEME)
        self.C = get_theme(self.theme_name)
        self.collapsed = bool(self.config_mgr.get_setting("sidebar_collapsed", False))
        self._pet = None            # 桌面悬浮宠物（None = 未召唤）
        self.pomodoro = None        # 番茄钟 {"end": 时间戳, "minutes": N}
        self._pomo_job = None
        self.current_key = "home"
        self.current_page = None
        self._photos = []           # 头像等图片引用，防止被回收
        self.query = ""             # 全局搜索关键字（空 = 不过滤）
        self.search_entry = None
        self._hidden = False        # 被全局热键隐藏
        self.hk = hotkey.GlobalHotkey()

        try:
            from core import sysinfo as _sysinfo
            _sysinfo.prime()        # 预热 CPU / 网速采样基准
        except Exception:
            pass

        self.configure(bg=self.C["app_bg"])
        self._set_icon()
        self.minsize(MIN_W, MIN_H)
        if not self._restore_geometry():
            self._fit_to_screen()
        self.bind("<Configure>", self._on_window_resize)

        self._build_shell()
        self._show_page("home")
        self._notify_load_status()

        self.bind("<F5>", self._on_f5)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self._init_hotkey()

    def _fit_to_screen(self):
        """初始大小不超过屏幕的 90% —— 小屏笔记本上别一启动就顶满屏。"""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        center_window(self,
                      max(MIN_W, min(WIN_W, int(sw * 0.9))),
                      max(MIN_H, min(WIN_H, int(sh * 0.88))))

    def _on_window_resize(self, event=None):
        """窗口被拉窄到一定程度时自动收起侧边栏，把宽度让给内容区。

        只在「这次折叠是自动的」时才自动展开，不覆盖用户手动折叠的意图；
        自动折叠也不写进配置，下次启动仍是用户自己选的状态。
        """
        if event is not None and event.widget is not self:
            return
        w = self.winfo_width()
        if w <= 1:
            return
        if w >= AUTO_COLLAPSE_W:
            self._search_expanded = False
        if (w < AUTO_COLLAPSE_W and not self.collapsed
                and not getattr(self, "_search_expanded", False)):
            self._auto_collapsed = True
            self.toggle_sidebar(persist=False)
        elif w >= AUTO_COLLAPSE_W and getattr(self, "_auto_collapsed", False):
            self._auto_collapsed = False
            self.toggle_sidebar(persist=False)
        self._update_topbar_density()
        # Configure 触发时子控件还没重新布局，量到的高度是旧的，
        # 所以这里补一次空闲后的重排（只在档位真变了才重建，不会抖）
        self._relayout_nav_if_needed()
        self.after_idle(self._relayout_nav_if_needed)

    def _update_topbar_density(self):
        """很窄的窗口里藏起副标题，保住主标题不被挤出标题条。"""
        sub = getattr(self, "page_sub", None)
        if sub is None:
            return
        if self.winfo_width() < NARROW_W:
            sub.pack_forget()
        else:
            try:
                sub.pack(side="left", padx=SP["xs"])
            except tk.TclError:
                pass

    def _restore_geometry(self):
        """恢复上次退出时的窗口大小和位置。

        用户把窗口拉大是想一直用这个尺寸——每次启动都回到初始大小等于白调。
        换过显示器 / 拔掉外接屏时旧坐标可能整个跑到屏幕外，这里做夹限兜底。
        """
        geom = str(self.config_mgr.get_setting("window_geometry", "") or "")
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geom)
        if not m:
            return False
        w, h, x, y = (int(v) for v in m.groups())
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        # 下限必须引用 MIN_W/MIN_H：早先这里写死 900×560，于是
        # 「能把窗口缩多小」和「记住你上次缩到多大」两个特性互相打架——
        # 缩到 600×450 退出，下次启动又被弹回 900×560。
        w, h = max(MIN_W, min(w, sw)), max(MIN_H, min(h, sh))
        x, y = max(0, min(x, sw - 120)), max(0, min(y, sh - 120))
        self.geometry(f"{w}x{h}+{x}+{y}")
        return True

    def _save_geometry(self):
        """退出前记下窗口大小位置（最小化时坐标是 -32000 那种，跳过不存）。"""
        try:
            geom = self.geometry()
        except tk.TclError:
            return
        if geom and not geom.startswith("-"):
            self.config_mgr.set_setting("window_geometry", geom)

    # ---------------- 全局热键 ----------------
    def _init_hotkey(self):
        """按配置注册全局热键，并开始轮询（每 200ms 看一次）。"""
        enabled = bool(self.config_mgr.get_setting("hotkey_enabled", True))
        if not enabled:
            self.hk.unregister()
            return
        mod = int(self.config_mgr.get_setting("hotkey_mod", hotkey.DEFAULT_HOTKEY[0]) or 0)
        vk = int(self.config_mgr.get_setting("hotkey_vk", hotkey.DEFAULT_HOTKEY[1]) or 0)
        self.hk_auto = ""
        try:
            hwnd = int(self.winfo_id())
        except Exception:
            hwnd = None
        if not self.hk.register(mod, vk, hwnd):
            # 组合被别的程序占了：自动换一个能用的（并写回配置，界面显示一致）
            for m, v in hotkey.HOTKEY_FALLBACKS:
                if (m, v) == (mod, vk):
                    continue
                if self.hk.register(m, v, hwnd):
                    self.config_mgr.set_setting("hotkey_mod", m)
                    self.config_mgr.set_setting("hotkey_vk", v)
                    self.hk_auto = ("「%s」被其它程序占用，已自动改用「%s」"
                                    % (hotkey.combo_text(mod, vk),
                                       hotkey.combo_text(m, v)))
                    break
        if not getattr(self, "_hotkey_polling", False):
            self._hotkey_polling = True     # 轮询链只启动一次
            self.after(200, self._hotkey_poll)

    def _hotkey_poll(self):
        try:
            if self.hk.poll():
                self.toggle_window()
        except Exception:
            pass
        self.after(200, self._hotkey_poll)

    def hotkey_text(self) -> str:
        """当前热键的可读文本（供设置页显示）。"""
        if not self.config_mgr.get_setting("hotkey_enabled", True):
            return "（已关闭）"
        mod = int(self.config_mgr.get_setting("hotkey_mod", hotkey.DEFAULT_HOTKEY[0]) or 0)
        vk = int(self.config_mgr.get_setting("hotkey_vk", hotkey.DEFAULT_HOTKEY[1]) or 0)
        return hotkey.combo_text(mod, vk) or "（未设置）"

    def reload_hotkey(self):
        """设置页改完热键后重新注册。"""
        self.hk.unregister()
        self._init_hotkey()

    def toggle_window(self):
        """热键：一键呼出 / 隐藏主窗口。"""
        if self._hidden or str(self.state()) == "withdrawn":
            self.deiconify()
            self.lift()
            try:
                self.attributes("-topmost", True)
                self.after(200, lambda: self.attributes("-topmost", False))
            except tk.TclError:
                pass
            self.focus_force()
            self._hidden = False
        else:
            self._hidden = True
            self.withdraw()
            pet = getattr(self, "_pet", None)
            if pet is not None:
                try:
                    pet._bubble.say(f"按 {self.hotkey_text()} 可以随时叫我回来～", 4000)
                except Exception:
                    pass

    def _notify_load_status(self):
        """配置层记录了"这次读取不顺利"时，明确告诉用户一次。

        load_status 之前只躺在 ConfigManager 里没人读 —— 用户看到的是
        "分类怎么少了"，而不是"配置损坏已恢复"。
        """
        status = getattr(self.config_mgr, "load_status", "")
        if not status:
            return
        note = getattr(self.config_mgr, "status_note", "")
        title = ("⚠ 配置已自动恢复" if status == "recovered"
                 else "⚠ 配置已重置")
        tip = ("备份文件可以在程序目录下找到（config.json.bak）；"
               "损坏的原件没有删除，已改名保留。"
               if status == "recovered" else
               "建议先检查程序目录下的 config.json.corrupt-* 文件。")
        self.after(300, lambda: messagebox.showwarning(
            title, f"{note}\n\n{tip}", parent=self))

    def _set_icon(self):
        ico = os.path.join(ASSETS, "momo.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except tk.TclError:
                pass

    # ---------------- 整体骨架 ----------------
    def _build_shell(self):
        """左侧边栏 + 右侧（标题条 + 内容区）。"""
        self._build_sidebar()

        self.main = tk.Frame(self, bg=self.C["app_bg"])
        self.main.pack(side="left", fill="both", expand=True)

        topbar = tk.Frame(self.main, bg=self.C["topbar_bg"], height=TOPBAR_H)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        self.page_title = tk.Label(topbar, text="", bg=self.C["topbar_bg"],
                                   fg=self.C["text"],
                                   font=font(FS["title"], "bold"))
        self.page_title.pack(side="left", padx=SP["xl"])
        self.page_sub = tk.Label(topbar, text="", bg=self.C["topbar_bg"],
                                 fg=self.C["sidebar_muted"],
                                 font=font(FS["xs"]))
        self.page_sub.pack(side="left", padx=SP["xs"])
        hline(self.main, self.C["divider"], pady=SP["none"])

        self.content = tk.Frame(self.main, bg=self.C["app_bg"])
        self.content.pack(fill="both", expand=True)

    # ---------------- 左侧边栏 ----------------
    def _build_sidebar(self):
        c = self.C
        w = SIDEBAR_W_MINI if self.collapsed else SIDEBAR_W
        self.sidebar = tk.Frame(self, bg=c["sidebar_bg"], width=w)
        # 主区已存在时（切页/折叠重建侧栏），必须插到它前面，否则会跑到右边
        if getattr(self, "main", None) is not None:
            self.sidebar.pack(side="left", fill="y", before=self.main)
        else:
            self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._build_user_block()
        self._build_search()
        hline(self.sidebar, c["divider"], padx=SP["md"], pady=(SP["sm"], SP["sm"]))
        # 先建底部键再建导航：pack 按「打包顺序」分配空间，窗口很矮时
        # 后打包的会被挤没——以前最后才打包底部键，560×420 下「折叠/退出」
        # 被压成 2px 直接看不见。导航区是可压缩的那一个（见 _nav_metrics）。
        self._build_footer()
        self._nav_buttons()

    def _build_user_block(self):
        """顶部品牌区：墨墨头像 + 软件全名 + 版本 / 当前用户 / 已归类数。

        软件名是第一眼的品牌信息，以前侧栏只有头像和用户名，名字压根没
        露出来。现在头像在左、文字列在右：名字一行（完整显示）、版本和
        用户信息两行小字。三行文字全部走 fit_label，栏宽不够时按像素截断
        加省略号，不会出现半个字。
        """
        c = self.C
        box = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        box.pack(fill="x", padx=SP["md"], pady=(SP["lg"], SP["sm"]))
        avatar = load_image_file(os.path.join(ASSETS, "momo-open.png"),
                                 AVATAR, self._photos)
        if self.collapsed:
            # 折叠态只留头像（居中），名字和版本放不下就不硬塞
            if avatar is not None:
                tk.Label(box, image=avatar, bg=c["sidebar_bg"]).pack(expand=True)
            else:
                tk.Label(box, text="🐙", bg=c["sidebar_bg"],
                         font=font(FS["xl"])).pack(expand=True)
            return
        if avatar is not None:
            tk.Label(box, image=avatar, bg=c["sidebar_bg"]).pack(
                side="left", anchor="n", padx=(SP["none"], SP["sm"]))
        else:
            tk.Label(box, text="🐙", bg=c["sidebar_bg"],
                     font=font(FS["xl"])).pack(side="left", anchor="n")

        texts = tk.Frame(box, bg=c["sidebar_bg"])
        texts.pack(side="left", fill="x", expand=True)
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "本机用户"
        done = len(self.config_mgr.data.get("assignments", {}))
        for text, color_key, size, weight in (
                (APP_TITLE, "text", FS["sm"], "bold"),
                (f"{APP_VERSION} · {user}", "sidebar_muted", FS["xs"], "normal"),
                (f"已归类 {done} 项", "sidebar_muted", FS["xs"], "normal")):
            lab = tk.Label(texts, text=text, bg=c["sidebar_bg"], fg=c[color_key],
                           font=font(size, weight), anchor="w")
            lab.pack(fill="x", expand=True)
            fit_label(lab, text, pad=TEXT_PAD)

    # ---------------- 全局搜索 ----------------
    def _build_search(self):
        """导航上方的全局搜索框：输入即过滤首页桌面项 / 分类。"""
        c = self.C
        box = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        box.pack(fill="x", padx=SP["md"], pady=(SP["sm"], SP["none"]))

        if self.collapsed:
            # 折叠态只放一个放大镜，点它会自动展开侧边栏并聚焦
            btn = tk.Frame(box, bg=c["search_bg"], height=BTN_H, cursor="hand2")
            btn.pack(fill="x")
            btn.pack_propagate(False)
            IconLabel(btn, "search", NAV_ICON, c["nav_icon"],
                          bg=c["search_bg"]).pack(
                expand=True)
            for w in (btn,):
                w.bind("<Button-1>", lambda e: self._expand_search())
            box.bind("<Button-1>", lambda e: self._expand_search())
            return

        self.search_var = tk.StringVar(value=self.query)
        entry = RoundedEntry(
            box, c, textvariable=self.search_var, height=BTN_H,
            on_clear=lambda: self._set_query(""),
            on_return=lambda e: self._open_first_result(),
            on_escape=lambda e: self._set_query(""))
        entry.pack(fill="x")
        self.search_entry = entry
        self.search_var.trace_add("write", self._on_search_changed)

    def _expand_search(self):
        if self.collapsed:
            # 用户主动展开：标记一下，免得「窗口还窄」的自动折叠立刻把它收回去
            self._search_expanded = True
            self.toggle_sidebar()
        entry = getattr(self, "search_entry", None)
        if entry is not None:
            entry.focus_set()

    def _on_search_changed(self, *_):
        """输入时实时过滤（不重新扫描桌面，避免每敲一个字都卡顿）。"""
        self._set_query(self.search_var.get())

    def _set_query(self, text: str):
        q = (text or "").strip()
        if q == self.query:
            return
        self.query = q
        page = getattr(self, "current_page", None)
        if self.current_key == "home" and page is not None:
            page.refresh(rescan=False)
        else:
            self._show_page("home")

    def _clear_search(self):
        if getattr(self, "search_var", None) is not None:
            self.search_var.set("")
        self._set_query("")

    def _open_first_result(self):
        """回车：直接打开搜索结果里的第一项。"""
        page = getattr(self, "current_page", None)
        if self.current_key != "home" or page is None:
            return
        if not getattr(page, "open_first", None):
            return
        if not page.open_first():
            messagebox.showinfo("搜索", "没有找到匹配的项目～", parent=self)

    def _nav_buttons(self):
        """中部导航菜单（单独一个容器，切页时只重建这里）。

        expand=True 不是为了占满，而是让这个框「吃掉剩余高度」——
        于是 winfo_height() 就是实际能分给导航的空间，窗口变矮时
        _nav_metrics() 靠它把行高压紧，而不是让底部的键被挤没。
        """
        c = self.C
        self._nav_frame = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        self._nav_frame.pack(fill="both", expand=True, pady=SP["xs"])
        # 绑在自己的 Configure 上：这个框的高度就是「实际分到多少」，
        # 比在窗口 Configure 里量可靠（那时子控件还没重新布局，量到的是旧值）
        self._nav_frame.bind("<Configure>", lambda e: self._relayout_nav_if_needed())
        self._nav_density = None
        self._render_nav_items()

    # ---- 矮窗口下的导航密度 ----
    def _nav_metrics(self):
        """(行高, 上下间距)：够高就用 NAV_H，不够就按比例压紧。

        压到 NAV_H_MIN 还不够时不再裁掉后面的项——那比行矮更糟——而是
        继续把行高压到「均分能拿到的值」，6 个导航项永远都看得见。
        """
        avail = self._nav_frame.winfo_height()
        if avail <= 1:
            return NAV_H, SP["xs"]          # 还没布局出来，先用标准值
        per = avail / float(len(NAV_ITEMS))
        pad = int(min(SP["xs"], max(0, (per - NAV_H) / 2.0)))
        cap = per - 2 * pad
        h = int(max(min(NAV_H_MIN, cap), min(NAV_H, cap)))
        return h, pad

    def _relayout_nav_if_needed(self):
        """窗口高度变了就重排导航（只在档位真变了时才重建，避免抖动）。"""
        if getattr(self, "_nav_frame", None) is None:
            return
        m = self._nav_metrics()
        if m == self._nav_density:
            return
        self._nav_density = m
        self._render_nav_items()

    def _render_nav_items(self):
        """画出导航条目（切页时只重画这几条，搜索框和用户区不受影响）。"""
        for w in self._nav_frame.winfo_children():
            w.destroy()
        for key, icon, label in NAV_ITEMS:
            self._nav_item(self._nav_frame, key, icon, label)

    def _nav_item(self, parent, key, icon, label):
        """一条导航：线性图标 + 文字，选中项左侧有强调色竖条。"""
        c = self.C
        active = (key == self.current_key)
        bg = c["sidebar_active"] if active else c["sidebar_bg"]
        fg = c["accent"] if active else c["text"]
        icon_fg = c["accent"] if active else c["nav_icon"]
        h, pad = self._nav_metrics()

        item = tk.Frame(parent, bg=bg, cursor="hand2")
        item.pack(fill="x", padx=SP["sm"], pady=pad)
        inner = tk.Frame(item, bg=bg, height=h)
        inner.pack(fill="x")
        inner.pack_propagate(False)

        if active and not self.collapsed:
            tk.Frame(inner, bg=c["accent"], width=3).pack(
                side="left", fill="y", padx=(SP["none"], SP["sm"]))
        ic = IconLabel(inner, icon, min(NAV_ICON, max(px(14), h - px(8))), icon_fg,
                       bg=bg)
        if self.collapsed:
            ic.place(relx=0.5, rely=0.5, anchor="center")
            targets = [item, inner, ic]
        else:
            ic.pack(side="left", padx=NAV_PAD)
            lab = tk.Label(inner, text=label, bg=bg, fg=fg, anchor="w",
                           font=font(FS["sm"], "bold" if active else "normal"))
            # expand=True 让文字吃掉整条剩余宽度：这样它的可用宽度是固定的
            # （不随文字长短变化），fit_label 才有稳定的基准去判断放不放得下
            lab.pack(side="left", fill="x", expand=True,
                     padx=(SP["none"], TEXT_PAD))
            fit_label(lab, label, pad=TEXT_PAD)
            targets = [item, inner, ic, lab]

        hover_bg = c["sidebar_active"] if active else c["sidebar_hover"]
        enter, leave = self._hover_group(targets, bg, hover_bg)
        for w in targets:
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", lambda e, k=key: self._show_page(k))
        return item

    @staticmethod
    def _hover_group(widgets, normal_bg, hover_bg):
        """侧边栏菜单项的 hover：整条（含图标 / 文字）一起换底色。"""
        def paint(color):
            for w in widgets:
                try:
                    w.configure(bg=color)
                except tk.TclError:
                    pass

        def enter(e=None):
            paint(hover_bg)

        def leave(e=None):
            paint(normal_bg)
        return enter, leave

    def _build_footer(self):
        """左下角功能键：折叠侧边栏 / 退出（同样是统一线性图标）。"""
        c = self.C
        foot = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        foot.pack(side="bottom", fill="x", pady=SP["sm"])
        hline(foot, c["divider"], padx=SP["md"], pady=(SP["none"], SP["sm"]))
        for icon, label, cmd in (
                ("collapse", "折叠侧边栏" if not self.collapsed else "展开侧边栏",
                 self.toggle_sidebar),
                ("power", "退出", self._quit)):
            item = tk.Frame(foot, bg=c["sidebar_bg"], cursor="hand2")
            item.pack(fill="x", padx=SP["sm"], pady=SP["xs"])
            inner = tk.Frame(item, bg=c["sidebar_bg"], height=NAV_H_SM)
            inner.pack(fill="x")
            inner.pack_propagate(False)
            ic = IconLabel(inner, icon, NAV_ICON_SM, c["nav_icon"],
                            bg=c["sidebar_bg"])
            if self.collapsed:
                ic.place(relx=0.5, rely=0.5, anchor="center")
                targets = [item, inner, ic]
            else:
                ic.pack(side="left", padx=NAV_PAD)
                lab = tk.Label(inner, text=label, bg=c["sidebar_bg"],
                               fg=c["sidebar_muted"], anchor="w",
                               font=font(FS["sm"]))
                lab.pack(side="left", fill="x", expand=True,
                         padx=(SP["none"], TEXT_PAD))
                fit_label(lab, label, pad=TEXT_PAD)
                targets = [item, inner, ic, lab]
            enter, leave = self._hover_group(targets, c["sidebar_bg"],
                                             c["sidebar_hover"])
            normal_fg = c["nav_icon"]
            for w in targets:
                w.bind("<Enter>", enter)
                w.bind("<Leave>", leave)
                w.bind("<Button-1>", lambda e, f=cmd: f())
            ic.bind("<Enter>", lambda e, i=ic: i.set_color(c["text"]))
            ic.bind("<Leave>", lambda e, i=ic: i.set_color(normal_fg))

    # ---------------- 页面路由 ----------------
    def _show_page(self, key: str, force: bool = False):
        """切换右侧主内容区显示的页面。

        页面实例会被缓存：切走时只是 pack_forget（不再销毁重建），
        切回来时再 pack 出来。好处是
          · 不会每次点导航都重扫一遍桌面、重建搜索框（丢了输入焦点）；
          · 视觉上也不闪。
        force=True 时强制重建（比如刚改完分类、需要彻底刷新的场合）。
        """
        if key not in PAGE_BY_KEY:
            key = "home"
        self.current_key = key
        page_cls = PAGE_BY_KEY[key]

        pages = getattr(self, "_pages", None)
        if pages is None:
            pages = self._pages = {}
        page = pages.get(key)
        if page is not None and force:
            hide = getattr(page, "on_hide", None)      # 先停掉它的定时器等副作用
            if hide is not None:
                try:
                    hide()
                except Exception:
                    pass
            try:
                page.destroy()
            except tk.TclError:
                pass
            pages.pop(key, None)
            page = None
        if page is None:
            page = page_cls(self.content, self)
            pages[key] = page

        for k, p in pages.items():
            if p is page:
                continue
            try:
                p.pack_forget()
            except tk.TclError:
                continue
            hide = getattr(p, "on_hide", None)
            if hide is not None:
                try:
                    hide()          # 页面有后台任务时可在这里停掉（通用钩子）
                except tk.TclError:
                    pass
        page.pack(fill="both", expand=True)
        self.current_page = page
        self.page_title.config(text=page_cls.title)
        self.page_sub.config(text=page_cls.subtitle)

        # 侧边栏只更新高亮（不再整体销毁重建，搜索框焦点得以保留）
        if getattr(self, "_nav_frame", None) is not None:
            try:
                self._render_nav_items()
            except tk.TclError:
                pass

        show = getattr(page, "on_show", None)
        if show is not None:
            show()
        elif hasattr(page, "refresh"):
            page.refresh()

    def update_topbar(self, text: str):
        """页面把自己的状态写回顶部标题条（如项目数量）。"""
        if getattr(self, "page_sub", None) is not None:
            self.page_sub.config(text=text)
            self._update_topbar_density()

    def refresh_current_page(self):
        page = getattr(self, "current_page", None)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def toggle_sidebar(self, persist=True):
        """折叠 / 展开侧边栏。

        persist=False 用于「窗口太窄自动收起」这种临时动作——不写进配置，
        免得用户只是缩了一下窗口，下次启动侧边栏就一直是折叠的。
        """
        self.collapsed = not self.collapsed
        if persist:
            self.config_mgr.set_setting("sidebar_collapsed", self.collapsed)
            self._auto_collapsed = False
        self.sidebar.destroy()
        self._build_sidebar()

    # ---------------- 主题 ----------------
    def _apply_theme(self, name: str):
        """切换主题：更新配色、保存配置、重建整个界面。"""
        if name not in THEMES:
            name = DEFAULT_THEME
        self.theme_name = name
        self.C = get_theme(name)
        self.config_mgr.set_setting("theme", name)
        self.configure(bg=self.C["app_bg"])
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                w.destroy()
        self.sidebar = None
        self.main = None
        self.content = None
        self._pages = {}        # 换主题等于整套重建，缓存的页面一并作废
        self._photos = []
        self._build_shell()
        self._show_page(self.current_key)

    # ---------------- 桌面宠物 ----------------
    def pet_active(self) -> bool:
        return getattr(self, "_pet", None) is not None

    def _toggle_pet(self):
        """召唤 / 收起桌面上独立悬浮的墨墨。"""
        if self.pet_active():
            try:
                self._pet.on_close()
            except Exception:
                pass
            return
        from gui.pet import DesktopPet
        self._pet = DesktopPet(self)

    def _on_pet_closed(self):
        """桌宠被收起时的回调：同步设置页按钮状态。"""
        self._pet = None
        if self.current_key == "settings":
            self._show_page("settings", force=True)   # 按钮文字要重算

    # ---------------- 番茄钟 ----------------
    POMO_MIN, POMO_MAX = 1, 600        # 允许自定义的范围（分钟）

    @property
    def pomo_minutes(self) -> int:
        """用户设置的专注时长（分钟）。"""
        try:
            v = int(self.cfg.get_setting("pomodoro_minutes", 45))
        except (TypeError, ValueError):
            v = 45
        return max(self.POMO_MIN, min(self.POMO_MAX, v))

    @property
    def pomo_break(self) -> int:
        """用户设置的休息时长（分钟）。"""
        try:
            v = int(self.cfg.get_setting("pomodoro_break", 5))
        except (TypeError, ValueError):
            v = 5
        return max(self.POMO_MIN, min(self.POMO_MAX, v))

    def set_pomo_minutes(self, minutes, break_minutes=None):
        """把用户自定义的番茄钟时长写入配置。"""
        self.cfg.set_setting("pomodoro_minutes", self.pomo_minutes
                             if minutes is None else
                             max(self.POMO_MIN, min(self.POMO_MAX, int(minutes))))
        if break_minutes is not None:
            self.cfg.set_setting("pomodoro_break", self.pomo_break
                                 if break_minutes is None else
                                 max(self.POMO_MIN,
                                     min(self.POMO_MAX, int(break_minutes))))
        return self.pomo_minutes

    def start_pomodoro(self, minutes=None, break_minutes=None):
        """开启番茄钟：桌宠进入伴学状态，头顶显示倒计时。

        minutes 为 None 时使用用户设置好的默认时长。
        """
        import time as _t
        mins = self.pomo_minutes if minutes is None else int(minutes)
        mins = max(self.POMO_MIN, min(self.POMO_MAX, mins))
        rest = self.pomo_break if break_minutes is None else int(break_minutes)
        rest = max(self.POMO_MIN, min(self.POMO_MAX, rest))
        self.pomodoro = {"end": _t.time() + mins * 60,
                         "minutes": mins, "break": rest}
        if self._pomo_job:
            try:
                self.after_cancel(self._pomo_job)
            except Exception:
                pass
        self._pomo_job = self.after(mins * 60 * 1000, self._pomodoro_done)

    def stop_pomodoro(self):
        """手动结束：立刻清掉桌宠头上的倒计时气泡。"""
        self.pomodoro = None
        if self._pomo_job:
            try:
                self.after_cancel(self._pomo_job)
            except Exception:
                pass
            self._pomo_job = None
        self._pet_pomodoro_end("stop")

    def _pomodoro_done(self):
        """番茄钟到点：弹窗提醒 + 桌宠气泡庆祝（之后不再显示倒计时）。"""
        self._pomo_job = None
        info = self.pomodoro or {}
        mins = info.get("minutes", self.pomo_minutes)
        rest = info.get("break", self.pomo_break)
        self.pomodoro = None
        self._pet_pomodoro_end("done", mins, rest)
        self.refresh_pomodoro_ui()
        messagebox.showinfo(
            "🍅 番茄钟结束",
            f"专注 {mins} 分钟完成！\n\n站起来活动一下，休息 {rest} 分钟吧～",
            parent=self)

    def _pet_pomodoro_end(self, kind, minutes=0, break_minutes=0):
        kind = "done" if kind == "done" else "stop"
        if kind == "done":
            self.pomodoro = None
        pet = getattr(self, "_pet", None)
        if pet is None:
            return
        try:
            pet.on_pomodoro_end(kind, minutes, break_minutes)
        except Exception:
            pass

    def refresh_pomodoro_ui(self):
        """番茄钟状态变化后，刷新可能正在显示的页面（倒计时 / 设置）。

        页面现在会被缓存，_show_page 不带 force 只是把旧实例重新 pack 出来，
        按钮文字不会重算 —— 这里必须强制重建。
        """
        if self.current_key in ("countdowns", "settings"):
            self._show_page(self.current_key, force=True)

    # ---------------- 事件 ----------------
    def _on_f5(self, event=None):
        self.refresh_current_page()

    def _on_wheel(self, event):
        """鼠标滚轮转发给当前页面的画布（首页网格）。"""
        canvas = getattr(getattr(self, "current_page", None), "canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        except tk.TclError:
            pass

    def _quit(self):
        if messagebox.askyesno("退出", f"确定要退出{APP_TITLE}吗？"):
            try:
                self.hk.unregister()
            except Exception:
                pass
            if self.pet_active():
                try:
                    self._pet.on_close()
                except Exception:
                    pass
            self._save_geometry()
            self.destroy()
