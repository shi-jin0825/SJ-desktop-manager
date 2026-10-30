# -*- coding: utf-8 -*-
"""从吉祥物图生成透明背景立绘 assets/mascot-stand.png（桌宠用）。

用法：
    D:\\Python313\\python.exe tools\\mascot_cutout.py [源图路径]

处理：Shell 缩略图取原图 -> 从边缘泛洪填充去除棋盘格/纯色背景
（不会误伤角色内部的白色高光）-> 边缘软化 -> 区域平均缩放到 96px。
"""
import ctypes
import os
import sys
from collections import deque

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.icons import png_from_rgba
from make_icon import downscale

ASSETS = os.path.join(PROJ, "assets")
OUT_PNG = os.path.join(ASSETS, "mascot-stand.png")
STAND_SIZE = 96          # 桌宠显示尺寸（px）

# 与 mascot_to_ico.py 相同的 Shell 缩略图提取
from mascot_to_ico import get_thumbnail  # noqa: E402


def is_background(r: int, g: int, b: int) -> bool:
    """棋盘格背景：高亮度低饱和（白/浅灰，暗格约 222/221/219）。"""
    return min(r, g, b) > 208 and (max(r, g, b) - min(r, g, b)) <= 16


def flood_clear(w: int, h: int, rgba) -> None:
    """从图像边缘泛洪，把连通的背景像素 alpha 置 0（原地修改）。"""
    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            q.append((x, y))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if visited[i]:
            continue
        visited[i] = 1
        p = i * 4
        if not is_background(rgba[p], rgba[p + 1], rgba[p + 2]):
            continue
        rgba[p + 3] = 0
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))


def soften_edges(w: int, h: int, rgba) -> None:
    """边缘软化：紧邻透明区的高亮像素降为半透明，减小白边。"""
    alpha = [rgba[(y * w + x) * 4 + 3] for y in range(h) for x in range(w)]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if alpha[i] == 0:
                continue
            near_transparent = (
                (x > 0 and alpha[i - 1] == 0) or (x < w - 1 and alpha[i + 1] == 0) or
                (y > 0 and alpha[i - w] == 0) or (y < h - 1 and alpha[i + w] == 0))
            if near_transparent:
                p = i * 4
                r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
                if min(r, g, b) > 195 and (max(r, g, b) - min(r, g, b)) <= 25:
                    rgba[p + 3] = 110


def main():
    args = [a for a in sys.argv[1:]]
    if args:
        src = os.path.normpath(args[0])
    else:
        src = MASCOT_SRC = os.path.join(ASSETS, "mascot-stand-src.png")
    if not os.path.isfile(src):
        raise SystemExit(f"源图不存在：{src}")

    w, h, rgba = get_thumbnail(src)
    rgba = bytearray(rgba)
    print(f"源图: {w}x{h}")
    flood_clear(w, h, rgba)
    soften_edges(w, h, rgba)
    small = downscale(rgba, w, STAND_SIZE)
    os.makedirs(ASSETS, exist_ok=True)
    with open(OUT_PNG, "wb") as f:
        f.write(png_from_rgba(bytes(small), STAND_SIZE, STAND_SIZE))
    transparent = sum(1 for i in range(STAND_SIZE * STAND_SIZE) if small[i * 4 + 3] == 0)
    print(f"已生成 {OUT_PNG}（{STAND_SIZE}px，透明像素 {transparent * 100 // (STAND_SIZE * STAND_SIZE)}%）")


if __name__ == "__main__":
    main()
