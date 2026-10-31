# -*- coding: utf-8 -*-
"""主框架（Shell）：左侧边栏导航 + 右侧主内容区。

布局约定：
    左侧边栏  ── 顶部：用户头像 / 当前用户
              ── 中部：导航菜单（首页 / 分类 / 统计 / 设置）
              ── 底部：折叠侧边栏、退出
    右侧主区  ── 顶部标题条 + 下方内容区（点击左侧菜单切换页面）

具体页面在 gui/pages.py 里实现，这里只负责路由与全局能力
（主题、桌宠、窗口居中）。
"""
import os
import tkinter as tk
from tkinter import messagebox

from core.config import ConfigManager
from core.icons import icon_png  # noqa: F401（保持与旧引用兼容）
from gui.theme import DEFAULT_THEME, THEMES, THEME_NAMES, get_theme
from gui.pages import PAGE_BY_KEY, DesktopPage
from gui.widgets import center_window, load_image_file, hline

APP_TITLE = "墨墨桌面管理助手"
SIDEBAR_W = 208      # 展开宽度
SIDEBAR_W_MINI = 64  # 折叠后宽度
WIN_W, WIN_H = 1120, 700

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets")

# 导航菜单：(页面 key, 图标, 名称)
NAV_ITEMS = (
    ("home", "🏠", "首页"),
    ("categories", "🗂", "分类管理"),
    ("stats", "📊", "数据统计"),
    ("system", "📈", "系统监控"),
    ("settings", "⚙", "设置"),
)


class App(tk.Tk):
    """主窗口：侧边栏 + 内容区。"""

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.config_mgr = ConfigManager()
        self.theme_name = self.config_mgr.get_setting("theme", DEFAULT_THEME)
        self.C = get_theme(self.theme_name)
        self.collapsed = bool(self.config_mgr.get_setting("sidebar_collapsed", False))
        self._pet = None            # 桌面悬浮宠物（None = 未召唤）
        self.current_key = "home"
        self.current_page = None
        self._photos = []           # 头像等图片引用，防止被回收

        self.configure(bg=self.C["app_bg"])
        self._set_icon()
        self.minsize(900, 560)
        center_window(self, WIN_W, WIN_H)

        self._build_shell()
        self._show_page("home")

        self.bind("<F5>", self._on_f5)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.protocol("WM_DELETE_WINDOW", self._quit)

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

        topbar = tk.Frame(self.main, bg=self.C["topbar_bg"], height=56)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        self.page_title = tk.Label(topbar, text="", bg=self.C["topbar_bg"],
                                   fg=self.C["text"],
                                   font=("Microsoft YaHei", 14, "bold"))
        self.page_title.pack(side="left", padx=20)
        self.page_sub = tk.Label(topbar, text="", bg=self.C["topbar_bg"],
                                 fg=self.C["sidebar_muted"],
                                 font=("Microsoft YaHei", 9))
        self.page_sub.pack(side="left", padx=4)
        hline(self.main, self.C["divider"], pady=0)

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
        hline(self.sidebar, c["divider"], padx=12, pady=(4, 8))
        self._nav_buttons()
        self._build_footer()

    def _build_user_block(self):
        """顶部用户信息：墨墨头像 + 当前用户名。"""
        c = self.C
        box = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        box.pack(fill="x", padx=10, pady=(14, 6))
        avatar = load_image_file(os.path.join(ASSETS, "momo-open.png"),
                                 44, self._photos)
        if avatar is not None:
            tk.Label(box, image=avatar, bg=c["sidebar_bg"]).pack(
                anchor="w" if not self.collapsed else "center")
        else:
            tk.Label(box, text="🐙", bg=c["sidebar_bg"],
                     font=("Microsoft YaHei", 22)).pack()
        if not self.collapsed:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or "本机用户"
            tk.Label(box, text=user, bg=c["sidebar_bg"], fg=c["text"],
                     font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
                fill="x", pady=(6, 0))
            done = len(self.config_mgr.data.get("assignments", {}))
            tk.Label(box, text=f"已归类 {done} 项", bg=c["sidebar_bg"],
                     fg=c["sidebar_muted"], font=("Microsoft YaHei", 8),
                     anchor="w").pack(fill="x")

    def _nav_buttons(self):
        """中部导航菜单。"""
        c = self.C
        nav = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        nav.pack(fill="x", pady=4)
        for key, icon, label in NAV_ITEMS:
            self._nav_item(nav, key, icon, label)

    def _nav_item(self, parent, key, icon, label):
        c = self.C
        active = (key == self.current_key)
        text = icon if self.collapsed else f"{icon}   {label}"
        btn = tk.Button(parent, text=text,
                        anchor="center" if self.collapsed else "w",
                        font=("Microsoft YaHei", 11, "bold" if active else "normal"),
                        bg=c["sidebar_active"] if active else c["sidebar_bg"],
                        fg=c["accent"] if active else c["text"],
                        activebackground=c["sidebar_hover"],
                        activeforeground=c["accent"],
                        relief="flat", bd=0, padx=10, pady=9,
                        command=lambda k=key: self._show_page(k))
        btn.pack(fill="x", padx=8, pady=2)
        return btn

    def _build_footer(self):
        """左下角功能键：折叠侧边栏 / 退出。"""
        c = self.C
        foot = tk.Frame(self.sidebar, bg=c["sidebar_bg"])
        foot.pack(side="bottom", fill="x", pady=8)
        hline(foot, c["divider"], padx=12, pady=(0, 6))
        for icon, label, cmd in (
                ("⇔", "折叠侧边栏" if not self.collapsed else "展开侧边栏",
                 self.toggle_sidebar),
                ("⏻", "退出", self._quit)):
            text = icon if self.collapsed else f"{icon}   {label}"
            tk.Button(foot, text=text,
                      anchor="center" if self.collapsed else "w",
                      font=("Microsoft YaHei", 10),
                      bg=c["sidebar_bg"], fg=c["sidebar_muted"],
                      activebackground=c["sidebar_hover"],
                      activeforeground=c["text"],
                      relief="flat", bd=0, padx=10, pady=7,
                      command=cmd).pack(fill="x", padx=8, pady=2)

    # ---------------- 页面路由 ----------------
    def _show_page(self, key: str):
        """切换右侧主内容区显示的页面。"""
        if key not in PAGE_BY_KEY:
            key = "home"
        self.current_key = key
        page_cls = PAGE_BY_KEY[key]

        # 侧边栏高亮跟随切换
        self.sidebar.destroy()
        self._build_sidebar()

        for w in self.content.winfo_children():
            w.destroy()
        page = page_cls(self.content, self)
        page.pack(fill="both", expand=True)
        self.current_page = page
        self.page_title.config(text=page_cls.title)
        self.page_sub.config(text=page_cls.subtitle)

    def update_topbar(self, text: str):
        """页面把自己的状态写回顶部标题条（如项目数量）。"""
        if getattr(self, "page_sub", None) is not None:
            self.page_sub.config(text=text)

    def refresh_current_page(self):
        page = getattr(self, "current_page", None)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def toggle_sidebar(self):
        """折叠 / 展开侧边栏（状态写入 config.json）。"""
        self.collapsed = not self.collapsed
        self.config_mgr.set_setting("sidebar_collapsed", self.collapsed)
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
            self._show_page("settings")

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
            if self.pet_active():
                try:
                    self._pet.on_close()
                except Exception:
                    pass
            self.destroy()
