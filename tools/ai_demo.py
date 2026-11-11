# -*- coding: utf-8 -*-
"""墨墨 AI 对话 —— UI 集成示例 / 最小可运行 Demo。

演示如何在现有 Tkinter 界面里接入 core.ai_client：
  1. 一个输入框 + 一个「对话」按钮
  2. 点击后把用户输入交给 App.ask_momo（内部起子线程）
  3. 主线程立刻显示「墨墨正在思考中…」
  4. 子线程拿到结果后切回主线程，把回复画进气泡

直接运行：  py -3 tools/ai_demo.py
（依赖：已设置 ZHIPU_API_KEY 环境变量；未设置也能跑，会返回友好提示）

这段代码是「示例」，直接抄进 pages.py 的某个页面即可复用同样的模式。
"""
import os
import sys
import tkinter as tk

# 让脚本能从仓库根目录 import gui / core（直接跑本文件时需要）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.theme import get_theme
from gui.fonts import font
from gui.widgets import rounded_rect


class AiDemo(tk.Tk):
    """一个独立的对话小窗口，演示完整调用链。"""

    def __init__(self):
        super().__init__()
        self.title("墨墨 AI 对话 Demo")
        self.geometry("520x560")
        self.C = get_theme("light")
        c = self.C
        self.configure(bg=c["app_bg"])

        # 聊天区（用 Canvas 画气泡）
        self.chat = tk.Canvas(self, bg=c["app_bg"], highlightthickness=0)
        self.chat.pack(fill="both", expand=True, padx=16, pady=(16, 0))
        self._y = 16   # 气泡累计的纵向游标

        # 底部输入区
        bar = tk.Frame(self, bg=c["app_bg"])
        bar.pack(fill="x", padx=16, pady=16)
        self.entry = tk.Entry(bar, font=font(12), bg=c["panel_bg"],
                              fg=c["text"], insertbackground=c["text"],
                              relief="flat", highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True,
                        ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.send())
        self.btn = tk.Button(bar, text="对话", command=self.send,
                             bg=c["accent"], fg="white", relief="flat",
                             font=font(12), activebackground=c["accent"],
                             cursor="hand2", padx=18, pady=6)
        self.btn.pack(side="right")

        self._bubble("墨墨", "嗨！我是墨墨，想问什么都可以～  \n（AI 对话示例）")

    # ---- 气泡绘制（可抄进任何页面复用）----
    def _bubble(self, who, text):
        c = self.C
        is_me = who == "我"
        fg = c["text"]
        # 用户气泡靠右、墨墨气泡靠左
        anchor = "e" if is_me else "w"
        x_pad = 100 if is_me else 0     # 右侧留空，让气泡右对齐
        box_w = 460
        fnt = font(12)
        # 先估算文本需要的行高，再画圆角气泡
        lines = text.split("\n")
        line_h = 22
        h = len(lines) * line_h + 24
        x = 8 + x_pad
        fill = c["accent"] if is_me else c["panel_bg"]
        txt = "white" if is_me else fg
        rounded_rect(self.chat, x, self._y, x + box_w, self._y + h, 12,
                     fill=fill, outline="")
        self.chat.create_text(x + 16, self._y + 14, anchor="nw",
                              text=text, fill=txt, font=fnt, width=box_w - 32)
        self._y += h + 12
        # 滚到底
        self.chat.update_idletasks()
        self.chat.config(scrollregion=(0, 0, 0, self._y))
        self.chat.yview_moveto(1.0)

    # ---- 核心调用链（关键！）----
    def send(self):
        question = self.entry.get().strip()
        if not question:
            return
        self.entry.delete(0, "end")
        self._bubble("我", question)

        # on_start：主线程，请求刚发出时显示「思考中」
        # on_done ：子线程拿结果后切回主线程，把回复画进气泡
        self.app_shell_ask_momo(
            question,
            on_start=lambda: self._bubble("墨墨", "墨墨正在思考中…"),
            on_done=lambda ans: self._replace_last_bubble("墨墨", ans),
        )

    # 这里直接内联一个 ask_momo（不依赖 gui.app.App 也能跑通 demo），
    # 真正的项目里应调用 self.app.ask_momo(...)
    def app_shell_ask_momo(self, question, on_done=None, on_start=None):
        import threading
        from core.ai_client import ask_ai

        def _worker():
            ans = ask_ai(question)
            try:
                self.after(0, lambda: on_done(ans) if on_done else None)
            except tk.TclError:
                pass

        if on_start:
            on_start()
        threading.Thread(target=_worker, daemon=True).start()

    def _replace_last_bubble(self, who, text):
        # 简化处理：demo 里直接把「思考中」替换为最终回复（重新定位游标）
        self._y = max(16, self._y - 22 - 12)  # 粗略回收最后一行
        self._bubble(who, text)


if __name__ == "__main__":
    AiDemo().mainloop()
