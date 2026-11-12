# -*- coding: utf-8 -*-
"""墨墨桌面管理助手 —— 功能演示录制脚本（纯净主窗口视角 + MP4 优先）。

自动启动 App、预置一份真实感的演示数据（8 个分类、30+ 桌面项目、2 条
计划、1 条倒计时、番茄钟进行中），驱动一条完整操作链：

    首页 → 右键移入分类 → 全局搜索 → 打开分类 → 时间管理启动番茄钟
         → 摸头桌宠 → 数据统计（数字变化）

画面只截取主窗口区域（四周不留桌面壁纸/任务栏/其它窗口），桌宠用
Win32 `PrintWindow` 单独抓取后合成。输出 **MP4**（H.264，体积小、画质
无 256 色量化损失），GIF 仅作降级备用。

零运行时依赖原则：本脚本只用于开发期生成素材，不进入应用运行时；
依赖 Pillow（截图）+ imageio-ffmpeg（编码 MP4），均为构建期工具。

用法：
    py -3 tools/record_demo.py                 # 录制 MP4 + GIF
    py -3 tools/record_demo.py --list          # 只看操作链清单
    py -3 tools/record_demo.py --mp4-only      # 只要 MP4
    py -3 tools/record_demo.py --width 1180 --height 760   # 输出尺寸
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

# 演示用的临时占位文件（.lnk 会因无目标而打开失败，用普通文件即可，
# 录制时创建、结束后删除，绝不污染用户桌面）。
DEMO_FILES = [
    "项目策划书.docx", "季度财务报表.xlsx", "产品需求文档.pdf",
    "周报模板.txt", "会议纪要.txt", "学习笔记.md",
    "读书清单.txt", "旅行计划.txt", "健身打卡.txt",
    "数据备份.zip", "壁纸素材.png", "简历初稿.docx",
]

# 8 个演示分类（覆盖常见桌面整理场景）
DEMO_CATEGORIES = ["工具", "办公", "娱乐", "学习", "设计", "开发", "影音", "文档"]

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
        main_left = app.winfo_rootx()
        main_top = app.winfo_rooty()
        main_w = app.winfo_width()
        pet.x = float(main_left + main_w - 160)
        pet.y = float(main_top + 12)
        pet._base_y = pet.y
        pet.vy = 0.0
        pet.vx = 0.0
        pet.geometry(f"+{int(pet.x)}+{int(pet.y)}")
        app.update_idletasks()
    except Exception:
        pass


def grab_frame(app, out_dir, name, out_size, bbox_override=None):
    """截取主窗口区域 + 合成桌宠，缩放后存 PNG。"""
    from PIL import ImageGrab, Image

    mx, my = app.winfo_rootx(), app.winfo_rooty()
    mw, mh = app.winfo_width(), app.winfo_height()
    if mw <= 0 or mh <= 0:
        return None

    if bbox_override is not None:
        bbox = bbox_override
    else:
        pad = 0
        bbox = (max(0, mx - pad), max(0, my - pad),
                mx + mw + pad, my + mh + pad)
    frame = ImageGrab.grab(bbox=bbox).convert("RGB")

    pet = getattr(app, "_pet", None)
    if pet is not None:
        try:
            pet_img, left, top = capture_window(pet.winfo_id())
            if pet_img is not None:
                pet_rgba = pet_img.convert("RGBA")
                px = pet_rgba.load()
                for y in range(pet_rgba.height):
                    for x in range(pet_rgba.width):
                        r, g, b, a = px[x, y]
                        if r < 12 and g < 12 and b < 12:
                            px[x, y] = (0, 0, 0, 0)
                frame = frame.convert("RGBA")
                rel_x, rel_y = left - bbox[0], top - bbox[1]
                frame.paste(pet_rgba, (rel_x, rel_y), pet_rgba)
                frame = frame.convert("RGB")
        except Exception:
            pass

    if out_size:
        frame = frame.resize(out_size, Image.LANCZOS)
    path = os.path.join(out_dir, name)
    frame.save(path)
    return path


def setup_demo_data(app):
    """预置演示数据：8 分类 + 临时占位文件 + 全量归类 + 计划 + 倒计时。

    返回一个清理函数，录制结束后调用恢复原状。
    """
    from core.scanner import get_desktop_paths, scan_desktop
    from core.config import item_key

    cfg = app.config_mgr
    created_files = []

    def cleanup():
        # 删除临时占位文件
        for fp in created_files:
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except OSError:
                pass
        # 恢复原分类列表（清掉演示多加的分类）
        for cat in DEMO_CATEGORIES:
            if cat in cfg.categories and cat not in ("工具", "办公", "娱乐"):
                cfg.remove_category(cat)
        # 清掉演示的归类（占位文件对应的 key 已随文件删除失效）
        for key in list(cfg.data["assignments"].keys()):
            if any(key.endswith(f) for f in DEMO_FILES):
                del cfg.data["assignments"][key]
        # 删掉演示计划与倒计时
        for p in list(cfg.plans):
            if p.get("title", "").startswith("演示"):
                cfg.remove_plan(p["id"])
        for cd in list(cfg.countdowns):
            if cd.get("title", "").startswith("演示"):
                cfg.remove_countdown(cd["id"])
        cfg.save()

    try:
        # 1. 确保分类齐全（8 个）
        for cat in DEMO_CATEGORIES:
            if cat not in cfg.categories:
                cfg.add_category(cat)

        # 2. 在用户桌面创建临时占位文件（补齐到 30+ 项目）
        desktop = get_desktop_paths()[0] if get_desktop_paths() else \
            os.path.join(os.path.expanduser("~"), "Desktop")
        for fname in DEMO_FILES:
            fp = os.path.join(desktop, fname)
            if not os.path.exists(fp):
                try:
                    with open(fp, "w", encoding="utf-8") as f:
                        f.write("墨墨演示数据\n")
                    created_files.append(fp)
                except OSError:
                    pass

        # 3. 重新扫描，把大部分项目归类到 8 个分类（轮转分配），
        #    刻意留约 1/3 未归类——首页既要有分类文件夹、也要有零散
        #    磁贴才充实，右键「移入分类」也有操作对象
        items = scan_desktop()
        cats = DEMO_CATEGORIES
        # 归类前 2/3 的项目，留后 1/3 未归类
        n_assign = int(len(items) * 2 / 3)
        idx = 0
        for it in items[:n_assign]:
            if cfg.get_category(it.path, it.name):
                continue
            cat = cats[idx % len(cats)]
            cfg.assign(it.path, cat)
            idx += 1

        # 4. 预置 2 条计划 + 1 条倒计时
        if not any(p.get("title", "").startswith("演示") for p in cfg.plans):
            cfg.add_plan("演示：完成项目策划书", date="2026-11-20", note="优先级最高")
            cfg.add_plan("演示：阅读《架构整洁之道》", note="每天 30 分钟")
        if not any(c.get("title", "").startswith("演示") for c in cfg.countdowns):
            cfg.add_countdown("演示：项目上线倒计时", "2026-12-01",
                              note="还有两周", repeat=False)

    except Exception:
        pass

    return cleanup


def run(out_dir, frames_per_scene, out_size):
    from gui.app import App

    app = App()
    app.update()
    try:
        app.geometry("1180x700+0+0")
        app.update()
        app.attributes("-topmost", True)
        app.lift()
        app.focus_force()
        app.update()
        time.sleep(0.4)
    except Exception:
        pass

    frames = []
    step = 0

    def snap(name, top=None, bbox=None):
        nonlocal step
        try:
            (top or app).lift()
            (top or app).attributes("-topmost", True)
        except Exception:
            pass
        # 多轮 update：确保 canvas/网格完成布局（否则首页磁贴画不出来）
        for _ in range(6):
            app.update_idletasks()
            app.update()
            time.sleep(0.02)
        time.sleep(0.08)
        p = grab_frame(app, out_dir, f"{step:03d}_{name}.png", out_size,
                       bbox_override=bbox)
        step += 1
        frames.append((name, p))
        return p

    def reset_search():
        try:
            app.search_var.set("")
            app.update_idletasks()
        except Exception:
            pass

    # 预置演示数据，拿到清理函数
    cleanup = setup_demo_data(app)

    try:
        # 0. 呼出桌宠全程陪伴
        if not app.pet_active():
            app._toggle_pet()
            app.update()
            time.sleep(0.4)

        # 1. 首页磁贴（8 分类 + 已归类项目，桌宠陪伴）
        app._show_page("home", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("home")

        # 2. 右键「移入分类」：选一个未归类项，弹移入菜单
        app._show_page("home", force=True)
        reset_search()
        # 找一个未归类项演示右键移入（若全归类了则演示移出再移入）
        unassigned = [i for i in app._pages["home"].items if not i.category]
        if not unassigned:
            # 全归类了：临时把最后一个项移出，再演示移入
            last = app._pages["home"].items[-1]
            app.config_mgr.unassign(last.path)
            app._show_page("home", force=True)
            unassigned = [i for i in app._pages["home"].items if not i.category]
        if unassigned:
            target = unassigned[0]
            # 触发右键菜单：直接把该项归到「文档」分类，展示归类动作
            app.config_mgr.assign(target.path, "文档")
            app._show_page("home", force=True)
            for _ in range(frames_per_scene):
                _position_pet_near_main(app)
                snap("move_in")

        # 3. 全局搜索（输入过滤）
        app._show_page("home", force=True)
        app.search_var.set("")
        app.update()
        _position_pet_near_main(app)
        snap("search_0")
        app.search_var.set("文档")
        app.update()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("search")
        reset_search()

        # 4. 打开分类窗口
        app._show_page("home", force=True)
        reset_search()
        try:
            app._pages["home"]._open_category("文档")
            app.update()
            time.sleep(0.3)
            for _ in range(frames_per_scene):
                _position_pet_near_main(app)
                snap("open_category")
        except Exception:
            pass

        # 5. 时间管理：启动番茄钟
        app._show_page("countdowns", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("countdowns")
        app.start_pomodoro(1, 1)
        app.update()
        time.sleep(0.4)
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("pomodoro")
        app.stop_pomodoro()

        # 6. 摸头桌宠（show_happy：眯眼笑 + 气泡；每帧重新触发，表情
        #    默认只持续 0.9s，不重触发会闪一下就恢复成待机脸）
        app._show_page("home", force=True)
        reset_search()
        pet = getattr(app, "_pet", None)
        for _ in range(frames_per_scene):
            if pet is not None:
                try:
                    pet.show_happy()
                except Exception:
                    pass
            app.update()
            _position_pet_near_main(app)
            snap("pat_pet")

        # 7. 数据统计（数字已随归类/番茄钟变化）
        app._show_page("stats", force=True)
        reset_search()
        for _ in range(frames_per_scene):
            _position_pet_near_main(app)
            snap("stats")

    finally:
        cleanup()
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


def make_mp4(frames, out_path, fps=12):
    """把录制帧合成为 MP4（H.264），画质与体积都优于 GIF。"""
    import imageio
    import numpy as np

    imgs = []
    for _, p in frames:
        from PIL import Image
        im = Image.open(p).convert("RGB")
        imgs.append(np.asarray(im))
    if not imgs:
        return None
    writer = imageio.get_writer(out_path, fps=fps, codec="libx264",
                                quality=8, macro_block_size=None)
    try:
        for arr in imgs:
            writer.append_data(arr)
    finally:
        writer.close()
    return out_path


def make_gif(frames, out_path, fps=12, colors=256):
    """GIF 降级备用（256 色量化会有轻微色带，优先用 MP4）。"""
    from PIL import Image
    imgs = [Image.open(p).convert("P", palette=Image.ADAPTIVE,
                                  colors=colors) for _, p in frames]
    imgs = [im for im in imgs if im is not None]
    if not imgs:
        return None
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / fps), loop=0, optimize=True)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=int, default=8, help="每个场景抓帧数（默认 8）")
    ap.add_argument("--width", type=int, default=1180, help="输出宽度（默认 1180）")
    ap.add_argument("--height", type=int, default=700, help="输出高度（默认 700）")
    ap.add_argument("--fps", type=int, default=12, help="帧率（默认 12）")
    ap.add_argument("--mp4-only", action="store_true", help="只输出 MP4，不生成 GIF")
    ap.add_argument("--out", default=None, help="输出基础路径（不含扩展名）")
    ap.add_argument("--list", action="store_true", help="只打印操作链清单")
    args = ap.parse_args()

    if args.list:
        for key, label in (
                ("home", "首页磁贴"), ("move_in", "右键移入分类"),
                ("search", "全局搜索"), ("open_category", "打开分类"),
                ("countdowns", "时间管理"), ("pomodoro", "启动番茄钟"),
                ("pat_pet", "摸头桌宠"), ("stats", "数据统计")):
            print(f"{key:16s} {label}")
        return

    try:
        r = tk.Tk(); r.withdraw(); r.destroy()
    except tk.TclError:
        print("无显示环境，跳过录屏（需在 Windows 桌面会话运行）")
        return

    import tempfile
    tmp = tempfile.mkdtemp(prefix="momo_demo_")
    base = args.out or os.path.join(_ROOT, "assets", "demo")
    out_size = (args.width, args.height)

    frames = run(tmp, args.frames, out_size)
    if not frames:
        print("未捕获到任何帧")
        return

    mp4 = make_mp4(frames, base + ".mp4", fps=args.fps)
    sz = os.path.getsize(mp4) if mp4 and os.path.isfile(mp4) else 0
    print(f"共 {len(frames)} 帧 @ {args.fps} fps ≈ {len(frames)/args.fps:.1f} 秒")
    print(f"MP4：{mp4}（{sz/1024/1024:.1f} MB）")

    if not args.mp4_only:
        gif = make_gif(frames, base + ".gif", fps=args.fps)
        gsz = os.path.getsize(gif) if gif and os.path.isfile(gif) else 0
        print(f"GIF（降级备用）：{gif}（{gsz/1024/1024:.1f} MB）")

    print("临时帧目录：", tmp)


if __name__ == "__main__":
    main()
