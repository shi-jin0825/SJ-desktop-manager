# -*- coding: utf-8 -*-
"""墨墨桌面管理助手 —— 功能演示动图录制脚本（全屏桌面视角）。

自动启动 App，逐场景驱动关键界面与悬浮桌宠，用 Pillow 截取**整个屏幕**、
把桌宠窗口（overrideredirect 分层窗口，GDI 截屏抓不到）用 Win32
`PrintWindow` 单独抓取后合成到画面中，再缩放并合成 GIF。

输出：assets/demo.gif（供 README「功能演示」引用）。

零运行时依赖原则：本脚本只用于开发期生成素材，不进入应用运行时；
依赖 Pillow（构建期工具，类比 PyInstaller）。

用法：
    py -3 tools/record_demo.py            # 录制全部场景（全屏桌面视角）
    py -3 tools/record_demo.py --list     # 只看场景清单
    py -3 tools/record_demo.py --frames N # 每个场景抓 N 帧（默认 6）
    py -3 tools/record_demo.py --width 1280 --height 800   # 输出尺寸

说明：
- 需要真实显示环境（Windows 桌面会话），无头环境会跳过。
- 悬浮桌宠会被拉到主窗口右侧入镜，并用 PrintWindow 单独抓取合成。
- 场景切换用 App 内部方法驱动，稳定可复现。
"""
import argparse
import ctypes
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tkinter as tk

SCENES = (
    ("home",       "首页磁贴"),
    ("search",     "全局搜索"),
    ("categories", "分类体系"),
    ("countdowns", "时间管理"),
    ("stats",      "数据统计"),
    ("pet",        "呼出桌宠"),
    ("pomodoro",   "番茄钟"),
)

PW_RENDERFULLCONTENT = 2


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
    ]


def capture_window(hwnd):
    """用 PrintWindow 抓指定窗口，返回 (PIL.Image, left, top)。"""
    from PIL import Image
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None, rect.left, rect.top

    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)

    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight, bmi.biPlanes = w, -h, 1
    bmi.biBitCount, bmi.biCompression = 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)

    if not ok:
        return None, rect.left, rect.top
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    return img, rect.left, rect.top


def _position_pet_near_main(app):
    pet = getattr(app, "_pet", None)
    if pet is None:
        return
    try:
        main_right = app.winfo_rootx() + app.winfo_width()
        main_top = app.winfo_rooty()
        pet.x = float(main_right + 40)
        pet.y = float(main_top + 60)
        # 同时更新浮动中心与速度，避免物理引擎下一帧把桌宠拉回原地面
        pet._base_y = pet.y
        pet.vy = 0.0
        pet.vx = 0.0
        pet.geometry(f"+{int(pet.x)}+{int(pet.y)}")
        app.update_idletasks()
    except Exception:
        pass


def grab_frame(app, out_dir, name, out_size):
    """截全屏 + 合成桌宠，缩放后存 PNG。"""
    from PIL import ImageGrab, Image
    full = ImageGrab.grab().convert("RGB")

    # 桌宠单独抓取并贴到全屏对应坐标
    pet = getattr(app, "_pet", None)
    if pet is not None:
        try:
            pet_img, left, top = capture_window(pet.winfo_id())
            if pet_img is not None:
                pet_rgba = pet_img.convert("RGBA")
                # 桌宠窗口用 -transparentcolor 做透明，PrintWindow 抓到时
                # 透明区域被渲染成纯黑 (0,0,0)；把近黑像素置透明避免黑块。
                px = pet_rgba.load()
                for y in range(pet_rgba.height):
                    for x in range(pet_rgba.width):
                        r, g, b, a = px[x, y]
                        if r < 12 and g < 12 and b < 12:
                            px[x, y] = (0, 0, 0, 0)
                full = full.convert("RGBA")
                full.paste(pet_rgba, (left, top), pet_rgba)
                full = full.convert("RGB")
        except Exception:
            pass

    if out_size:
        full = full.resize(out_size, Image.LANCZOS)
    path = os.path.join(out_dir, name)
    full.save(path)
    return path


def run(out_dir, frames_per_scene, out_size):
    from gui.app import App

    app = App()
    app.update()
    try:
        app.lift()
        app.update()
        time.sleep(0.3)
    except Exception:
        pass

    frames = []
    step = 0

    def snap(name):
        nonlocal step
        app.update_idletasks()
        app.update()
        time.sleep(0.12)
        p = grab_frame(app, out_dir, f"{step:03d}_{name}.png", out_size)
        step += 1
        frames.append((name, p))
        return p

    def reset_search():
        try:
            app.search_var.set("")
            app.update_idletasks()
        except Exception:
            pass

    # 临时归类：给几个真实桌面项归到分类，让分类页/统计页有层次。
    # 录完在 finally 里恢复原状，不污染用户配置。
    demo_assignments = []

    def demo_assign():
        """扫描桌面项，挑前几项临时归到「工具/办公/娱乐」，返回可恢复清单。"""
        try:
            from core.scanner import scan_desktop
            items = scan_desktop()
            # 按分类轮转分配：第 i 个未归类项归到第 i%3 个分类，避免重复
            cats = ["工具", "办公", "娱乐"]
            per_cat = 3
            counts = {c: 0 for c in cats}
            for it in items:
                if app.config_mgr.get_category(it.path, it.name):
                    continue   # 已有归类，跳过
                cat = cats[len(demo_assignments) % len(cats)]
                if counts[cat] >= per_cat:
                    continue
                app.config_mgr.assign(it.path, cat)
                demo_assignments.append((it.path, cat))
                counts[cat] += 1
                if all(v >= per_cat for v in counts.values()):
                    break
            return len(demo_assignments)
        except Exception:
            return 0

    def demo_unassign():
        for p, cat in demo_assignments:
            try:
                app.config_mgr.unassign(p)
            except Exception:
                pass

    try:
        # 0. 提前呼出桌宠，全程陪伴
        if not app.pet_active():
            app._toggle_pet()
            app.update()
            time.sleep(0.4)

        # 1. 首页磁贴（桌宠已在旁陪伴）
        app._show_page("home", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("home")

        # 2. 全局搜索
        app._show_page("home", force=True)
        app.search_var.set("")
        app.update()
        _position_pet_near_main(app)
        snap("search_0")
        app.search_var.set("墨")
        app.update()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("search")
        reset_search()

        # 3. 分类体系（先临时归类，让分类页有内容）
        demo_assign()
        app._show_page("categories", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("categories")

        # 4. 时间管理
        app._show_page("countdowns", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("countdowns")

        # 5. 数据统计
        app._show_page("stats", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("stats")

        # 6. 番茄钟（桌宠伴学状态）
        app._show_page("countdowns", force=True)
        app.start_pomodoro(1, 1)
        app.update()
        time.sleep(0.4)
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("pomodoro")
        app.stop_pomodoro()

    finally:
        # 恢复临时归类，收起桌宠
        demo_unassign()
        try:
            if app.pet_active():
                app._toggle_pet()
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass

    return frames


def make_gif(frames, out_path, fps=10):
    from PIL import Image
    imgs = [Image.open(p) for _, p in frames]
    if not imgs:
        return None
    imgs[0].save(
        out_path, save_all=True, append_images=imgs[1:],
        duration=int(1000 / fps), loop=0, optimize=True,
    )
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=int, default=6, help="每个场景抓帧数（默认 6）")
    ap.add_argument("--width", type=int, default=1280, help="输出宽度（默认 1280）")
    ap.add_argument("--height", type=int, default=800, help="输出高度（默认 800）")
    ap.add_argument("--out", default=None, help="输出 GIF 路径")
    ap.add_argument("--list", action="store_true", help="只打印场景清单")
    args = ap.parse_args()

    if args.list:
        for key, label in SCENES:
            print(f"{key:12s} {label}")
        return

    try:
        r = tk.Tk(); r.withdraw(); r.destroy()
    except tk.TclError:
        print("无显示环境，跳过录屏（需在 Windows 桌面会话运行）")
        return

    import tempfile
    tmp = tempfile.mkdtemp(prefix="momo_demo_")
    out = args.out or os.path.join(_ROOT, "assets", "demo.gif")
    out_size = (args.width, args.height)

    frames = run(tmp, args.frames, out_size)
    if not frames:
        print("未捕获到任何帧")
        return

    gif = make_gif(frames, out)
    print(f"共 {len(frames)} 帧，输出：{gif}")
    print("临时帧目录：", tmp)


if __name__ == "__main__":
    main()
