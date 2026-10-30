# -*- coding: utf-8 -*-
"""从「墨墨-睁眼笑」图生成桌宠两张表情立绘：
  - assets/momo-open.png   睁眼笑（默认形态）
  - assets/momo-happy.png  开心眯眼（点击时的形态）

处理：Shell 取原图 -> 抹掉右下角 AI 水印 -> 从边缘泛洪去米色背景 ->
边缘软化 -> 自动定位双眼 -> 复制一份把眼睛改成"⌣"眯眼笑弧线 ->
缩放到 512px 保存。
"""
import os
import sys
from collections import deque

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.icons import png_from_rgba          # noqa: E402
from make_icon import downscale               # noqa: E402
from mascot_to_ico import get_thumbnail       # noqa: E402

ASSETS = os.path.join(PROJ, "assets")
OUT_SIZE = 512


def is_background(r, g, b):
    """米色背景：高亮度低饱和。"""
    return min(r, g, b) > 200 and (max(r, g, b) - min(r, g, b)) <= 20


def flood_clear(w, h, rgba):
    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        q.extend(((0, y), (w - 1, y)))
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


def soften_edges(w, h, rgba):
    alpha = [rgba[(y * w + x) * 4 + 3] for y in range(h) for x in range(w)]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if alpha[i] == 0:
                continue
            near = ((x > 0 and alpha[i - 1] == 0) or
                    (x < w - 1 and alpha[i + 1] == 0) or
                    (y > 0 and alpha[i - w] == 0) or
                    (y < h - 1 and alpha[i + w] == 0))
            if near:
                p = i * 4
                r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
                if min(r, g, b) > 190 and (max(r, g, b) - min(r, g, b)) <= 28:
                    rgba[p + 3] = 110


def find_eyes(w, h, rgba):
    """在脸部区域用连通域找两只眼球（深色大块），返回各自 bbox。

    深色描边/斑点/嘴也会成块，因此按这些条件过滤：
    面积足够大、宽高比接近、中心 y 落在 [0.40h, 0.58h] 的"眼睛带"里。
    """
    def dark(p):
        r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
        return (r + g + b) / 3 < 95

    y0, y1 = int(h * 0.32), int(h * 0.68)
    x0, x1 = int(w * 0.20), int(w * 0.80)
    seen = bytearray(w * h)
    comps = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = y * w + x
            if seen[i] or not dark(i * 4):
                continue
            # BFS 连通域
            box = [x, y, x, y]
            area = 0
            q = deque(((x, y),))
            seen[i] = 1
            while q:
                cx, cy = q.popleft()
                area += 1
                box[0] = min(box[0], cx)
                box[2] = max(box[2], cx)
                box[1] = min(box[1], cy)
                box[3] = max(box[3], cy)
                for nx, ny in ((cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1)):
                    if x0 <= nx < x1 and y0 <= ny < y1:
                        j = ny * w + nx
                        if not seen[j] and dark(j * 4):
                            seen[j] = 1
                            q.append((nx, ny))
            comps.append((area, tuple(box)))
    bw_min = int(w * 0.06)
    cands = []
    for area, (bx0, by0, bx1, by1) in comps:
        bw, bh = bx1 - bx0, by1 - by0
        cy = (by0 + by1) / 2
        if (area > bw_min * bh * 0.5 and bw > bw_min
                and 0.55 <= bw / max(bh, 1) <= 2.2
                and 0.38 * h <= cy <= 0.60 * h):
            cands.append((area, (bx0, by0, bx1, by1)))
    cands.sort(reverse=True)
    if len(cands) < 2:
        raise SystemExit("没找到两只眼睛: " + repr([(a, b) for a, b in comps[:8]]))
    eyes = sorted([c[1] for c in cands[:2]], key=lambda b: b[0])
    return eyes


def make_happy(w, h, rgba, eyes):
    """把眼球像素替换成周围身体色（按列垂直插值，保留明暗渐变），
    再画浅而宽的"⌣"眯眼笑弧线。只动眼球像素，不伤腮红/描边。"""
    happy = bytearray(rgba)

    def is_dark(p):
        return (rgba[p] + rgba[p + 1] + rgba[p + 2]) / 3 < 110

    def is_white(p):
        return min(rgba[p], rgba[p + 1], rgba[p + 2]) > 225

    for (xmin, ymin, xmax, ymax) in eyes:
        pad = 6
        # 1) 收集眼球像素掩码：bbox 内的深色像素 + 被包住的高光白点，膨胀 2px
        mask = set()
        for y in range(max(0, ymin - pad), min(h, ymax + pad)):
            for x in range(max(0, xmin - pad), min(w, xmax + pad)):
                p = (y * w + x) * 4
                if is_dark(p) or is_white(p):
                    mask.add((x, y))
        dil = set()
        for (x, y) in mask:
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if dx * dx + dy * dy <= 5:
                        dil.add((x + dx, y + dy))
        # 2) 掩码内像素按"同列上方/下方最近的非掩码像素"做垂直插值
        cols = {}
        for (x, y) in dil:
            cols.setdefault(x, []).append(y)
        for x, ys in cols.items():
            ys.sort()
            runs, start, prev = [], ys[0], ys[0]
            for y in ys[1:]:
                if y != prev + 1:
                    runs.append((start, prev))
                    start = y
                prev = y
            runs.append((start, prev))
            for a, b in runs:
                ya, yb = a - 1, b + 1
                pa = (ya * w + x) * 4 if ya >= 0 else None
                pb = (yb * w + x) * 4 if yb < h else None
                if pa is None and pb is None:
                    continue
                ca = tuple(rgba[pa:pa + 3]) if pa is not None else \
                    tuple(rgba[pb:pb + 3])
                cb = tuple(rgba[pb:pb + 3]) if pb is not None else ca
                for y in range(a, b + 1):
                    t = (y - a) / max(1, b - a)
                    q = (y * w + x) * 4
                    happy[q] = int(ca[0] + (cb[0] - ca[0]) * t)
                    happy[q + 1] = int(ca[1] + (cb[1] - ca[1]) * t)
                    happy[q + 2] = int(ca[2] + (cb[2] - ca[2]) * t)
                    happy[q + 3] = 255
        # 3) 画浅而宽的"⌣"弧（二次贝塞尔，端点在上、中点微微下沉）
        bw, bh = xmax - xmin, ymax - ymin
        ink = tuple(rgba[((ymin + bh // 2) * w + xmin + 8) * 4:
                         ((ymin + bh // 2) * w + xmin + 8) * 4 + 3])
        x_l, x_r = xmin + int(bw * 0.04), xmax - int(bw * 0.04)
        base_y = ymin + int(bh * 0.42)
        depth = bh * 0.38
        thick = max(4, int(bh * 0.30))
        steps = bw * 2
        for s in range(steps + 1):
            t = s / steps
            bx = (1 - t) ** 2 * x_l + 2 * t * (1 - t) * ((x_l + x_r) / 2) + t ** 2 * x_r
            by = (1 - t) ** 2 * base_y + 2 * t * (1 - t) * (base_y + depth * 2) + t ** 2 * base_y
            for dy in range(-thick // 2, thick // 2 + 1):
                yy, xx = int(by) + dy, int(bx)
                if 0 <= yy < h and 0 <= xx < w:
                    q = (yy * w + xx) * 4
                    happy[q], happy[q + 1], happy[q + 2] = ink
                    happy[q + 3] = 255
    return happy


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src or not os.path.isfile(src):
        raise SystemExit("用法: python momo_faces.py <睁眼笑源图>")
    src = os.path.normpath(src)

    w, h, rgba = get_thumbnail(src)
    rgba = bytearray(rgba)
    print(f"源图: {w}x{h}")

    # 抹掉右下角 "AI生成 WORKBUDDY>" 水印（涂成背景色，泛洪时会一并清除）
    bg = tuple(rgba[(5 * w + 5) * 4:(5 * w + 5) * 4 + 3])
    wy0, wx0 = int(h * 0.90), int(w * 0.66)
    for y in range(wy0, h):
        for x in range(wx0, w):
            q = (y * w + x) * 4
            rgba[q], rgba[q + 1], rgba[q + 2] = bg

    flood_clear(w, h, rgba)
    soften_edges(w, h, rgba)

    eyes = find_eyes(w, h, rgba)
    print("左眼 bbox:", eyes[0], "| 右眼 bbox:", eyes[1])
    happy = make_happy(w, h, rgba, eyes)

    os.makedirs(ASSETS, exist_ok=True)
    for name, data in (("momo-open", rgba), ("momo-happy", happy)):
        small = downscale(data, w, OUT_SIZE)
        out = os.path.join(ASSETS, name + ".png")
        with open(out, "wb") as f:
            f.write(png_from_rgba(bytes(small), OUT_SIZE, OUT_SIZE))
        n = OUT_SIZE * OUT_SIZE
        trans = sum(1 for i in range(n) if small[i * 4 + 3] == 0)
        print(f"{out}: 透明 {trans * 100 // n}%")


if __name__ == "__main__":
    main()
