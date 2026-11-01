# -*- coding: utf-8 -*-
"""把墨墨桌面管理助手打包成一个 Windows exe（PyInstaller）。

用法：
    python tools/build_exe.py            # 打包成单个 exe
    python tools/build_exe.py --dir      # 打包成目录（启动更快，便于排查）

说明：
    * 运行时本身零第三方依赖，PyInstaller 只是**构建期**工具，
      不会进到最终产物里，也不影响「纯标准库」的承诺。
    * 没装 PyInstaller 时会提示安装命令，不会偷偷装东西。
    * 打包结果在 dist/ 下，图标与 assets 一并打进去。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_NAME = "墨墨桌面管理助手"
ICON = os.path.join(ROOT, "assets", "momo.ico")


def have_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def build(onefile: bool = True) -> int:
    if not have_pyinstaller():
        print("[!] 没找到 PyInstaller。先安装它（只用一次，构建期依赖）：")
        print("    pip install pyinstaller")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean",
           "--name", APP_NAME,
           "--windowed",                       # 不弹黑框控制台
           "--icon", ICON,
           "--add-data", os.path.join(ROOT, "assets") + os.pathsep + "assets",
           "--hidden-import", "tkinter",
           "--collect-submodules", "core",
           "--collect-submodules", "gui",
           ]
    cmd += ["--onefile"] if onefile else ["--onedir"]
    cmd.append(os.path.join(ROOT, "main.py"))

    print("[i] 打包命令：", " ".join(cmd))
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode == 0:
        out = os.path.join(ROOT, "dist",
                           APP_NAME + ".exe" if onefile else APP_NAME)
        print("\n[✓] 完成：", out)
        print("    把它拷到任意目录双击即可运行（不需要装 Python）。")
    return res.returncode


if __name__ == "__main__":
    sys.exit(build(onefile="--dir" not in sys.argv))
