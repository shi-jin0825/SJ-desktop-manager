# -*- coding: utf-8 -*-
"""从「墨墨-睁眼笑」原图程序化生成桌宠的各状态立绘（纯标准库）。

生成到 assets/ 下：
  momo-shy.png    害羞（眯眼笑 + 腮红）        —— 摸头/点击反馈
  momo-hot.png    好热（汗滴 + 吐舌 + 脸红）    —— CPU 占用过高
  momo-tired.png  疲惫（半闭眼 + 黑眼圈 + 汗）  —— 内存吃紧
  momo-study.png  学习（身前摊开一本书）        —— 番茄钟伴学
  momo-run.png    奔跑（左右速度线）            —— 网速飞快

画法全部基于像素运算：先定位双眼连通域，再在已知位置叠加几何图形，
不做任何外部依赖（同 tools/momo_faces.py 的思路）。

用法： python tools/momo_states.py
"""
import os
import sys
from collections import deque

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from core.icons import png_from_rgba          # noqa: E402
from gui.pet import decode_png                # noqa: E402

ASSETS = os.path.join(PROJ, "assets")
SRC = os.path.join(ASSETS, "momo-open.png")


# --------------------------------------------------------------- 基础工具
def find_eyes(w, h, rgba):
    """找两只眼球（深色大块连通域），返回左、右的 bbox。"""
    def dark(p):
        return (rgba[p] + rgba[p + 1] + rgba[p + 2]) / 3 < 95

    y0, y1 = int(h * 0.32), int(h * 0.68)
    x0, x1 = int(w * 0.20), int(w * 0.80)
    seen = bytearray(w * h)
    comps = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = y * w + x
            if seen[i] or not dark(i * 4):
                continue
            box = [x, y, x, y]
            area = 0
            q = deque(((x, y),))
            seen[i] = 1
            while q:
                cx, cy = q.popleft()
                area += 1
                box[0] = min(box[0], cx); box[2] = max(box[2], cx)
                box[1] = min(box[1], cy); box[3] = max(box[3], cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if x0 <= nx < x1 and y0 <= ny < y1:
                        j = ny * w + nx
                        if not seen[j] and dark(j * 4):
                            seen[j] = 1
                            q.append((nx, ny))
            bw, bh = box[2] - box[0], box[3] - box[1]
            cy = (box[1] + box[3]) / 2
            if (area > w * 0.03 * bh * 0.4 and bw > w * 0.04
                    and 0.35 * h <= cy <= 0.62 * h):
                comps.append((area, tuple(box)))
    comps.sort(reverse=True)
    if len(comps) < 2:
        raise SystemExit("没找到两只眼睛")
    return sorted([c[1] for c in comps[:2]], key=lambda b: b[0])


def blend(rgba, w, h, x, y, color, alpha, inside_only=False):
    """在 (x, y) 叠一个像素；alpha 0~255。"""
    if not (0 <= x < w and 0 <= y < h):
        return
    p = (y * w + x) * 4
    if inside_only and rgba[p + 3] < 40:
        return
    a = alpha / 255.0
    for c in range(3):
        rgba[p + c] = int(rgba[p + c] * (1 - a) + color[c] * a)
    rgba[p + 3] = max(rgba[p + 3], int(alpha if not inside_only else 255 * a))


def ellipse(rgba, w, h, cx, cy, rx, ry, color, alpha, inside_only=True):
    """填充椭圆（可带旋转外的简单轴对齐）。"""
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            d = dx * dx + dy * dy
            if d <= 1.0:
                # 边缘 1 像素做羽化
                k = alpha if d <= 0.75 else alpha * (1.0 - (d - 0.75) / 0.25)
                blend(rgba, w, h, x, y, color, int(k), inside_only)


def ring(rgba, w, h, cx, cy, rx, ry, color, alpha, thick=3):
    """椭圆描边。"""
    steps = max(60, int(max(rx, ry) * 8))
    import math
    for s in range(steps + 1):
        t = 2 * math.pi * s / steps
        for k in range(thick):
            f = 1.0 - k * 0.06
            x = int(cx + rx * f * math.cos(t))
            y = int(cy + ry * f * math.sin(t))
            blend(rgba, w, h, x, y, color, alpha, inside_only=True)


def drop(rgba, w, h, cx, cy, size, color, edge):
    """画一滴汗：下方圆 + 上方尖角。"""
    import math
    r = size / 2.0
    # 圆身
    for y in range(int(cy - r), int(cy + r * 1.15) + 1):
        for x in range(int(cx - r) - 1, int(cx + r) + 2):
            dx = (x - cx) / r
            dy = (y - cy) / (r * 1.05)
            if dx * dx + dy * dy <= 1.0:
                blend(rgba, w, h, x, y, color, 255)
    # 尖角（水滴顶）
    for i in range(int(r * 1.35)):
        t = i / (r * 1.35)
        half = r * (1 - t) * 0.95
        y = int(cy - r - i)
        for x in range(int(cx - half), int(cx + half) + 1):
            blend(rgba, w, h, x, y, color, 255)
    # 高光 + 描边
    ring(rgba, w, h, cx, cy + r * 0.1, r * 0.98, r * 1.0, edge, 150, thick=2)
    ellipse(rgba, w, h, cx - r * 0.3, cy - r * 0.2, r * 0.22, r * 0.16,
            (255, 255, 255), 170, inside_only=False)


def blush(rgba, w, h, eyes, alpha=110):
    """两颊腮红（眼睛下方偏外）。"""
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = eyes
    color = (255, 138, 160)
    cy = (ly1 + ry1) / 2 + (ly1 - ly0) * 0.55
    rr = (lx1 - lx0) * 0.62
    for cx in (lx0 - (lx1 - lx0) * 0.08, rx1 + (rx1 - rx0) * 0.08):
        ellipse(rgba, w, h, cx, cy, rr, rr * 0.55, color, alpha)


def save(name, w, h, rgba):
    path = os.path.join(ASSETS, name)
    with open(path, "wb") as f:
        f.write(png_from_rgba(bytes(rgba), w, h))
    print("  ->", name)


# --------------------------------------------------------------- 各状态
def make_shy(w, h, rgba, eyes):
    """害羞：眯眼笑（来自 momo-happy 的弧线思路）+ 加重腮红。"""
    out = bytearray(rgba)
    # 用 happy 图的弧线：直接改眼为向下弯的浅弧（同 momo_faces.make_happy 简化版）
    for (x0, y0, x1, y1) in eyes:
        bw, bh = x1 - x0, y1 - y0
        ink = (40, 60, 78)
        x_l, x_r = x0 + bw * 0.06, x1 - bw * 0.06
        base_y = y0 + bh * 0.34
        depth = bh * 0.40
        thick = max(4, int(bh * 0.26))
        steps = int(bw * 2)
        # 先把眼球区域用身体色填掉
        body = (166, 227, 210)
        for y in range(y0 - 4, y1 + 6):
            for x in range(x0 - 4, x1 + 5):
                p = (y * w + x) * 4
                r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
                if (r + g + b) / 3 < 130 or min(r, g, b) > 220:
                    out[p], out[p + 1], out[p + 2] = body
                    out[p + 3] = 255
        for s in range(steps + 1):
            t = s / steps
            bx = (1 - t) ** 2 * x_l + 2 * t * (1 - t) * ((x_l + x_r) / 2) + t ** 2 * x_r
            by = (1 - t) ** 2 * base_y + 2 * t * (1 - t) * (base_y + depth * 2) + t ** 2 * base_y
            for dy in range(-thick // 2, thick // 2 + 1):
                blend(out, w, h, int(bx), int(by) + dy, ink, 255, inside_only=False)
    blush(out, w, h, eyes, alpha=150)
    return out


def make_hot(w, h, rgba, eyes):
    """好热：头顶两滴汗 + 吐舌头 + 脸红。"""
    out = bytearray(rgba)
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = eyes
    eye_h = ly1 - ly0
    # 汗滴：头顶两侧
    drop(out, w, h, lx0 - eye_h * 0.25, ly0 - eye_h * 1.35, eye_h * 0.85,
         (120, 200, 245), (70, 140, 200))
    drop(out, w, h, rx1 + eye_h * 0.45, ry0 - eye_h * 1.75, eye_h * 0.62,
         (120, 200, 245), (70, 140, 200))
    # 吐舌头：嘴（两眼中间偏下）下方伸出一小截
    mx = (lx1 + rx0) / 2
    my = (ly1 + ry1) / 2 + eye_h * 0.35
    tw, th = eye_h * 0.62, eye_h * 0.46
    ellipse(out, w, h, mx, my + th * 0.35, tw, th, (245, 130, 150), 255,
            inside_only=False)
    # 舌头中缝
    for i in range(int(th * 0.9)):
        blend(out, w, h, int(mx), int(my + th * 0.1 + i), (200, 95, 115), 220,
              inside_only=False)
    blush(out, w, h, eyes, alpha=140)
    return out


def make_tired(w, h, rgba, eyes):
    """疲惫：上眼皮下垂遮住眼睛上半 + 黑眼圈 + 一滴汗 + 喘息。"""
    out = bytearray(rgba)
    body = (166, 227, 210)
    for (x0, y0, x1, y1) in eyes:
        bh = y1 - y0
        cut = y0 + bh * 0.52          # 遮住上半
        for y in range(y0 - 3, int(cut) + 1):
            for x in range(x0 - 3, x1 + 4):
                p = (y * w + x) * 4
                r, g, b = rgba[p], rgba[p + 1], rgba[p + 2]
                if (r + g + b) / 3 < 130 or min(r, g, b) > 220:
                    out[p], out[p + 1], out[p + 2] = body
                    out[p + 3] = 255
        # 眼皮线
        for x in range(x0 - 2, x1 + 3):
            for dy in (0, 1, 2):
                blend(out, w, h, x, int(cut) + dy, (52, 78, 92), 235,
                      inside_only=False)
        # 黑眼圈（眼下淡淡的阴影）
        ellipse(out, w, h, (x0 + x1) / 2, y1 + bh * 0.42,
                (x1 - x0) * 0.62, bh * 0.20, (120, 150, 165), 90)
    (lx0, ly0, lx1, ly1), (_rx0, ry0, _rx1, _ry1) = eyes
    eye_h = ly1 - ly0
    drop(out, w, h, lx1 + eye_h * 0.5, ly0 - eye_h * 1.5, eye_h * 0.55,
         (130, 205, 245), (75, 145, 200))
    return out


def make_study(w, h, rgba, eyes):
    """学习：身前摊开一本书（两页 + 中缝 + 文字线），眼神保持专注。"""
    out = bytearray(rgba)
    (lx0, ly0, lx1, ly1), (rx0, _ry0, rx1, _ry1) = eyes
    eye_h = ly1 - ly0
    cy = (ly1 + ry1 if False else ly1) + eye_h * 2.35     # 书的上沿
    bw = (rx1 - lx0) * 1.55
    cx = (lx0 + rx1) / 2
    page_h = bw * 0.30
    # 书本外框（略带阴影）
    for i in range(2):
        off = 6 - i * 6
        col = (90, 130, 140) if i == 0 else (40, 60, 70)
        for y in range(int(cy + off), int(cy + page_h + off)):
            for x in range(int(cx - bw / 2 + off), int(cx + bw / 2 + off)):
                on_edge = (abs(x - (cx - bw / 2 + off)) <= 4 or
                           abs(x - (cx + bw / 2 + off)) <= 4 or
                           abs(y - (cy + off)) <= 4 or
                           abs(y - (cy + page_h + off)) <= 4)
                if on_edge:
                    blend(out, w, h, x, y, col, 255, inside_only=False)
    # 书页
    for y in range(int(cy + 5), int(cy + page_h - 3)):
        for x in range(int(cx - bw / 2 + 5), int(cx + bw / 2 - 4)):
            if abs(x - cx) <= 3:
                continue
            shade = 250 if ((x + y) // 7) % 2 == 0 else 240
            blend(out, w, h, x, y, (shade, shade, 250), 255, inside_only=False)
    # 中缝
    for y in range(int(cy + 4), int(cy + page_h - 2)):
        for x in range(int(cx - 3), int(cx + 4)):
            blend(out, w, h, x, y, (150, 160, 170), 255, inside_only=False)
    # 页面文字线
    line_y = int(cy + page_h * 0.42)
    for k in range(3):
        yy = line_y + k * int(page_h * 0.16)
        for x in range(int(cx - bw * 0.40), int(cx - bw * 0.08)):
            blend(out, w, h, x, yy, (175, 180, 190), 255, inside_only=False)
        for x in range(int(cx + bw * 0.08), int(cx + bw * 0.40)):
            blend(out, w, h, x, yy, (175, 180, 190), 255, inside_only=False)
    return out


def make_run(w, h, rgba, eyes):
    """奔跑：左右两侧的速度线 + 微微前倾的动感。"""
    out = bytearray(rgba)
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = eyes
    eye_h = ly1 - ly0
    color = (110, 170, 165)
    # 左侧速度线
    for k in range(3):
        y = ly0 + eye_h * (0.15 + k * 0.75)
        length = eye_h * (1.5 - k * 0.25)
        for i in range(int(length)):
            for dy in (0, 1, 2):
                blend(out, w, h, int(lx0 - eye_h * 0.45 - i), int(y + dy),
                      color, 220 - i * 2, inside_only=False)
    # 右侧速度线
    for k in range(3):
        y = ry0 + eye_h * (0.15 + k * 0.75)
        length = eye_h * (1.5 - k * 0.25)
        for i in range(int(length)):
            for dy in (0, 1, 2):
                blend(out, w, h, int(rx1 + eye_h * 0.45 + i), int(y + dy),
                      color, 220 - i * 2, inside_only=False)
    return out


def main():
    dec = decode_png(SRC)
    if not dec:
        raise SystemExit("读不到 " + SRC)
    w, h, rgba = dec
    eyes = find_eyes(w, h, rgba)
    print("眼睛:", eyes)

    save("momo-shy.png", w, h, make_shy(w, h, rgba, eyes))
    save("momo-hot.png", w, h, make_hot(w, h, rgba, eyes))
    save("momo-tired.png", w, h, make_tired(w, h, rgba, eyes))
    save("momo-study.png", w, h, make_study(w, h, rgba, eyes))
    save("momo-run.png", w, h, make_run(w, h, rgba, eyes))
    print("完成")


if __name__ == "__main__":
    main()
