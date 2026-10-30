# -*- coding: utf-8 -*-
"""生成 SJ 桌面管理器的专属 .ico 图标。

用法：
    D:\\Python313\\python.exe tools\\make_icon.py

产出：
    assets/app-grid.ico    蓝底圆角面板 + 3×3 真实应用图标（推荐，与 App 界面一致）
    assets/app-folder.ico  系统原生文件夹图标

ICO 内嵌多个尺寸（256/64/48/32/16），保证在任务栏、小图标视图下都清晰。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.icons import icon_rgba, png_from_rgba
from core.scanner import scan_desktop

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SIZES = (256, 64, 48, 32, 16)

# 面板配色（与 App 的蓝灰风格呼应）
BG_TOP = (108, 158, 245)      # 顶部亮蓝
BG_BOTTOM = (46, 95, 179)     # 底部深蓝


def rounded_square(size: int, top, bottom, radius_ratio: float = 0.24) -> bytearray:
    """画一个竖向渐变的圆角方块，返回 RGBA 像素。"""
    buf = bytearray(size * size * 4)
    r = int(size * radius_ratio)
    for y in range(size):
        t = y / max(size - 1, 1)
        cr = int(top[0] + (bottom[0] - top[0]) * t)
        cg = int(top[1] + (bottom[1] - top[1]) * t)
        cb = int(top[2] + (bottom[2] - top[2]) * t)
        row = y * size * 4
        cy = min(max(y + 0.5, r), size - r)
        dy = y + 0.5 - cy
        for x in range(size):
            cx = min(max(x + 0.5, r), size - r)
            dx = x + 0.5 - cx
            if dx * dx + dy * dy <= r * r:
                i = row + x * 4
                buf[i:i + 4] = bytes((cr, cg, cb, 255))
    return buf


def blend(dst: bytearray, dsize: int, src, sw: int, sh: int, dx: int, dy: int, target: int):
    """把 src（RGBA）按最近邻缩放到 target 后，以 src-over 方式合成到 dst 上。"""
    for ty in range(target):
        sy = min(sh - 1, ty * sh // target)
        srow = sy * sw * 4
        drow = (dy + ty) * dsize * 4
        for tx in range(target):
            sx = min(sw - 1, tx * sw // target)
            si = srow + sx * 4
            sa = src[si + 3]
            if not sa:
                continue
            di = drow + (dx + tx) * 4
            if sa == 255:
                dst[di:di + 4] = src[si:si + 4]
            else:
                a = sa / 255.0
                ia = 1.0 - a
                for k in range(3):
                    v = src[si + k] * a + dst[di + k] * ia
                    dst[di + k] = 255 if v > 255 else int(v)
                dst[di + 3] = max(dst[di + 3], sa)


def downscale(buf, size: int, new_size: int) -> bytearray:
    """RGBA 像素的区域平均降采样。"""
    if new_size >= size:
        return buf
    f = size / new_size
    out = bytearray(new_size * new_size * 4)
    for y in range(new_size):
        y0 = int(y * f)
        y1 = max(y0 + 1, min(size, int((y + 1) * f)))
        for x in range(new_size):
            x0 = int(x * f)
            x1 = max(x0 + 1, min(size, int((x + 1) * f)))
            r = g = b = a = n = 0
            for yy in range(y0, y1):
                base = yy * size * 4
                for xx in range(x0, x1):
                    i = base + xx * 4
                    r += buf[i]; g += buf[i + 1]; b += buf[i + 2]; a += buf[i + 3]
                    n += 1
            o = (y * new_size + x) * 4
            out[o:o + 4] = bytes((r // n, g // n, b // n, a // n))
    return out


def render_grid(size: int, icons) -> bytearray:
    """主设计：圆角蓝底 + 3×3 真实应用图标。"""
    canvas = rounded_square(size, BG_TOP, BG_BOTTOM)
    n = 3
    margin = int(size * 0.14)
    gap = max(1, int(size * 0.04))
    cell = (size - 2 * margin - (n - 1) * gap) // n
    if cell < 4 or not icons:
        return canvas
    for i, rgba in enumerate(icons[:n * n]):
        if not rgba:
            continue
        row, col = divmod(i, n)
        blend(canvas, size, rgba[2], rgba[0], rgba[1],
              margin + col * (cell + gap), margin + row * (cell + gap), cell)
    return canvas


def collect_icons(cell: int, count: int = 9):
    """取桌面前若干个项目的真实图标（按目标尺寸请求，由 Shell 缩放）。"""
    out = []
    for item in scan_desktop()[:count]:
        try:
            out.append(icon_rgba(item.path, cell))
        except Exception:
            out.append(None)
    return out


def write_ico(path: str, images):
    """把 [(size, rgba_pixels), ...] 写成多尺寸 ICO（内嵌 PNG，Vista+ 支持）。"""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, rgba in images:
        png = png_from_rgba(bytes(rgba), size, size)
        b = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + data)


def build_grid_ico(path: str):
    big, mid = 256, 64
    # 256 与 64 各自原尺寸渲染（缩略图标按对应尺寸重新请求，质量最好）
    frames = {big: render_grid(big, collect_icons(cell_size(big))),
              mid: render_grid(mid, collect_icons(cell_size(mid)))}
    # 更小尺寸由 64 降采样得到
    for s in (48, 32, 16):
        frames[s] = downscale(frames[mid], mid, s)
    write_ico(path, [(s, frames[s]) for s in SIZES])
    return len(SIZES)


def cell_size(size: int) -> int:
    """3×3 网格下单个小图标的边长。"""
    margin = int(size * 0.14)
    gap = max(1, int(size * 0.04))
    return (size - 2 * margin - 2 * gap) // 3


def build_folder_ico(path: str):
    got = icon_rgba(os.path.expanduser("~"), 256)
    if not got:
        return 0
    w, h, base = got
    if w != h:
        return 0
    frames = {}
    for s in SIZES:
        frames[s] = base if s == w else downscale(base, w, s)
    write_ico(path, [(s, frames[s]) for s in SIZES])
    return len(SIZES)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    grid = os.path.join(OUT_DIR, "app-grid.ico")
    folder = os.path.join(OUT_DIR, "app-folder.ico")
    n1 = build_grid_ico(grid)
    n2 = build_folder_ico(folder)
    print("生成完成：")
    print("  ", grid, f"({n1} 个尺寸, {os.path.getsize(grid)} 字节)")
    if n2:
        print("  ", folder, f"({n2} 个尺寸, {os.path.getsize(folder)} 字节)")


if __name__ == "__main__":
    main()
