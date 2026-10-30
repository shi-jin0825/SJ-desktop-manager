# -*- coding: utf-8 -*-
"""从吉祥物图片生成应用图标 assets/momo.ico（多尺寸）。

用法：
    D:\\Python313\\python.exe tools\\mascot_to_ico.py [源图路径] [--crop-bottom 百分比]

说明：
    - 源图（JPG/PNG 等）通过 Shell IShellItemImageFactory 提取内容缩略图
      （零第三方依赖）；
    - 首次运行会裁掉底部水印（--crop-bottom，默认 0）、四角转圆角透明，
      并把处理结果存为 assets/mascot.png；
    - 之后重跑默认读 mascot.png 直接生成 assets/momo.ico
      （256/64/48/32/16 五个尺寸）。
"""
import ctypes
import math
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.icons import (_IID_IShellItemImageFactory, _SIZE, _SHCreateItemFromParsingName,
                        _bgra_to_rgba, _bitmap_bgra, _ensure_com, _gdi32,
                        png_from_rgba)
from make_icon import SIZES, downscale, write_ico

ASSETS = os.path.join(PROJ, "assets")
MASCOT_PNG = os.path.join(ASSETS, "mascot.png")
OUT_ICO = os.path.join(ASSETS, "momo.ico")

SIIGBF_BIGGERSIZEOK = 0x1
THUMB_REQ = 1024          # 向 Shell 请求的尺寸
CROP_BOTTOM_DEFAULT = 0.0
CORNER_RADIUS_RATIO = 0.22   # 圆角半径（相对边长）


def get_thumbnail(path: str, size: int = THUMB_REQ):
    """图片文件 -> (w, h, RGBA)，取内容缩略图（不是文件类型图标）。"""
    _ensure_com()
    p = ctypes.c_void_p()
    hr = _SHCreateItemFromParsingName(str(path), None,
                                      ctypes.byref(_IID_IShellItemImageFactory),
                                      ctypes.byref(p))
    if hr != 0 or not p.value:
        raise OSError(f"CreateItem 失败: 0x{hr & 0xFFFFFFFF:08X}")
    vtbl = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p)).contents,
                       ctypes.POINTER(ctypes.c_void_p))
    try:
        GetImage = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, _SIZE,
                                      ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(vtbl[3])
        hbmp = ctypes.c_void_p()
        hr = GetImage(p, _SIZE(size, size), SIIGBF_BIGGERSIZEOK, ctypes.byref(hbmp))
        if hr != 0 or not hbmp.value:
            raise OSError(f"GetImage 失败: 0x{hr & 0xFFFFFFFF:08X}")
        try:
            w, h, bgra = _bitmap_bgra(hbmp)
            return w, h, _bgra_to_rgba(bgra)
        finally:
            _gdi32.DeleteObject(hbmp)
    finally:
        Release = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[2])
        Release(p)


def crop_square(w: int, h: int, rgba, crop_bottom: float):
    """裁掉底部 crop_bottom 比例后居中取正方形。"""
    keep_h = min(h, int(h * (1 - crop_bottom)))
    side = min(w, keep_h)
    x0, y0 = (w - side) // 2, (keep_h - side) // 2
    out = bytearray(side * side * 4)
    for row in range(side):
        src = ((y0 + row) * w + x0) * 4
        dst = row * side * 4
        out[dst:dst + side * 4] = rgba[src:src + side * 4]
    return side, out


def round_corners(rgba, side: int, radius_ratio: float = CORNER_RADIUS_RATIO):
    """圆角矩形外的像素置为透明（近似抗锯齿：边缘 1px 渐变）。"""
    r = side * radius_ratio
    lim = side - r   # 圆角圆心位于 (lim, lim) 等四处
    for y in range(side):
        for x in range(side):
            # 只处理四个角部方块区域
            cx = lim if x >= lim else (r if x < r else None)
            cy = lim if y >= lim else (r if y < r else None)
            if cx is None or cy is None:
                continue
            d = math.hypot(x - cx, y - cy)
            if d > r + 0.5:
                rgba[(y * side + x) * 4 + 3] = 0
            elif d > r - 0.5:   # 边缘过渡
                a = max(0.0, min(1.0, (r + 0.5 - d)))
                i = (y * side + x) * 4 + 3
                rgba[i] = int(rgba[i] * a)
    return rgba


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    crop_bottom = CROP_BOTTOM_DEFAULT
    for a in sys.argv[1:]:
        if a.startswith("--crop-bottom="):
            crop_bottom = float(a.split("=", 1)[1]) / 100.0
        elif a == "--crop-bottom":
            crop_bottom = 0.08

    os.makedirs(ASSETS, exist_ok=True)

    if args:
        src = os.path.normpath(args[0])   # 兼容 MSYS/bash 传来的正斜杠路径
        if not os.path.isfile(src):
            raise SystemExit(f"源图不存在：{src}")
        if crop_bottom or not os.path.isfile(MASCOT_PNG):
            w, h, rgba = get_thumbnail(src)
            side, sq = crop_square(w, h, rgba, crop_bottom)
            sq = round_corners(sq, side)
            with open(MASCOT_PNG, "wb") as fp:
                fp.write(png_from_rgba(bytes(sq), side, side))
            print(f"已保存 {MASCOT_PNG}（{side}x{side}，源 {w}x{h}，"
                  f"裁底部 {crop_bottom * 100:.0f}%，圆角透明）")

    if not os.path.isfile(MASCOT_PNG):
        raise SystemExit("缺少 assets/mascot.png，请先传入源图路径")

    w, h, rgba = get_thumbnail(MASCOT_PNG)
    if w != h:
        w, rgba = crop_square(w, h, rgba, 0.0)
    frames = [(s, rgba if s == w else downscale(rgba, w, s)) for s in SIZES]
    write_ico(OUT_ICO, frames)
    print(f"已生成 {OUT_ICO}（{len(frames)} 个尺寸，{os.path.getsize(OUT_ICO)} 字节）")


if __name__ == "__main__":
    main()
