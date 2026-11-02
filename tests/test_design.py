# -*- coding: utf-8 -*-
"""设计令牌守护测试：防止间距 / 字号又散落成孤值。

v1.7 之前间距 177 处用了 18 个值、字号 93 处用了 13 个值，统一到
gui/tokens.py 之后，用文件扫描锁住「页面代码里不许再写裸数字」。
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.tokens import BAR_H, FS, SP          # noqa: E402
from gui.pages import TILE_SIZE, TILE_PRESETS, tile_scale  # noqa: E402

GUI_FILES = ["gui/pages.py", "gui/app.py", "gui/widgets.py", "gui/pet.py"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()


class TokenTest(unittest.TestCase):
    def test_spacing_only_via_tokens(self):
        """padx/pady 不许再写裸数字（SP 字典本身除外）。"""
        pat = re.compile(r"\b(?:ipad[xy]|pad[xy])=(-?\d+)\b")
        bad = []
        for p in GUI_FILES:
            for m in pat.finditer(read(p)):
                # tokens.py 的定义文件不在扫描范围，命中即违规
                bad.append((p, m.group(0)))
        self.assertEqual(bad, [])

    def test_font_sizes_only_via_tokens(self):
        """font() / fonts.font() 的第一个参数不许是裸数字。"""
        pat = re.compile(r"(?<![\w.])\bfonts?\.font\((\d+)")
        bad = [(p, m.group(0)) for p in GUI_FILES
               for m in pat.finditer(read(p))]
        self.assertEqual(bad, [])

    def test_scales_are_finite(self):
        self.assertLessEqual(len(SP), 8)
        self.assertLessEqual(len(FS), 8)
        self.assertEqual(BAR_H, 10)
        self.assertGreaterEqual(min(FS.values()), 10)   # 可读下限


class TileScaleTest(unittest.TestCase):
    def test_monotonic_and_bounded(self):
        prev = 0.0
        for w in range(300, 3400, 25):
            s = tile_scale(w)
            self.assertGreaterEqual(s, prev, w)
            self.assertGreaterEqual(s, 0.72)
            self.assertLessEqual(s, 1.75)
            prev = s

    def test_presets_are_multiples(self):
        """手动档位应是基准的倍数，不再是孤值。"""
        for name, v in TILE_PRESETS.items():
            ratio = v / float(TILE_SIZE)
            # 允许 1/8 步进的倍数（0.875 = 7/8 也算「基准的倍数」）
            self.assertAlmostEqual(ratio * 8, round(ratio * 8),
                                   places=2, msg=name)
            self.assertTrue(0.7 <= ratio <= 1.5, name)

    def test_category_card_follows_same_curve(self):
        """分类卡片和首页磁贴共用 tile_scale：卡片不该比磁贴还大。"""
        from gui.pages import CAT_TILE_W, CategoryWindow
        for w in (400, 560, 800, 1100, 1600, 2400):
            _, card = CategoryWindow._plan(w - 300)      # 分类窗口通常比主窗口小
            tile = int(round(TILE_SIZE * tile_scale(w)))
            self.assertLessEqual(card, tile, w)


if __name__ == "__main__":
    unittest.main()
