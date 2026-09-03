# 千寻图片查看器 QianXun Viewer

<img src="assets/logo.png" width="96" alt="千寻图片查看器 Logo">

> 面向大规模本地图片库（千张级、单张 10~60MB）的高性能 Windows 桌面查看器。
> 缩略图优先 · 全程异步 · 无损操作 · 云盘友好。

`版本 v1.3.0（测试版）` · `平台 Windows 10/11 x64` · `Python 3.11+ / PySide6`

**作者：羡林i (Y_XianLin)** · 版权所有 © 2026，保留所有权利（详见 [LICENSE](LICENSE)）
仓库：[Gitee](https://gitee.com/xianlin-i/qianxun-viewer) · 前身：[ImgRandomDisplay](https://gitee.com/xianlin-i/ImgRandomDisplay)

---

## 界面预览

**启动闪屏** —— 启动即拉起 Logo，重型依赖延迟加载，主窗秒级呈现：

![启动闪屏](docs/images/00_splash.png)

**图片墙（默认）** —— justified 无缝拼接、不显示文件名；工具栏含 搜索 / 长宽比 / 文件夹 三重筛选：

![图片墙](docs/images/01_wall.png)

**图片墙多选** —— Ctrl/Shift 多选、右键预选（金色选框），批量操作：

![图片墙多选](docs/images/01b_wall_multisel.png)

**分页模式** —— 每张卡片带信息行与基础功能按钮（★最爱 / 存 / 拷 / 位 / 移）：

![分页模式](docs/images/02_page.png)

**大图浏览器** —— 全屏覆盖层，缩放/平移/旋转/切换，右上角可见操作按钮：

![大图浏览器](docs/images/03_viewer.png)

**重复图片检测** —— pHash 簇代表聚类，分组并排预览，一键保留最大/最新，可重新检测：

![重复检测](docs/images/04_duplicates.png)

**垃圾桶** —— 移出可逆、可还原回原子目录，程序不做任何删除：

![垃圾桶](docs/images/05_trash.png)

**缓存管理** —— 缓存存本地用户目录，云同步目录零流量：

![缓存管理](docs/images/06_cache.png)

**上传到云** —— 多线程增量上传，三层去重跳过，进度实时：

![上传到云](docs/images/07_upload.png)

**程序设置** —— 目录 / 查重阈值 / 线程数 / 外链有效期 / 启动行为等均可调：

![程序设置](docs/images/08_settings.png)

**在线库（OSS）** —— 整桶列举 800+ 张，IMG 签名缩略图，原图按需加载：

![在线库](docs/images/09_online.png)

## 功能特性

- **图片墙（滚动模式）**：justified 无缝拼接布局；末行自然宽度不拉伸；滚轮每格至少一行高度；方向键焦点 + Enter 进大图；Ctrl/Shift 多选 + 右键预选，批量操作复用快捷键与菜单。
- **分页模式**：页码条（首页/上一页/下一页/末页），每页数量随窗体自适应；卡片功能按钮行。
- **大图浏览器**：滚轮缩放 1%~800%（锚定鼠标）、拖拽平移、双击适应/100%、90° 旋转、←/→ 切换（预加载 ±1）、Esc/✕ 返回、F 收藏；512 档缓存先行、原图后台无缝替换；超大图降采样防 OOM。
- **最爱系统**：`favorites.json` 跟随图片目录（相对路径，目录移动不丢）；星标角标；"仅看最爱"过滤。
- **五种排序**：随机（固定种子）/ 时间± / 大小±；"重新随机"换种子。
- **筛选**：文件名搜索（子串、不区分大小写）+ 长宽比筛选（预设 1:1/16:9/1:2 等，可自定义如 `1.5:3`，±10% 容差）+ 「文件夹」下拉子树筛选；本地/在线/垃圾桶通用，与排序/仅看最爱任意叠加。
- **重复图片检测**：pHash（numpy 自实现，64bit）+ 簇代表聚类防链式误并；阈值默认 4、设置可调 0–12；组面板一键"保留最大/最新，其余移出"。
- **垃圾桶**：移出 = 移动到 `Remove/`（可逆、重名加后缀），垃圾桶页可还原回原子目录；`R` 键快捷还原。
- **图片操作**：另存为（Ctrl+S）、复制图片（Ctrl+C）、复制文件、打开所在位置（Ctrl+O）、移出（Del）。
- **体验细节**：拖拽文件夹加载、空态引导、暗色主题、高 DPI、F11 全屏、2:1 比例提示、窗口/视图状态记忆、单实例保护、目录变更自动/手动刷新（F5）。
- **云盘/网络盘友好**：缩略图缓存存本地用户目录（不写图片目录、无同步流量）；所有 IO 退避重试，瞬时错误不误判"已损坏"；关窗即退（工作线程取消机制）。
- **阿里云 OSS 在线库（v1.3.0 测试版）**：「上传到云」多线程增量上传（三层去重跳过）；「在线库」模式浏览云端库（IMG 签名缩略图 + 原图按需）；分享双模式：限时签名外链（≤7 天）或永久直链（单对象公共读，桶保持私有，可撤回）。设计详见 [docs/ONLINE_DESIGN.md](docs/ONLINE_DESIGN.md)。
- **启动体验**：启动即拉起 Logo 闪屏，重型依赖延迟加载，主窗体秒级呈现。

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

打包产物在 `dist/`，可直接拷贝到无 Python 环境的 Windows 机器运行。发行版以 Git 标签（如 `v1.2.1`）管理。

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
├── main.py                 # 入口（单实例保护）
├── requirements.txt        # 运行/打包依赖
├── build.bat               # onefile 打包脚本
├── build-onedir.bat        # onedir 打包脚本
├── assets/                 # logo.png / icon.ico
├── docs/                   # 用户指南 / 架构 / 变更日志 / 截图
└── src/
    ├── meta.py             # 名称 / 版本 / 版权
    ├── controllers.py      # 控制层：加载/排序/分页/筛选/缩略图调度/操作分发
    ├── core/               # 服务层（无 Qt 依赖）：模型/扫描/缩略图/最爱/查重/pHash/设置
    ├── workers/            # 工作线程层：Scan/Thumb/Decode/Hash/Move（可取消）
    ├── ui/                 # UI 层：主窗体/图片墙/网格/分页/大图/设置/重复面板/缓存/QSS
    └── utils/              # 文件操作 / 格式化 / 资源路径
```

## 架构设计

分层：UI（PySide6）→ 控制层 → 服务层（core，纯 Python）→ 工作线程层（QThreadPool + Worker）→ 数据层。
线程模型、缓存策略、内存红线、无损操作、IO 容错等详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 数据与配置

| 位置 | 说明 |
|---|---|
| 本地 `%LOCALAPPDATA%/QianXunViewer/cache/<目录指纹>/{256,512}/` | 缩略图磁盘缓存（不写入图片目录，云同步无流量），命名 = `sha1(路径\|大小\|mtime)`，文件变更自动失效 |
| 图片目录/`favorites.json` | 最爱配置（相对路径），随目录移动 |
| 图片目录/`Remove/` | 垃圾桶；内含 `.qx_removed.json` 记录原路径用于还原 |
| 用户目录 QSettings（INI） | 程序设置与状态记忆（目录/模式/滑块/排序/页码/滚动/窗口几何/查重阈值） |

## 测试

开发期通过离屏（`QT_QPA_PLATFORM=offscreen`）冒烟脚本验证：真实大目录与云盘目录扫描、缩略图缓存、排序、分页、图片墙无缝布局与末行不拉伸、卡片按钮、最爱持久化、移出/还原、重复检测与链式抑制、长宽比筛选、大图解码、退出无残留等。测试脚本为临时文件，不随仓库分发。

## 文档

- [用户指南](docs/USER_GUIDE.md)
- [架构设计](docs/ARCHITECTURE.md)
- [变更日志](docs/CHANGELOG.md)

## 版权与许可

**千寻图片查看器 QianXun Viewer**
**版权所有 © 2026 羡林i (Y_XianLin)，保留所有权利。** 详见 [LICENSE](LICENSE)。
第三方组件（PySide6、Pillow、numpy、PyInstaller 等）依各自开源许可使用。
