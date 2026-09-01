# 架构设计

千寻图片查看器 v1.0.0 · 版权所有 © 羡林i (Y_XianLin)

## 1. 设计思想

1. **缩略图优先（Thumbnail-First）**：网格/图片墙只消费 256/512 两档落盘缓存；原图仅在大图浏览器按需解码。
2. **全程异步（Never Block UI）**：扫描、缩略图、哈希、原图解码、文件移动全部在 `QThreadPool` 工作线程；UI 线程只渲染。
3. **增量呈现**：扫描即出列表；缩略图按视口可见优先调度，占位先行、逐张替换。
4. **数据与视图分离**：`core/` 服务层不依赖 Qt（`settings.py` 的 QSettings 封装除外），可独立单测。
5. **配置就近**：最爱配置跟随图片目录；程序级设置存用户目录。
6. **无损操作**：移出可逆（`Remove/` + 原路径映射），删除类操作一律不做。

## 2. 分层结构

```
┌──────────────────────────────────────────────┐
│ UI 层 (PySide6)                               │
│ MainWindow │ WallView │ GridView+Delegate │   │
│ Pager │ ViewerOverlay │ SettingsDialog │      │
│ DuplicatesDialog │ styles.qss                │
├──────────────────────────────────────────────┤
│ 控制层 controllers.LibraryController         │
│ 加载/排序/分页/筛选/缩略图调度/操作分发/垃圾桶   │
├──────────────────────────────────────────────┤
│ 服务层 core（无 Qt 依赖）                      │
│ image_item │ scanner │ thumbnail │ favorites │
│ duplicates │ settings                        │
├──────────────────────────────────────────────┤
│ 工作线程层 workers（QRunnable + Signal）       │
│ ScanWorker │ ThumbWorker │ DecodeWorker │     │
│ HashWorker │ MoveWorker                      │
├──────────────────────────────────────────────┤
│ 工具层 utils：file_ops / format / paths       │
└──────────────────────────────────────────────┘
```

## 3. 核心数据模型

`ImageItem`（dataclass）：`path / size_bytes / mtime / width / height / phash / favorite / dup_group / corrupted`。扫描时仅读文件头获取分辨率，不解码像素。

## 4. 线程模型与并发安全

- 全局 `QThreadPool`（4 线程）承载 Scan/Thumb/Decode/Hash；`move_pool`（**1 线程**）串行化移出/还原，防止快速连按 `Del` 竞态。
- Worker 通过 Qt 信号回传结果，禁止跨线程操作 UI。
- **引用保活**：`LibraryController._track(w)` 持有 worker 引用至其终止信号发出，避免运行期被 GC 导致 "Signal source has been deleted"。
- **退出静默**：`workers._emit()` 对退出期接收端已销毁的 RuntimeError 静默；`closeEvent` 中 `waitForDone` 等待线程池收尾。
- **加载世代令牌 `_load_seq`**：切换目录后旧 ScanWorker 的批次/完成信号一律作废，杜绝跨目录数据污染。
- **预热泵**：`_warm_all_thumbs` 不再一次性洪泛提交，改为 deque + `_pump_warm` 限量并发（≤8）；可见任务 priority=1 始终插队，快速滚动不做无效解码。
- **目录监听**：`QFileSystemWatcher` + 800ms 防抖自动重扫；`reload_current()`（F5/按钮）兼作网络盘等监听不可靠场景的手动入口。

## 5. 缩略图缓存

- 目录：本地 `%LOCALAPPDATA%/QianXunViewer/cache/<图片目录指纹>/{256,512}/`——不写入图片目录，云同步/网盘目录不产生流量（v1.1.1 起）。
- 命名：`sha1(绝对路径|大小|mtime).jpg` —— 幂等且天然失效（文件变更即换名重建）。
- 档位选择：展示尺寸 > 256 用 512 档，否则 256 档。
- 调度：视口可见项 priority=1 优先，其余扫描完成后 priority=-1 预热；生成时顺带在 32×32 灰度图上计算 pHash（64bit）。
- 方向正确性：`ImageOps.exif_transpose`；损坏图标记 `corrupted` 并在 UI 显示"已损坏"。
- 内存侧：`QPixmapCache` 上限 300MB，超额自动淘汰。

## 6. 内存红线

- 网格/图片墙只持有缩略图 `QPixmap`，绝不解码原图。
- 原图解码设 `Image.MAX_IMAGE_PIXELS` 上限；超过 `MAX_DECODE_PIXELS`(1.2 亿像素) 用 `draft()` 降采样解码防 OOM。
- 大图浏览器仅保留当前张 + 前后预加载各 1 张。

## 7. 视图布局

- **WallView（图片墙）**：`QAbstractScrollArea` 自绘。justified 算法：按宽高比贪心累加，`行高 = 视口宽 / Σ宽高比`，达到目标行高即断行；行末格取余宽，图片以 cover 裁切填充，实现行间/行内无缝。滚动范围由总布局高度决定；可见范围反推用于缩略图调度。
- **GridView（分页）**：`QListView(IconMode)` + 自定义 Delegate 绘制卡片（图 + 信息行 + 按钮行 + 角标）。按钮命中：`mousePressEvent` 中对 `delegate.button_rects(visualRect)` 做矩形命中，命中则发 `card_action` 而非选择。
- 分页容量：`每页 = 列数 × 行数`，由视口与 `sizeHint` 实时计算；窗体变化自动重算并夹取页码。

## 8. 最爱与无损操作

- `favorites.json`：`{"version":1,"items":[{"path":相对路径,"added":时间}]}`，相对路径保证目录整体移动后仍生效。
- 移出：`Remove/<原名>`（重名加 `(n)` 后缀），并在 `Remove/.qx_removed.json` 记录 `移出后文件名 → 原相对路径`；还原据此回到原子目录（目录缺失则回根目录），保证可逆。

## 9. 查重

- pHash 为 numpy 自实现（`core/phash.py`：32×32 灰度 + 二维 DCT，取 8×8 低频与中值比较得 64bit），不依赖 imagehash/scipy，包体显著缩小。
- 全量加载完成后 `HashWorker` 后台「簇代表」聚类（成员与组首代表汉明距离 ≤ 阈值，默认 4，设置可调 0–12），避免传递性链式合并；结果写 `dup_group`，UI 打蓝标；面板支持按最大/最新保留（其余走可逆移出）。

## 10. 状态持久化（QSettings INI）

键：`default_open_dir / default_save_dir / view_mode / sort_mode / thumb_size / last_dir / last_page / last_scroll / window_geo`。启动恢复顺序：默认目录 > 上次目录。

## 11. 打包与资源

- `utils/paths.base_dir()` 兼容开发态与 `sys._MEIPASS` 冻结态。
- `--add-data` 携带 `assets/logo.png` 与 `src/ui/styles.qss`；图标经 `--icon` 嵌入。
- onefile 首次启动自解压较慢；onedir 启动更快，二者功能一致。

## 12. IO 容错（网络盘/慢速介质）

- 扫描：`stat` 与文件头读取失败均退避重试（0.2s 起），仍失败才计错误/标记损坏。
- 缩略图 `generate` 与原图 `decode_original`：3 次退避重试（0.3s/0.6s），瞬时 SMB/云盘 IO 错误不再误判「已损坏」。
- 缓存写入失败（磁盘满/只读）静默降级，状态栏提示。

## 13. 扩展点

- 新视图：实现 `set_items / visible_range_changed / item_clicked / customContextMenuRequested` 即可接入控制器。
- 新排序：`SORT_MODES` + `_sort` 分支 + 信息行映射。
- 新卡片按钮：`CARD_ACTIONS/CARD_GLYPHS` + `_on_card_action` 分发。
