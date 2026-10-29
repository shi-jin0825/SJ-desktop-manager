# SJ-desktop-manager

一款用 Python（tkinter）编写的 Windows 桌面管理器，把桌面变成"手机桌面"：
扫描桌面上的文件、文件夹和快捷方式，按你自定义的分类归入"文件夹"，清晰一目了然。

## 功能

- 🔄 自动扫描桌面（含公共桌面）上的文件 / 文件夹 / `.lnk` / `.url` 快捷方式
- 📁 自由新建 / 删除分类（如：工具、办公、娱乐），分类以文件夹样式置顶展示
- 🖱 双击即打开对应文件或程序；右键可将任意项目移入 / 移出分类
- 💾 分类与分配关系保存在 `config.json`，不会移动或改动桌面上的真实文件
- ⌨️ F5 刷新

## 运行

```bash
python main.py
```

仅使用 Python 标准库（tkinter），**无需安装任何第三方依赖**。要求 Python 3.8+。

## 项目结构

```
SJ-desktop-manager/
├── main.py            # 启动入口
├── core/
│   ├── scanner.py     # 桌面项扫描
│   └── config.py      # 分类配置持久化（config.json）
├── gui/
│   └── app.py         # 手机桌面式 GUI（tkinter）
└── config.json        # 首次运行自动生成
```

## Roadmap

- [ ] 拖拽分配项目到分类
- [ ] 提取快捷方式真实图标
- [ ] 多页面（分页滑动）
- [ ] 开机自启动

## License

MIT
