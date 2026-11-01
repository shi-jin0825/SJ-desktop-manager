# -*- coding: utf-8 -*-
"""core 层纯逻辑单测（不需要窗口、不需要 Windows API）。

运行：
    python -m unittest discover -s tests -v
或
    python tests/test_core.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import countdown as cd
from core.config import ConfigManager, item_key


class CountdownTest(unittest.TestCase):
    def test_parse_date_ok(self):
        self.assertEqual(cd.parse_date("2026-12-20"), dt.date(2026, 12, 20))
        self.assertEqual(cd.parse_date("2026/12/20"), dt.date(2026, 12, 20))
        self.assertEqual(cd.parse_date("2026年12月20日"), dt.date(2026, 12, 20))
        self.assertIsInstance(cd.parse_date(dt.date(2026, 1, 1)), dt.date)

    def test_parse_date_bad(self):
        for bad in ("", None, "不是日期", "2026-13-01", "2026-2-30", "2026"):
            self.assertIsNone(cd.parse_date(bad), bad)

    def test_days_until(self):
        ref = dt.date(2026, 1, 1)
        self.assertEqual(cd.days_until(dt.date(2026, 1, 11), ref), 10)
        self.assertEqual(cd.days_until(dt.date(2026, 1, 1), ref), 0)
        self.assertEqual(cd.days_until(dt.date(2025, 12, 25), ref), -7)

    def test_repeat_rolls_to_next_year(self):
        ref = dt.date(2026, 6, 1)
        # 今年已过（3-05）→ 顺延到明年
        self.assertEqual(cd.next_target(dt.date(2020, 3, 5), ref, True),
                         dt.date(2027, 3, 5))
        # 今年还没到（12-20）→ 今年
        self.assertEqual(cd.next_target(dt.date(2020, 12, 20), ref, True),
                         dt.date(2026, 12, 20))

    def test_repeat_leap_day_falls_back_to_28(self):
        ref = dt.date(2027, 1, 1)          # 2027 是平年
        self.assertEqual(cd.next_target(dt.date(2000, 2, 29), ref, True),
                         dt.date(2027, 2, 28))

    def test_no_repeat_keeps_original(self):
        target = dt.date(2020, 1, 1)
        self.assertEqual(cd.next_target(target, dt.date(2026, 1, 1), False),
                         target)

    def test_progress_bounds(self):
        ref = dt.date(2026, 1, 1)
        item = {"date": "2026-01-11", "created": "2025-12-22", "repeat": False}
        p = cd.progress(item, ref)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)
        # 区间异常时不画进度条
        self.assertIsNone(cd.progress({"date": "2025-01-01",
                                       "created": "2026-01-01"}, ref))

    def test_describe_and_sort_key(self):
        ref = dt.date(2026, 1, 1)
        near = {"id": "a", "date": "2026-01-05", "note": "", "repeat": False}
        past = {"id": "b", "date": "2020-01-05", "note": "", "repeat": False}
        d = cd.describe(near, ref)
        self.assertIn("days", d)
        # 没到的排在前面，过去的垫底
        self.assertLess(cd.sort_key(near, ref), cd.sort_key(past, ref))


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_created(self):
        cm = ConfigManager(self.path)
        self.assertEqual(cm.categories, ["工具", "办公", "娱乐"])
        self.assertEqual(cm.countdowns, [])

    def test_atomic_write_creates_backup(self):
        cm = ConfigManager(self.path)
        cm.add_category("游戏")
        self.assertTrue(os.path.isfile(self.path))
        # 再写一次 → 上一份留成 .bak
        cm.add_category("学习")
        self.assertTrue(os.path.isfile(self.path + ".bak"))
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertIn("游戏", f.read())
        # 不留临时文件
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_corrupt_file_recovers_from_backup(self):
        cm = ConfigManager(self.path)
        cm.add_category("重要分类")
        cm.add_category("第二分类")        # 触发一次备份
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 写坏了的 json")     # 模拟断电 / 崩溃
        cm2 = ConfigManager(self.path)
        self.assertEqual(cm2.load_status, "recovered")
        self.assertIn("重要分类", cm2.categories)
        self.assertTrue(any("corrupt-" in n for n in os.listdir(self.tmp)))

    def test_corrupt_without_backup_resets(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json at all")
        cm = ConfigManager(self.path)
        self.assertEqual(cm.load_status, "reset")
        self.assertEqual(cm.categories, ["工具", "办公", "娱乐"])

    def test_assignment_key_is_path(self):
        cm = ConfigManager(self.path)
        cm.assign(r"C:\Users\me\Desktop\a.txt", "工具")
        self.assertEqual(cm.get_category(r"C:\users\me\desktop\a.txt"), "工具")
        # 大小写 / 斜杠不同也应命中同一条
        self.assertEqual(cm.get_category(r"C:/Users/ME/Desktop/a.txt"), "工具")

    def test_legacy_name_key_migrates(self):
        cm = ConfigManager(self.path)
        cm.data["assignments"]["a.txt"] = "办公"      # 老版本存的是文件名
        cm.save()

        class Item(object):
            path = r"C:\Users\me\Desktop\a.txt"
            name = "a.txt"

        self.assertEqual(cm.migrate_assignments([Item()]), 1)
        self.assertEqual(cm.get_category(Item.path), "办公")
        self.assertNotIn("a.txt", cm.data["assignments"])

    def test_prune_dead_assignments(self):
        cm = ConfigManager(self.path)
        cm.assign(r"C:\Users\me\Desktop\a.txt", "工具")
        cm.assign(r"C:\Users\me\Desktop\已删掉.txt", "工具")
        self.assertEqual(cm.prune_assignments([r"C:\Users\me\Desktop\a.txt"]), 1)
        self.assertEqual(len(cm.data["assignments"]), 1)

    def test_batch_assign_and_undo_snapshot(self):
        cm = ConfigManager(self.path)
        paths = [r"C:\a.txt", r"C:\b.txt", r"C:\c.txt"]
        self.assertEqual(cm.assign_batch(paths, "工具"), 3)
        for p in paths:
            self.assertEqual(cm.get_category(p), "工具")
        self.assertEqual(cm.unassign_batch(paths), 3)
        for p in paths:
            self.assertEqual(cm.get_category(p), "")

    def test_rename_category_keeps_assignments(self):
        cm = ConfigManager(self.path)
        cm.assign(r"C:\a.txt", "工具")
        self.assertTrue(cm.rename_category("工具", "效率"))
        self.assertEqual(cm.get_category(r"C:\a.txt"), "效率")

    def test_remove_category_frees_items(self):
        cm = ConfigManager(self.path)
        cm.assign(r"C:\a.txt", "工具")
        cm.remove_category("工具")
        self.assertEqual(cm.get_category(r"C:\a.txt"), "")

    def test_item_key_normalized(self):
        self.assertEqual(item_key(r"C:\A\b.TXT"), item_key("c:/a/B.txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
