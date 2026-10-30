# 墨墨桌面管理助手（SJ-desktop-manager）

一款用 Python（tkinter）编写的 Windows 桌面管理器，把桌面变成"手机桌面"：
扫描桌面上的文件、文件夹和快捷方式，按你自定义的分类归入"文件夹"，清晰一目了然。

![截图](assets/screenshot.png)

## 功能

- 🔄 自动扫描桌面（含公共桌面）上的文件 / 文件夹 / `.lnk` / `.url` 快捷方式
- 🖼 **显示每个项目的系统真实图标**（而非统一的文件 emoji）——通过 Windows Shell 的
  `IShellItemImageFactory` 接口提取 48×48 带 alpha 通道的真彩图标，能正确解析
  Steam / UWP 类快捷方式的目标程序图标；提取失败时回退 `SHGetFileInfoW`，再回退 emoji
- 📁 **手机文件夹式分类磁贴**：分类磁贴内部按 3×3 预览该分类前 9 个项目的真实小图标，
  不打开文件夹就能看清里面放了什么；空分类显示提示，悬停高亮，圆角面板样式
- 🖱 双击即打开对应文件或程序；右键可将任意项目移入 / 移出分类
- 💾 分类与分配关系保存在 `config.json`，不会移动或改动桌面上的真实文件
- ⌨️ F5 刷新
- 🐙 **桌面悬浮宠物**：工具栏「🐙 桌面宠物」可召唤墨墨悬浮在桌面上
  （无边框、背景完全透明、鼠标穿透、像在水里一样上下浮动），右键可切换
  完全穿透 / 浮动速度 / 收起；尺寸与浮动参数在 `gui/pet.py` 顶部可调
- 🧹 自动过滤 `desktop.ini` 等隐藏 / 系统文件，不会混进网格

整个程序**只依赖 Python 标准库**（tkinter + ctypes 调用 Win32/COM），
包括图标提取和 PNG 编码都是纯标准库实现，无任何第三方依赖。

## 运行

双击 `run.bat`（内部用 `pythonw.exe` 启动，**不会弹出命令行黑框**），或：

```bash
python main.py
```

要求 Windows 10+ 与 Python 3.8+。首次运行会在项目根目录生成 `config.json`。

## 专属图标与快捷方式

当前应用图标 `assets/momo.ico` 来自吉祥物「墨墨」（墨绿色小章鱼，见 `assets/mascot.png`），
由 `tools/mascot_to_ico.py` 生成（自动裁边去水印、四角圆角透明，内嵌 256/64/48/32/16
五个尺寸，纯 Python 标准库实现）。另保留备选图标 `assets/app-grid.ico`
（`tools/make_icon.py` 合成的蓝色圆角底 + 3×3 真实应用图标样式）。

`tools/make_shortcut.py` 可以一键在桌面创建指向本程序的快捷方式并应用图标
（通过 ctypes 直接调用 `IShellLinkW` + `IPersistFile` COM 接口，同样零依赖），
旧名快捷方式会被自动重命名：

```bash
python tools/mascot_to_ico.py   # 从吉祥物图生成 assets/momo.ico
python tools/make_icon.py       # 重新生成备选图标 assets/app-grid.ico
python tools/make_shortcut.py   # 在桌面创建/更新快捷方式
```

## 项目结构

```
SJ-desktop-manager/
├── main.py                # 启动入口
├── run.bat                # 一键启动（pythonw，无黑框）
├── core/
│   ├── scanner.py         # 桌面项扫描（过滤隐藏/系统文件）
│   ├── config.py          # 分类配置持久化（config.json）
│   └── icons.py           # 系统图标提取（Shell COM + 纯标准库 PNG 编码）
├── gui/
│   ├── app.py             # 手机桌面式 GUI（tkinter）
│   └── pet.py             # 桌面悬浮宠物（无边框/透明/穿透/浮动）
├── tools/
│   ├── make_icon.py       # 合成备选 .ico 图标（3×3 应用网格样式）
│   ├── mascot_to_ico.py   # 吉祥物图 -> 应用 .ico
│   └── make_shortcut.py   # 创建/更新桌面快捷方式
├── assets/                # 图标、吉祥物图与截图
└── config.json            # 首次运行自动生成
```

## 更新日志

### v0.4 — 桌面悬浮宠物

- **桌面悬浮宠物**（新增 `gui/pet.py`）：工具栏「🐙 桌面宠物」可召唤墨墨到桌面独立悬浮，
  无边框 + 背景完全透明（`-transparentcolor`），透明区域自动鼠标穿透不挡点击，
  并用 `after()` + 正弦曲线做上下浮动动画
- **消除透明边缘紫边**：自写 PNG 解码取真实 alpha（Tk 只给布尔），
  经去边（defringe）+ Bayer 抖动二值化，边缘干净无 halo
- **完全穿透模式**：右键菜单可切 `WS_EX_TRANSPARENT`，连章鱼本体也不挡点击
- 宠物尺寸 100px，参数集中在 `gui/pet.py` 顶部（尺寸 / 幅度 / 周期 / 帧率）

### v0.3 — 品牌焕新

- **应用图标**：墨绿色小章鱼吉祥物「墨墨」成为官方图标（多尺寸 `.ico`，
  自动去水印、圆角透明处理）
- **桌宠助手**：墨墨以透明立绘形式住在主界面右下角，可随意拖动，
  单击冒语录气泡（`tools/mascot_cutout.py` 从原图去除棋盘格背景生成）
- **更名**：软件正式定名「墨墨桌面管理助手」

### v0.2 — 界面与体验优化

- **真实图标**：所有磁贴显示系统真实图标（`IShellItemImageFactory` 优先，
  `SHGetFileInfoW` 兜底），彻底告别"全靠 emoji 分辨"
- **文件夹预览磁贴**：分类磁贴内 3×3 预览分类内容的小图标，还原手机桌面文件夹体验
- **一键启动**：新增 `run.bat`，`pythonw` 启动全程无命令行黑框
- **专属应用图标**：纯 Python 合成多尺寸 `.ico`，并附一键创建桌面快捷方式的工具
- **修复**：分类窗口右键"移出分类"崩溃（缺失方法）；图标红蓝通道反色；
  隐藏/系统文件混入网格；长文件名截断改用省略号

### v0.1 — 初始版本

- 桌面扫描、分类管理、双击打开、F5 刷新

## Roadmap

- [ ] 拖拽分配项目到分类
- [x] 提取快捷方式真实图标
- [ ] 多页面（分页滑动）
- [ ] 开机自启动

## License

MIT
