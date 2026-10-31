# -*- coding: utf-8 -*-
"""配置管理模块：分类、分配关系、倒计时与界面设置持久化到 config.json。"""
import json
import os
import time

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "categories": ["工具", "办公", "娱乐"],
    # key: 桌面项名称 -> value: 分类名
    "assignments": {},
    # 界面设置（如 theme: light / dark）
    "settings": {"theme": "light"},
    # 专属倒计时（倒数日）：[{id, title, date, note, repeat, created}]
    "countdowns": [],
}


class ConfigManager:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        # 补全缺失字段
        for key, val in DEFAULT_CONFIG.items():
            data.setdefault(key, json.loads(json.dumps(val)))
        return data

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

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

    # ---- 分配管理 ----
    def assign(self, item_name: str, category: str):
        if category in self.categories:
            self.data["assignments"][item_name] = category
            self.save()

    def unassign(self, item_name: str):
        self.data["assignments"].pop(item_name, None)
        self.save()

    def get_category(self, item_name: str) -> str:
        return self.data["assignments"].get(item_name, "")

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
