# -*- coding: utf-8 -*-
"""分类 CRUD 的公共层。

「新建 / 重命名 / 删除分类」这套交互原先在首页工具栏、首页的分类管理器
弹窗、分类页里各写了一遍（三份 40 行上下的复制粘贴），提示文案、判空逻辑
稍有出入就会表现不一致。这里收敛成三个函数，调用方只负责拿到结果后刷新。

约定：
    * 返回 None / False 表示「什么都没发生」（用户取消，或名称非法且已提示）；
    * 返回新名字 / True 表示配置已改动，调用方刷新界面。
"""
from tkinter import messagebox, simpledialog

INVALID_TIP = "分类名称为空或已存在"


def create_category(cfg, parent):
    """弹窗问一个新分类名并创建；返回新分类名，取消或重名返回 None。"""
    name = simpledialog.askstring("新建分类", "分类名称：", parent=parent)
    if name is None:
        return None
    if not cfg.add_category(name):
        messagebox.showwarning("提示", INVALID_TIP, parent=parent)
        return None
    return name.strip()


def rename_category(cfg, old, parent):
    """弹窗重命名分类（同步改归属）；返回新名字，取消或重名返回 None。"""
    new = simpledialog.askstring("重命名分类", "新的分类名称：",
                                 initialvalue=old, parent=parent)
    if new is None:
        return None
    if not cfg.rename_category(old, new):
        # 改成和原来一样的名字不算错误，只是不用提示
        if (new or "").strip() != old:
            messagebox.showwarning("提示", INVALID_TIP, parent=parent)
        return None
    return new.strip()


def delete_category(cfg, name, parent):
    """二次确认后删除分类；确认并执行返回 True，否则 False。"""
    if not messagebox.askyesno(
            "删除分类",
            f"删除分类「{name}」？\n其中的项目将回到未分类状态。",
            parent=parent):
        return False
    cfg.remove_category(name)
    return True
