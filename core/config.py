# -*- coding: utf-8 -*-
"""配置管理模块：分类、分配关系、倒计时与界面设置持久化到 config.json。

数据安全约定（P0）：
    * 写入：先写 config.json.tmp → fsync → os.replace 原子替换，
      断电/崩溃时不会留下半截文件。
    * 备份：每次成功写入前，把上一份「好配置」留成 config.json.bak。
    * 读取：主文件坏了自动回退 .bak，并把损坏文件留成 .corrupt-<时间戳>
      供人工检查；再坏才回默认配置（且不再静默 —— 由 load_status 告知调用方）。
"""
import json
import os
import time

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

# 备份 / 临时文件后缀
BAK_SUFFIX = ".bak"
TMP_SUFFIX = ".tmp"

# 归类 key 的版本：1 = 老版按文件名，2 = 按规范化路径
ASSIGN_KEY_VERSION = 2

DEFAULT_CONFIG = {
    "categories": ["工具", "办公", "娱乐"],
    # key: 桌面项的规范化路径（旧版是文件名） -> value: 分类名
    "assignments": {},
    # 界面设置（如 theme: light / dark）
    # pomodoro_minutes / pomodoro_break：番茄钟专注与休息时长（分钟）
    "settings": {"theme": "light",
                 "pomodoro_minutes": 45,
                 "pomodoro_break": 5},
    # 专属倒计时（倒数日）：[{id, title, date, note, repeat, created}]
    "countdowns": [],
    # 日程计划（时间管理页）：[{id, title, date, note, done, done_at, created}]
    # date 可为空 = 不限日期的待办；done_at 记录勾选完成的日期
    "plans": [],
    # 归类 key 方案版本（用于旧配置自动迁移）
    "assign_key_version": ASSIGN_KEY_VERSION,
}


def item_key(path: str) -> str:
    """桌面项在 assignments 里的 key：规范化后的绝对路径。

    早先直接用文件名做 key，于是「文件改名 / 移动后归类静默失效」，
    而且用户桌面与公共桌面的同名项目会互相顶掉。改成路径后这两个问题
    都没了；大小写不敏感用 normcase 统一（Windows 下等价）。
    """
    return os.path.normcase(os.path.abspath(path))


def _read_json(path: str):
    """读一个 JSON 文件；坏了返回 None（不抛）。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


class ConfigManager:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        # 加载结果说明："" 正常 / "recovered" 从备份恢复 / "reset" 已重置为默认
        self.load_status = ""
        self.status_note = ""
        self.data = self._load()
        self._migrate()

    def _migrate(self):
        """旧配置升级：把 assign_key_version 提到当前版本。"""
        if int(self.data.get("assign_key_version", 1) or 1) >= ASSIGN_KEY_VERSION:
            return
        # 旧的「文件名 key」不动 —— get_category / migrate_assignments
        # 会在扫描到对应文件时自动换成路径 key，用户看不到任何丢失。
        self.data["assign_key_version"] = ASSIGN_KEY_VERSION
        self.save()

    # ---------------- 读取 ----------------
    def _load(self) -> dict:
        data = _read_json(self.path)
        if data is not None:
            self.load_status = ""
            return self._fill(data)

        # 主文件坏了 —— 先试备份
        bak = self.path + BAK_SUFFIX
        recovered = _read_json(bak)
        if recovered is not None:
            self._quarantine()
            self.load_status = "recovered"
            self.status_note = ("config.json 读取失败，已自动从 config.json.bak 恢复；"
                                "损坏的原件保留为 %s"
                                % os.path.basename(self._corrupt_name()))
            return self._fill(recovered)

        if os.path.isfile(self.path):
            self._quarantine()
            self.load_status = "reset"
            self.status_note = ("config.json 与备份都已损坏，已重置为默认配置；"
                                "原件保留为 %s"
                                % os.path.basename(self._corrupt_name()))
        else:
            self.load_status = ""      # 第一次用，本来就没有文件
        return self._fill({})

    def _fill(self, data: dict) -> dict:
        """补全缺失字段，避免旧配置升级后 KeyError。"""
        for key, val in DEFAULT_CONFIG.items():
            data.setdefault(key, json.loads(json.dumps(val)))
        return data

    def _corrupt_name(self) -> str:
        return "%s.corrupt-%s" % (self.path, time.strftime("%Y%m%d-%H%M%S"))

    def _quarantine(self):
        """把读不出来的原件挪到一边，留给用户人工检查。"""
        dest = self._corrupt_name()
        try:
            os.replace(self.path, dest)
        except OSError:
            try:
                os.remove(self.path)
            except OSError:
                pass

    # ---------------- 写入 ----------------
    def save(self):
        """原子写入：临时文件 → fsync → os.replace，并保留上一份为 .bak。"""
        text = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp = self.path + TMP_SUFFIX
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            # 临时文件都写不出去（盘满 / 只读）：退回直接写，至少不留半截 tmp
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            return

        # 备份上一份「好配置」
        try:
            if os.path.isfile(self.path):
                with open(self.path, "rb") as src, \
                        open(self.path + BAK_SUFFIX, "wb") as dst:
                    dst.write(src.read())
        except OSError:
            pass
        try:
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)

    # ---- 界面设置 ----
    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key: str, value):
        self.settings[key] = value
        self.save()

    # ---- 分类管理 ----
    @property
    def categories(self) -> list:
        return self.data["categories"]

    def add_category(self, name: str) -> bool:
        name = name.strip()
        if not name or name in self.categories:
            return False
        self.categories.append(name)
        self.save()
        return True

    def rename_category(self, old: str, new: str) -> bool:
        """重命名分类，同时更新已归属的项目；失败返回 False。"""
        new = (new or "").strip()
        if not new or new == old or new in self.categories:
            return False
        if old not in self.categories:
            return False
        self.categories[self.categories.index(old)] = new
        for key, val in self.data["assignments"].items():
            if val == old:
                self.data["assignments"][key] = new
        self.save()
        return True

    def remove_category(self, name: str):
        if name in self.categories:
            self.categories.remove(name)
        # 该分类下的项目回到未分类
        for key in [k for k, v in self.data["assignments"].items() if v == name]:
            del self.data["assignments"][key]
        self.save()

    # ---------------- 分配管理 ----------------
    def assign(self, path: str, category: str):
        """把某个桌面项（按路径）归到分类。"""
        if category in self.categories:
            self.data["assignments"][item_key(path)] = category
            self.save()

    def unassign(self, path: str):
        self.data["assignments"].pop(item_key(path), None)
        self.data["assignments"].pop(os.path.basename(path), None)  # 旧 key
        self.save()

    def get_category(self, path: str, name: str = "") -> str:
        """查某个桌面项的分类；顺手把旧版「按文件名」的归类迁移成按路径。"""
        key = item_key(path)
        got = self.data["assignments"].get(key)
        if not got and name and name in self.data["assignments"]:
            got = self.data["assignments"].pop(name)   # 老数据升级
            self.data["assignments"][key] = got
            self.save()
        return got or ""

    def assign_batch(self, paths, category: str) -> int:
        """批量归类（一次 save），返回成功条数。"""
        if category not in self.categories:
            return 0
        n = 0
        for p in paths:
            self.data["assignments"][item_key(p)] = category
            n += 1
        if n:
            self.save()
        return n

    def unassign_batch(self, paths) -> int:
        n = 0
        for p in paths:
            if self.data["assignments"].pop(item_key(p), None) is not None:
                n += 1
        if n:
            self.save()
        return n

    def migrate_assignments(self, items) -> int:
        """扫描后调用：把旧版「文件名 key」批量换成路径 key，返回迁移条数。"""
        moved = 0
        for it in items:
            path = getattr(it, "path", it)
            name = getattr(it, "name", None) or os.path.basename(path)
            if name in self.data["assignments"]:
                key = item_key(path)
                self.data["assignments"].setdefault(key,
                                                    self.data["assignments"].pop(name))
                moved += 1
        if moved:
            self.data["assign_key_version"] = ASSIGN_KEY_VERSION
            self.save()
        return moved

    def prune_assignments(self, alive_paths) -> int:
        """清掉指向已不存在文件的归类（改名/移动/删除后留下的死条目）。

        只清理「看起来像路径」的 key，旧版文件名 key 不动（等迁移处理）。
        返回清理条数。
        """
        alive = set(item_key(p) for p in alive_paths)
        dead = [k for k in self.data["assignments"]
                if os.path.isabs(k) and k not in alive]
        for k in dead:
            del self.data["assignments"][k]
        if dead:
            self.save()
        return len(dead)

    # ---- 专属倒计时（倒数日）----
    @property
    def countdowns(self) -> list:
        return self.data["countdowns"]

    def add_countdown(self, title: str, date: str, note: str = "",
                      repeat: bool = False) -> str:
        """新增一条倒计时，返回它的 id。"""
        cid = "cd%d" % int(time.time() * 1000)
        # 保证 id 唯一（同一毫秒内连续创建时）
        while any(c.get("id") == cid for c in self.countdowns):
            cid += "x"
        self.countdowns.append({
            "id": cid,
            "title": title.strip(),
            "date": date,
            "note": (note or "").strip(),
            "repeat": bool(repeat),
            "created": time.strftime("%Y-%m-%d"),
        })
        self.save()
        return cid

    def update_countdown(self, cid: str, **fields) -> bool:
        """更新一条倒计时的字段（title / date / note / repeat）。"""
        for item in self.countdowns:
            if item.get("id") == cid:
                for key, val in fields.items():
                    if key in ("title", "date", "note"):
                        item[key] = (val or "").strip() if key != "date" else val
                    elif key == "repeat":
                        item[key] = bool(val)
                self.save()
                return True
        return False

    def remove_countdown(self, cid: str) -> bool:
        for i, item in enumerate(self.countdowns):
            if item.get("id") == cid:
                self.countdowns.pop(i)
                self.save()
                return True
        return False

    def get_countdown(self, cid: str):
        for item in self.countdowns:
            if item.get("id") == cid:
                return item
        return None

    # ---- 日程计划（时间管理）----
    @property
    def plans(self) -> list:
        return self.data["plans"]

    def add_plan(self, title: str, date: str = "", note: str = "") -> str:
        """新增一条日程计划，返回它的 id。"""
        pid = "pl%d" % int(time.time() * 1000)
        while any(p.get("id") == pid for p in self.plans):
            pid += "x"
        self.plans.append({
            "id": pid,
            "title": title.strip(),
            "date": date or "",
            "note": (note or "").strip(),
            "done": False,
            "done_at": "",
            "created": time.strftime("%Y-%m-%d"),
        })
        self.save()
        return pid

    def update_plan(self, pid: str, **fields) -> bool:
        """更新一条计划：title / date / note 文本字段，done 布尔。

        done 由 False 翻成 True 时自动记 done_at（今天），方便之后
        按完成时间排序；反向（重做）时清空。
        """
        for item in self.plans:
            if item.get("id") == pid:
                for key, val in fields.items():
                    if key in ("title", "note"):
                        item[key] = (val or "").strip()
                    elif key == "date":
                        item[key] = val or ""
                    elif key == "done":
                        was = bool(item.get("done"))
                        item[key] = bool(val)
                        if item[key] and not was:
                            item["done_at"] = time.strftime("%Y-%m-%d")
                        elif was and not item[key]:
                            item["done_at"] = ""
                self.save()
                return True
        return False

    def remove_plan(self, pid: str) -> bool:
        for i, item in enumerate(self.plans):
            if item.get("id") == pid:
                self.plans.pop(i)
                self.save()
                return True
        return False

    def get_plan(self, pid: str):
        for item in self.plans:
            if item.get("id") == pid:
                return item
        return None
