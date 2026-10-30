# -*- coding: utf-8 -*-
"""界面主题：浅色 / 深色两套配色，用户在「设置」里切换并持久化到 config.json。

新增配色项时，只要在两套主题的字典里都加上同名 key 即可。
"""

THEMES = {
    "light": {
        "app_bg": "#eef1f6",           # 主窗口 / 网格区背景
        "panel_bg": "#ffffff",         # 磁贴、按钮、列表项底色
        "panel_active": "#e5e5ea",     # 磁贴 / 按钮 hover、按下
        "text": "#333333",             # 主文字
        "text_muted": "#999999",       # 次要文字（空状态提示等）
        "folder_bg": "#dfe7f5",        # 分类文件夹磁贴底色
        "folder_bg_hover": "#c9d7ef",
        "folder_panel": "#ffffff",     # 文件夹内 3×3 预览面板
        "folder_panel_outline": "#c9d7ef",
        "placeholder": "#e5e5ea",      # 取不到图标时的占位块
        "placeholder_outline": "#d0d0d8",
        "empty_text": "#a3a3ad",       # 空分类里的"空"字
        "dialog_bg": "#f4f6fa",        # 弹窗（设置 / 分类管理器 / 分类内容）背景
        "menu_bg": "#ffffff",
        "menu_fg": "#222222",
        "menu_active": "#dfe7f5",
        "list_sel": "#c9d7ef",
        # 右侧滚动条：轨道 / 滑块 / 滑块 hover（轨道要比背景明显，否则看不见）
        "scroll_trough": "#dfe4ee",
        "scroll_thumb": "#aab3c6",
        "scroll_thumb_active": "#8d99b3",
        # ---- 左侧边栏 / 卡片 / 强调色 ----
        "sidebar_bg": "#ffffff",         # 侧边栏底色
        "sidebar_hover": "#f2f5fb",      # 菜单项 hover
        "sidebar_active": "#e8eefc",     # 当前选中的菜单项
        "sidebar_muted": "#8a93a6",      # 侧边栏次要文字（用户名下的说明）
        "accent": "#4b6bfb",             # 强调色（选中态、按钮、统计条）
        "accent_fg": "#ffffff",          # 强调色上的文字
        "divider": "#e6e9f0",            # 分隔线
        "card_bg": "#ffffff",            # 内容区卡片
        "topbar_bg": "#f7f9fc",          # 右侧顶部标题条
        "stat_bar": "#4b6bfb",           # 统计条填充
        "stat_bar_bg": "#e8eefc",        # 统计条底槽
    },
    "dark": {
        "app_bg": "#1c1f26",
        "panel_bg": "#2a2e38",
        "panel_active": "#383e4c",
        "text": "#e6e8ee",
        "text_muted": "#8b93a3",
        "folder_bg": "#2d3748",
        "folder_bg_hover": "#3a475e",
        "folder_panel": "#333a47",
        "folder_panel_outline": "#4a5568",
        "placeholder": "#3a4150",
        "placeholder_outline": "#4a5261",
        "empty_text": "#6b7480",
        "dialog_bg": "#21242c",
        "menu_bg": "#2a2e38",
        "menu_fg": "#e6e8ee",
        "menu_active": "#3a475e",
        "list_sel": "#3a475e",
        "scroll_trough": "#2b3240",
        "scroll_thumb": "#5b6478",
        "scroll_thumb_active": "#78849e",
        "sidebar_bg": "#21252d",
        "sidebar_hover": "#2a2f39",
        "sidebar_active": "#33405c",
        "sidebar_muted": "#8b93a3",
        "accent": "#6d8bff",
        "accent_fg": "#ffffff",
        "divider": "#2e343f",
        "card_bg": "#262b34",
        "topbar_bg": "#1c1f26",
        "stat_bar": "#6d8bff",
        "stat_bar_bg": "#2f3542",
    },
}

THEME_NAMES = {
    "light": "浅色模式",
    "dark": "深色模式",
}

DEFAULT_THEME = "light"


def get_theme(name: str) -> dict:
    """取主题配色；未知名字回退到浅色。"""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def style_menu(menu, c: dict) -> None:
    """给右键菜单套上主题色。"""
    menu.configure(bg=c["menu_bg"], fg=c["menu_fg"],
                   activebackground=c["menu_active"],
                   activeforeground=c["menu_fg"],
                   relief="flat", bd=1)
