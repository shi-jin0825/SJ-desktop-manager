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


class PlanTest(unittest.TestCase):
    """日程计划（时间管理页）的纯逻辑。"""

    def test_plan_describe_states(self):
        ref = dt.date(2026, 11, 4)
        self.assertEqual(cd.plan_describe({"date": ""}, ref)["state"], "nodate")
        self.assertEqual(cd.plan_describe({"date": "2026-11-09"}, ref)["text"],
                         "还有 5 天")
        self.assertEqual(cd.plan_describe({"date": "2026-11-04"}, ref)["text"],
                         "今天要做")
        self.assertEqual(cd.plan_describe({"date": "2026-11-01"}, ref)["text"],
                         "已过 3 天")

    def test_plan_sort_done_last(self):
        ref = dt.date(2026, 11, 4)
        overdue = {"title": "a", "date": "2026-11-01"}
        today = {"title": "b", "date": "2026-11-04"}
        future = {"title": "c", "date": "2026-11-09"}
        nodate = {"title": "d", "date": ""}
        done = {"title": "e", "date": "2026-11-01", "done": True,
                "done_at": "2026-11-04"}
        items = [done, future, nodate, today, overdue]
        order = [i["title"] for i in sorted(
            items, key=lambda i: cd.plan_sort_key(i, ref))]
        # 未完成按日期临近（逾期最先），无日期排未完成末尾，已完成垫底
        self.assertEqual(order, ["a", "b", "c", "d", "e"])


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

    @unittest.skipUnless(os.name == "nt",
                         "路径大小写与斜杠归一属 Windows 语义（normcase）")
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

    def test_category_counts_single_source(self):
        """category_counts 是分类计数的唯一事实来源：按扫描项解析分类。"""
        cm = ConfigManager(self.path)

        class Item(object):
            def __init__(self, path):
                self.path = path
                self.name = os.path.basename(path)

        items = [Item(r"C:\Desktop\a.txt"), Item(r"C:\Desktop\b.txt"),
                 Item(r"C:\Desktop\c.txt")]
        cm.assign_batch([i.path for i in items[:2]], "工具")
        cm.assign_batch([items[2].path], "娱乐")

        counts = cm.category_counts(items)
        self.assertEqual(counts, {"工具": 2, "娱乐": 1})

    def test_category_counts_ignores_unmatched_paths(self):
        """扫描项路径对不上 assignments key 时，不计入（避免虚高）。"""
        cm = ConfigManager(self.path)

        class Item(object):
            def __init__(self, path):
                self.path = path
                self.name = os.path.basename(path)

        # assignments 里有一条指向「已经不在扫描结果里」的路径
        cm.assign(r"C:\Desktop\旧路径.txt", "工具")
        items = [Item(r"C:\Desktop\现在只有这个.txt")]
        # 现在这个项没归类，旧路径对不上 → 计数应为空
        self.assertEqual(cm.category_counts(items), {})

    def test_reconcile_relinks_by_basename(self):
        """路径对不上但文件名还在：按 basename 重关联，别让归类静默归零。"""
        cm = ConfigManager(self.path)
        cm.assign(r"C:\Desktop\a.txt", "工具")   # 旧路径

        class Item(object):
            def __init__(self, path):
                self.path = path
                self.name = os.path.basename(path)

        # 文件被移动：路径变了，但 basename 仍是 a.txt
        items = [Item(r"D:\新位置\a.txt")]
        self.assertEqual(cm.reconcile_assignments(items), 1)
        self.assertEqual(cm.get_category(r"D:\新位置\a.txt"), "工具")
        self.assertEqual(cm.unresolved_count, 0)

    def test_reconcile_marks_unresolved(self):
        """连 basename 都对不上的归类：计入待重新关联，而非静默显示 0。"""
        cm = ConfigManager(self.path)
        cm.assign(r"C:\Desktop\已消失.txt", "工具")

        class Item(object):
            def __init__(self, path):
                self.path = path
                self.name = os.path.basename(path)

        items = [Item(r"C:\Desktop\别的文件.txt")]
        self.assertEqual(cm.reconcile_assignments(items), 0)
        self.assertEqual(cm.unresolved_count, 1)
        self.assertTrue(cm.unresolved_note)

    @unittest.skipUnless(os.name == "nt",
                         "路径大小写与斜杠归一属 Windows 语义（normcase）")
    def test_item_key_normalized(self):
        self.assertEqual(item_key(r"C:\A\b.TXT"), item_key("c:/a/B.txt"))


class UndoStackTest(unittest.TestCase):
    """首页「撤销上一步」用的栈：单项操作不能吃掉批量记录。"""

    def test_batch_then_single_keeps_both(self):
        from core.undo import UndoStack
        st = UndoStack()
        st.push([("a", ""), ("b", ""), ("c", "")])     # 批量移入
        st.push([("d", "工具")])                        # 右键单项
        self.assertEqual(len(st), 2)
        self.assertEqual(st.pop(), [("d", "工具")])
        # 关键：批量那一步还在，不会被单项覆盖
        self.assertEqual(st.pop(), [("a", ""), ("b", ""), ("c", "")])
        self.assertIsNone(st.pop())

    def test_depth_capped(self):
        from core.undo import UndoStack
        st = UndoStack(depth=3)
        for i in range(5):
            st.push([("p%d" % i, "")])
        self.assertEqual(len(st), 3)
        self.assertEqual(st.pop(), [("p4", "")])
        self.assertEqual(st.last_size, 1)

    def test_empty_push_ignored(self):
        from core.undo import UndoStack
        st = UndoStack()
        self.assertFalse(st.push([]))
        self.assertEqual(len(st), 0)
        self.assertFalse(bool(st))

    def test_group_by_category(self):
        from core.undo import UndoStack
        step = [("a", "工具"), ("b", ""), ("c", "工具")]
        self.assertEqual(UndoStack.group(step),
                         {"工具": ["a", "c"], "": ["b"]})


class IconsCacheKeyTest(unittest.TestCase):
    """图标缓存 key：斜杠写法不同不能变成两条缓存。"""

    @unittest.skipUnless(os.name == "nt",
                         "路径大小写与斜杠归一属 Windows 语义（normcase）")
    def test_slash_variants_share_one_key(self):
        from core.icons import cache_key
        self.assertEqual(cache_key(r"C:\Users\me\a.lnk", 48),
                         cache_key("C:/Users/me/a.lnk", 48))
        self.assertEqual(cache_key(r"C:\USERS\me\A.LNK", 48),
                         cache_key(r"c:\users\me\a.lnk", 48))

    def test_size_matters(self):
        from core.icons import cache_key
        self.assertNotEqual(cache_key(r"C:\a.lnk", 48),
                            cache_key(r"C:\a.lnk", 32))

    @unittest.skipUnless(os.name == "nt",
                         "路径大小写与斜杠归一属 Windows 语义（normcase）")
    def test_matches_config_item_key(self):
        """缓存 key 与 config 的归类 key 用同一套规范化，避免两边不一致。"""
        from core.icons import cache_key
        self.assertEqual(cache_key(r"C:\A\b.txt", 48)[0],
                         item_key("c:/a/B.txt"))


class PlanConfigTest(unittest.TestCase):
    """config 层日程计划 CRUD。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")
        self.cm = ConfigManager(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_get(self):
        pid = self.cm.add_plan("写周报", "2026-11-07", "发给组长")
        plan = self.cm.get_plan(pid)
        self.assertEqual(plan["title"], "写周报")
        self.assertEqual(plan["date"], "2026-11-07")
        self.assertFalse(plan["done"])
        self.assertEqual(plan["done_at"], "")
        # date 可空 = 不限日期的待办
        pid2 = self.cm.add_plan("随便想想")
        self.assertEqual(self.cm.get_plan(pid2)["date"], "")

    def test_update_done_records_done_at(self):
        pid = self.cm.add_plan("一件事", "2026-11-07")
        self.cm.update_plan(pid, done=True)
        plan = self.cm.get_plan(pid)
        self.assertTrue(plan["done"])
        self.assertTrue(plan["done_at"])          # 记了完成日期
        # 重做 → 清空
        self.cm.update_plan(pid, done=False)
        self.assertEqual(self.cm.get_plan(pid)["done_at"], "")

    def test_update_text_fields_and_remove(self):
        pid = self.cm.add_plan("原标题", "2026-11-07", "原备注")
        self.assertTrue(self.cm.update_plan(pid, title="新标题", note="新备注"))
        plan = self.cm.get_plan(pid)
        self.assertEqual(plan["title"], "新标题")
        self.assertEqual(plan["note"], "新备注")
        self.assertTrue(self.cm.remove_plan(pid))
        self.assertIsNone(self.cm.get_plan(pid))
        self.assertFalse(self.cm.remove_plan(pid))


class ScannerResilienceTest(unittest.TestCase):
    """扫描的健壮性：单个桌面目录不可读不能拖垮整个扫描。"""

    def test_unreadable_desktop_dir_skipped(self):
        from core import scanner
        real = scanner.get_desktop_paths
        tmp = tempfile.mkdtemp()
        try:
            ok_dir = os.path.join(tmp, "ok")
            os.mkdir(ok_dir)
            open(os.path.join(ok_dir, "a.txt"), "w").close()
            # 不存在的目录（权限错误 / OneDrive 临时不可读的替身）
            bad_dir = os.path.join(tmp, "gone")
            scanner.get_desktop_paths = lambda: [ok_dir, bad_dir]
            items = scanner.scan_desktop()
            self.assertEqual([i.name for i in items], ["a.txt"])
        finally:
            scanner.get_desktop_paths = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_all_dirs_gone_returns_empty_not_raise(self):
        from core import scanner
        real = scanner.get_desktop_paths
        scanner.get_desktop_paths = lambda: [
            os.path.join(tempfile.gettempdir(), "definitely-not-exists-xyz")]
        try:
            self.assertEqual(scanner.scan_desktop(), [])
        finally:
            scanner.get_desktop_paths = real


class SaveErrorTest(unittest.TestCase):
    """写盘失败（盘满 / 只读目录）不抛异常，而是记录并通知 error_reporter。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _readonly_cm(self):
        cm = ConfigManager(self.path)
        # 把目录改成只读，让任何写入都失败（Windows 下对已有文件仍可能可写，
        # 所以直接把 open 打成抛错，跨平台稳定）
        cm._save_atomic = lambda: (_ for _ in ()).throw(
            OSError(28, "No space left on device"))
        return cm

    def test_save_failure_recorded_not_raised(self):
        cm = self._readonly_cm()
        reported = []
        cm.error_reporter = reported.append
        cm.set_setting("theme", "dark")     # 不应当抛
        self.assertTrue(cm.save_error)
        self.assertEqual(len(reported), 1)  # reporter 被调到了
        # 失败不影响内存里的数据
        self.assertEqual(cm.get_setting("theme"), "dark")

    def test_save_success_clears_error(self):
        cm = ConfigManager(self.path)
        cm.save_error = "旧错误"
        cm.set_setting("theme", "dark")
        self.assertEqual(cm.save_error, "")
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["settings"]["theme"], "dark")


class PomodoroPersistTest(unittest.TestCase):
    """番茄钟状态落盘 / 恢复 / 统计累加。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.cm = ConfigManager(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_save_and_restore_roundtrip(self):
        state = {"phase": "focus", "end": 1234567890.0, "minutes": 25,
                 "break": 5, "paused": False, "pause_left": 0.0}
        self.cm.save_pomodoro(state)
        cm2 = ConfigManager(self.path)          # 模拟重启后重新加载
        self.assertEqual(cm2.get_setting("pomodoro"), state)

    def test_save_none_clears(self):
        self.cm.save_pomodoro({"end": 1.0})
        self.cm.save_pomodoro(None)
        cm2 = ConfigManager(self.path)
        self.assertIsNone(cm2.get_setting("pomodoro"))

    def test_record_pomo_accumulates(self):
        self.cm.record_pomo(25)
        self.cm.record_pomo(45)
        st = self.cm.get_setting("pomo_stats")
        self.assertEqual(st["sessions"], 2)
        self.assertEqual(st["focus_minutes"], 70)

    def test_record_pomo_survives_garbage(self):
        self.cm.data["settings"]["pomo_stats"] = "garbage"
        self.cm.record_pomo(30)
        self.assertEqual(self.cm.get_setting("pomo_stats"),
                         {"sessions": 1, "focus_minutes": 30})


class ReplaceAllTest(unittest.TestCase):
    """导入替换：合法 dict 生效并补全字段，非法结构拒绝。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.cm = ConfigManager(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_replace_dict_fills_defaults(self):
        self.assertTrue(self.cm.replace_all({"categories": ["A"]}))
        self.assertEqual(self.cm.categories, ["A"])
        # 缺省的字段补回默认（settings / plans 等），不 KeyError
        self.assertIn("theme", self.cm.settings)
        self.assertEqual(self.cm.plans, [])
        cm2 = ConfigManager(self.path)          # 落盘可重载
        self.assertEqual(cm2.categories, ["A"])

    def test_replace_non_dict_rejected(self):
        self.cm.add_category("原有")
        self.assertFalse(self.cm.replace_all([1, 2, 3]))
        self.assertFalse(self.cm.replace_all("junk"))
        # 未被破坏：默认 3 类 + 新增的「原有」都在
        self.assertEqual(self.cm.categories,
                         ["工具", "办公", "娱乐", "原有"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
