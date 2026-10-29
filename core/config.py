# -*- coding: utf-8 -*-
"""配置管理模块：分类与分配关系持久化到 config.json。"""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "categories": ["工具", "办公", "娱乐"],
    # key: 桌面项名称 -> value: 分类名
    "assignments": {}
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
