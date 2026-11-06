# -*- coding: utf-8 -*-
"""页面实例化冒烟：把每个页面真建出来一遍，带数据跑 refresh()。

test_core / test_design 全是纯逻辑和文本扫描，页面构造期崩溃（比如
v1.12 倒数日 _actions 三元素解包、refresh 在 __init__ 里被调用）完全
测不到 —— 用户点导航时异常被 Tk 回调吞掉，页面永远打不开。这个文件
就是补这个洞：每页实例化 + 造一条真实数据 + 强制重建，任何回归都会
在 CI 直接红。

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

require_tk = unittest.skipIf(tk is None, "当前 Python 没有 tkinter，跳过 GUI 用例")


@require_tk
class PageSmokeTest(unittest.TestCase):
    """逐页实例化。数据用独立临时配置，不碰用户的 config.json。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from core.config import ConfigManager
        cls._tmp = tempfile.mkdtemp()
        cls.cfg = ConfigManager(os.path.join(cls._tmp, "config.json"))
        # 造数据：没有数据的 refresh 分支（空态）测不出 _card/_focus_card
        cls._cid = cls.cfg.add_countdown("冒烟倒计时", "2099-01-01", note="x")
        cls._pid = cls.cfg.add_plan("冒烟计划", "2099-01-01", note="y")
        cls.app = None

    @classmethod
    def tearDownClass(cls):
        if cls.app is not None:
            try:
                cls.app.destroy()
            except Exception:
                pass

    def _app(self):
        """延迟建 App（每个用例独立，避免页面缓存互相污染）。"""
        from gui.app import App
        app = App.__new__(App)      # 不走 __init__ 的热键 / 托盘副作用
        tk.Tk.__init__(app)
        app.withdraw()
        app.config_mgr = self.cfg
        app.cfg = self.cfg      # property（pomo_minutes 等）读的是 self.cfg
        app.query = ""
        app._pages = {}
        app.current_page = None
        app.current_key = "home"
        from gui.theme import get_theme
        app.theme_name = self.cfg.get_setting("theme", "light")
        app.pomodoro = None     # SettingsPage / CountdownPage 直接读这个属性
        # SettingsPage 读热键对象的状态字段，给只读桩（不真注册热键）
        stub = type("HkStub", (), {})()
        stub.error = None
        app.hk = stub
        app.hk_auto = ""
        app.C = get_theme(app.theme_name)
        content = tk.Frame(app)
        content.pack(fill="both", expand=True)
        app.content = content
        # update_topbar 在无完整主窗口时会被调用，给个安全桩
        app.update_topbar = lambda *a, **k: None
        return app

    def test_every_page_builds(self):
        from gui.pages import PAGE_BY_KEY
        for key, page_cls in PAGE_BY_KEY.items():
            app = self._app()
            try:
                page = page_cls(app.content, app)     # 构造期就会 refresh
                app.update_idletasks()
                app.update()
                # 再调一次 refresh：构造路径之外的分支也跑到
                refresh = getattr(page, "refresh", None)
                if refresh is not None:
                    try:
                        refresh()
                    except TypeError:
                        refresh(rescan=False)         # DesktopPage.refresh 带参
                app.update_idletasks()
                app.update()
            except Exception as exc:
                self.fail("页面 %s(%s) 实例化/刷新崩溃: %r" % (key, page_cls.__name__, exc))
            finally:
                try:
                    page.destroy()
                except Exception:
                    pass
                app.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
