# 千寻图片查看器 QianXun Viewer

![logo](assets/logo.png)

> 面向大规模本地图片库（千张级、单张 10~60MB）的高性能桌面查看器。
> 缩略图优先 · 全程异步 · 无损操作。

`版本 v1.2.0` · `平台 Windows 10/11 x64` · `Python 3.11+ / PySide6` · `版权所有 © 羡林i (Y_XianLin)`

---

## 项目简介

千寻图片查看器是一款为"大量、超大"本地图片浏览而设计的桌面程序。它绝不在网格中解码原图，一律走两档落盘缩略图缓存；原图仅在进入大图浏览器时按需解码并降采样保护。目录扫描、缩略图生成、哈希计算、原图解码、文件移动全部在工作线程完成，UI 线程只做渲染。

## 功能特性

- **图片墙（滚动模式）**：justified 无缝拼接布局，不显示文件名，每行按宽高比自动凑满视口，行高随滑块调整；支持方向键焦点导航、Enter 进大图。
- **分页模式**：页码条（首页/上一页/下一页/末页），每页数量随窗体尺寸自动重算；每张卡片下方带基础功能按钮（★最爱 / 存 / 拷 / 位 / 移）。
- **大图浏览器**：全屏覆盖层；滚轮缩放 1%~800%（锚定鼠标）、拖拽平移、双击适应/100% 切换、90° 旋转、←/→ 切换（预加载前后各 1 张）、Esc 返回、F 收藏；先显示 512 档缓存、原图后台解码无缝替换。
- **最爱系统**：`favorites.json` 跟随图片目录（只记相对路径，目录移动不丢）；星标角标、"仅看最爱"过滤、快捷键 F。
- **五种排序**：随机（固定种子，同目录稳定）/ 时间正序 / 时间倒序 / 大小正序 / 大小倒序；"重新随机"换种子；信息行随排序变化。
- **长宽比筛选**：预设 1:1、16:9、1:2 等 + 自定义比例（如 `1.5:3`），±10% 容差整体符合即可。
- **重复图片检测**：缩略图生成时顺带计算 pHash（32×32 灰度，64bit），汉明距离 ≤ 阈值（默认 4，设置可调）判疑似重复；「簇代表」聚类避免链式误并；蓝色角标 + 组面板，可一键"保留最大/保留最新，其余移出"。
- **垃圾桶**：移出（移动到 `Remove/`，可逆，重名自动加后缀）而非删除；垃圾桶页面支持还原（回到原子目录，`R` 键或右键/卡片按钮）。
- **图片操作**：另存为（Ctrl+S）、复制图片到剪贴板（Ctrl+C）、打开所在位置（Ctrl+O）、移出（Del）。
- **体验细节**：拖拽文件夹加载、文件名搜索、空态引导提示、暗色主题、高 DPI、F11 全屏、窗口/视图状态记忆、2:1 比例提示、中文路径安全、单实例保护、目录变更自动/手动刷新（F5）、网络盘退避重试。

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 x64 |
| Python | 3.11+（开发态运行需要） |
| 运行依赖 | PySide6 ≥ 6.7、Pillow ≥ 10、numpy ≥ 1.24 |
| 打包依赖 | pyinstaller ≥ 6 |

## 快速开始

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 运行
.venv\Scripts\python.exe main.py
```

首次使用点击工具栏「打开目录」，或直接把文件夹拖进窗口；也可在「设置」中配置默认读取目录（启动自动加载）。

## 打包发行

```powershell
build.bat          # onefile 单文件：dist\QianXunViewer.exe（首次启动略慢属正常）
build-onedir.bat   # onedir 目录版：dist\QianXunViewer\QianXunViewer.exe（启动更快）
```

打包产物在 `dist/`，可直接拷贝到无 Python 环境的 Windows 机器运行。

## 快捷键

| 快捷键 | 功能 | 快捷键 | 功能 |
|---|---|---|---|
| `F` | 切换最爱 | `Ctrl+S` | 另存为 |
| `Del` | 移出到 Remove | `Ctrl+C` | 复制图片 |
| `R` | 垃圾桶内还原 / 大图旋转 | `Ctrl+O` | 打开所在位置 |
| `F11` | 全屏 | `F5` | 刷新当前目录 |
| `←` `→` / `Esc` | 大图切换 / 返回 | 方向键+`Enter` | 图片墙导航/进大图 |

完整操作说明见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)。

## 目录结构

```
qianxun-viewer/
├── main.py                 # 入口
├── requirements.txt        # 运行/打包依赖
├── build.bat               # onefile 打包脚本
├── build-onedir.bat        # onedir 打包脚本
├── assets/                 # logo.png / icon.ico
├── docs/                   # 用户指南 / 架构 / 变更日志
└── src/
    ├── meta.py             # 名称 / 版本 / 版权
    ├── controllers.py      # 控制层：加载/排序/分页/筛选/缩略图调度/操作分发
    ├── core/               # 服务层（无 Qt 依赖）：模型/扫描/缩略图/最爱/查重/设置
    ├── workers/            # 工作线程层：Scan/Thumb/Decode/Hash/Move
    ├── ui/                 # UI 层：主窗体/图片墙/网格/分页/大图/设置/重复面板/QSS
    └── utils/              # 文件操作 / 格式化 / 资源路径
```

## 架构设计

分层：UI（PySide6）→ 控制层 → 服务层（core，纯 Python）→ 工作线程层（QThreadPool + Worker）→ 数据层。
线程模型、缓存策略、内存红线、无损操作等详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 数据与配置

| 位置 | 说明 |
|---|---|
| 本地 `%LOCALAPPDATA%/QianXunViewer/cache/<目录指纹>/{256,512}/` | 缩略图磁盘缓存（不写入图片目录，云同步无流量），命名 = `sha1(路径\|大小\|mtime)`，文件变更自动失效 |
| 图片目录/`favorites.json` | 最爱配置（相对路径），随目录移动 |
| 图片目录/`Remove/` | 垃圾桶；内含 `.qx_removed.json` 记录原路径用于还原 |
| 用户目录 QSettings（INI） | 程序设置与状态记忆（目录/模式/滑块/排序/页码/滚动/窗口几何） |

## 测试

开发期通过离屏（`QT_QPA_PLATFORM=offscreen`）冒烟脚本验证：真实大目录扫描、缩略图缓存、排序、分页、图片墙无缝布局、卡片按钮、最爱持久化、移出/还原、重复检测、大图解码等（19 项断言全过）。测试脚本为临时文件，不随仓库分发；日常回归可直接运行程序按 [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 的 FAQ 抽查。

## 文档

- [用户指南](docs/USER_GUIDE.md)
- [架构设计](docs/ARCHITECTURE.md)
- [变更日志](docs/CHANGELOG.md)

## 版权与许可

版权所有 © 2026 羡林i (Y_XianLin)，保留所有权利。详见 [LICENSE](LICENSE)。
第三方组件（PySide6、Pillow、numpy、PyInstaller 等）依各自开源许可使用。
