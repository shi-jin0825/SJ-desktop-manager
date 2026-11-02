# -*- coding: utf-8 -*-
"""整理操作的多步撤销栈（纯逻辑，不依赖 tkinter，方便单测）。

背景：早先首页用单个 _last_op 记"上一步"，而右键单项操作也会写它 ——
于是「批量移一批 → 右键再动一项 → 撤销」只会回退最后那一个，批量记录
凭空消失。改成栈之后每一步都留着，深度封顶防止长时间整理无限堆积。
"""


class UndoStack(object):
    """最近若干步操作的快照栈，每步是 [(路径, 操作前的分类), ...]。"""

    def __init__(self, depth: int = 10):
        self.depth = max(1, int(depth))
        self._steps = []

    # ---- 写入 ----
    def push(self, entries) -> bool:
        """记一步；空操作不入栈，返回是否真的记下了。"""
        step = list(entries or [])
        if not step:
            return False
        self._steps.append(step)
        if len(self._steps) > self.depth:
            del self._steps[:-self.depth]      # 超出深度丢最早的
        return True

    # ---- 读取 ----
    def pop(self):
        """取出最近一步并移除；没有可撤销的返回 None。"""
        return self._steps.pop() if self._steps else None

    def clear(self):
        self._steps.clear()

    def __len__(self):
        return len(self._steps)

    def __bool__(self):
        return bool(self._steps)

    @property
    def last_size(self) -> int:
        """最近一步涉及几项（操作条上显示"上次整理了 N 项"用）。"""
        return len(self._steps[-1]) if self._steps else 0

    # ---- 还原 ----
    @staticmethod
    def group(step):
        """把一步 [(path, cat), ...] 归并成 {分类: [路径, ...]}。

        空分类（原本未归类）用 "" 表示，调用方据此决定 assign / unassign。
        """
        out = {}
        for path, cat in step or ():
            out.setdefault(cat or "", []).append(path)
        return out
