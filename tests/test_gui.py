# -*- coding: utf-8 -*-
"""gui 层里不需要人眼就能验证的部分（字体解析 / 胶囊按钮像素）。

会临时建一个隐藏的 Tk 根窗口 —— tkinter 的字体表必须有根窗口才能查。
运行：python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk          # noqa: E402
except ImportError:               # 精简版 Python / 无 GUI 的 CI 环境
    tk = None

_ROOT = None


def _root():
    """全局共用一个隐藏根窗口（建多个 Tk 实例在部分环境下会崩）。"""
    global _ROOT
    if _ROOT is None:
        _ROOT = tk.Tk()
        _ROOT.withdraw()
    return _ROOT

require_tk = unittest.skipIf(tk is None, "当前 Python 没有 tkinter，跳过 GUI 用例")


@require_tk
class FontTest(unittest.TestCase):
    def test_family_resolves_to_something_installed(self):
        from tkinter import font as tkfont
        from gui import fonts
        _root()
        fam = fonts.family()
        self.assertTrue(fam)
        available = set(tkfont.families(_root()))
        self.assertTrue(fam in available or fam == fonts.FALLBACK,
                        "%s 不在系统字体表里" % fam)

    def test_font_tuple_shape(self):
        from gui import fonts
        _root()
        fam = fonts.family()
        self.assertEqual(fonts.font(9), (fam, 9))
        self.assertEqual(fonts.font(11, "bold"), (fam, 11, "bold"))

    def test_size_is_int(self):
        from gui import fonts
        _root()
        self.assertIsInstance(fonts.font(10.0)[1], int)


@require_tk
class CapsuleButtonTest(unittest.TestCase):
    """胶囊按钮：两端圆形不能有"轮廓框"（曾经用 create_oval 描边导致）。"""

    def test_no_oval_items_on_canvas(self):
        from gui.widgets import ModernButton
        from gui.theme import get_theme
        root = _root()
        btn = ModernButton(root, text="新建分类", c=get_theme("light"),
                           primary=True, icon="folder")
        btn.update_idletasks()
        kinds = set()
        for item in btn.find_all():
            kinds.add(btn.type(item))
        self.assertIn("image", kinds)          # 胶囊位图
        self.assertNotIn("oval", kinds)        # 圆不能再是独立的椭圆图元
        btn.destroy()


if __name__ == "__main__":
    unittest.main()
