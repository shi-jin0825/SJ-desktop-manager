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
_NO_DISPLAY = False


def _probe_display():
    """探测能否真正创建 Tk 根窗口（ubuntu CI 装了 tkinter 但无 DISPLAY）。"""
    if tk is None:
        return False
    try:
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True
    except tk.TclError:
        return False


_NO_DISPLAY = not _probe_display()


def _root():
    """全局共用一个隐藏根窗口（建多个 Tk 实例在部分环境下会崩）。"""
    global _ROOT
    if _ROOT is None:
        _ROOT = tk.Tk()
        _ROOT.withdraw()
    return _ROOT

require_tk = unittest.skipIf(
    tk is None or _NO_DISPLAY,
    "当前环境无可用显示（缺 tkinter 或 headless CI），跳过 GUI 用例")


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


@require_tk
class TileScaleTest(unittest.TestCase):
    """首页磁贴随窗口放大：尺寸单调变大、列数合理、不超出网格宽度。

    只用到 _plan 这个纯计算，不需要真的建窗口。
    """

    @staticmethod
    def _plan(width, preset=None):
        from gui.pages import DesktopPage

        class _Cfg(object):
            def __init__(self, p):
                self.p = p

            def get_setting(self, key, default=None):
                return self.p if key == "tile_size" else default

        class _Page(object):
            cfg = _Cfg(preset)
            cols = 8
            tile_w = 96

        return DesktopPage._plan(_Page, width)

    def test_tile_grows_with_window(self):
        small = self._plan(640)
        big = self._plan(1280)
        self.assertGreater(big[1], small[1] + 20,
                           "窗口宽度翻倍，磁贴应该明显变大")
        self.assertGreaterEqual(self._plan(1920)[1], big[1])

    def test_monotonic_no_shrink(self):
        """拖动窗口时磁贴不该出现「拉宽反而变小」的回落。"""
        prev = 0
        for w in range(500, 2600, 10):
            _, tile = self._plan(w)
            self.assertGreaterEqual(tile, prev,
                                    "宽度 %d 时磁贴从 %d 缩到 %d" % (w, prev, tile))
            prev = tile

    def test_row_fits_grid(self):
        for w in range(500, 3000, 25):
            cols, tile = self._plan(w)
            self.assertLessEqual(cols * (tile + 20), w + 8,
                                 "宽度 %d 下 %d 列 × %dpx 放不下" % (w, cols, tile))
            self.assertTrue(4 <= cols <= 16)

    def test_preset_is_fixed(self):
        """手动档位：尺寸定死，只按宽度加减列数。"""
        self.assertEqual(self._plan(640, "small")[1], 84)
        self.assertEqual(self._plan(1600, "small")[1], 84)
        self.assertEqual(self._plan(640, "large")[1], 132)
        self.assertGreater(self._plan(1600, "small")[0],
                           self._plan(640, "small")[0])


if __name__ == "__main__":
    unittest.main()
