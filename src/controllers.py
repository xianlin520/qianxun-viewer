# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""控制层：加载 / 排序 / 分页 / 筛选 / 缩略图调度 / 操作分发。"""
from __future__ import annotations

import math
import os
import random
import shutil
import time
import zlib
from collections import deque
from pathlib import Path

from PySide6.QtCore import (QEventLoop, QFileSystemWatcher, QObject,
                            QThreadPool, QTimer, Signal)
from PySide6.QtGui import QPixmap

from .core import thumbnail
from .core.favorites import FavoritesStore
from .core.image_item import ImageItem
from .core.oss_service import (SHARE_EXPIRES, OssIndex, OssLibrary,
                              friendly_error, is_block_public_error)
from .core.settings import AppSettings
from .utils import file_ops
from .utils.format import human_size
from .workers.workers import (DecodeWorker, FavoriteSyncWorker, HashWorker,
                              ListWorker, MoveWorker, OnlineDeleteWorker,
                              ScanWorker, ThumbWorker, UploadWorker)

SORT_MODES = [("random", "随机"), ("time_asc", "时间正序"), ("time_desc", "时间倒序"),
              ("size_asc", "大小正序"), ("size_desc", "大小倒序")]

ASPECT_TOL = 0.10          # 长宽比容差（对数距离，约 ±10%）
ASPECT_PRESETS = ["全部", "1:1", "4:3", "3:2", "16:9", "2:1",
                  "3:4", "2:3", "9:16", "1:2"]


def parse_aspect(text: str):
    """解析 'a:b' 或单个浮点（宽/高）；无效/全部 返回 None。

    拒绝 0、负数、inf、nan：这些值会让 abs(log(ratio/target)) 变成
    inf/nan，导致筛选结果要么全灭要么全过。"""
    text = (text or "").strip()
    if not text or text in ("全部", "all", "*"):
        return None
    try:
        if ":" in text:
            a, b = text.split(":", 1)
            a, b = float(a), float(b)
            v = a / b if a > 0 and b > 0 else None
        else:
            v = float(text)
        if v is None or not math.isfinite(v) or v <= 0:
            return None
        return v
    except (ValueError, ZeroDivisionError):
        return None


class LibraryController(QObject):
    status = Signal(str, int)      # 状态栏消息, 超时 ms（0=常驻）
    title_changed = Signal(str)
    scan_done = Signal()
    view_reset = Signal()          # 模型整体重建
    wall_update = Signal()         # 图片墙重绘（缩略图/角标变化）
    dups_ready = Signal(list)

    def __init__(self, model, view, delegate, settings: AppSettings):
        super().__init__()
        self.model = model
        self.view = view
        self.delegate = delegate
        self.settings = settings
        self.root: Path | None = None
        self.main_root: Path | None = None     # 主图片目录（垃圾桶模式下保持不变）
        self.cache_root: Path | None = None    # 缩略图缓存根目录
        self.trash_mode = False
        self.all_items: list[ImageItem] = []
        self.view_items: list[ImageItem] = []
        self.favorites: FavoritesStore | None = None
        self.sort_mode = settings.sort_mode or "random"
        self.fav_only = False
        self.view_mode = settings.view_mode or "scroll"
        self.page = 0
        self._pending_page: int | None = None   # 启动时待恢复的期望页码
        self.per_page = 1
        self._seed_extra = 0
        self._rand_order: dict[str, float] = {}   # 随机序固化：路径 → 排序键
        self._rand_seed: int | None = None        # 当前随机序对应的种子
        self._by_path: dict[str, ImageItem] = {}
        self._queued: set[tuple[str, int]] = set()
        self._pending_thumbs = 0
        self._scan_finished = False
        self._dup_done = False
        self._scan_refresh_timer: QTimer | None = None
        self._show_dup_dialog = False

        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        # 移出操作单线程队列，防止快速连按 Del 引发竞态
        self.move_pool = QThreadPool(self)
        self.move_pool.setMaxThreadCount(1)
        self._active: set = set()   # 持有 worker 引用，防止运行期间被 GC
        self._load_seq = 0          # 加载世代令牌：切换目录后旧扫描结果作废
        self.filter_text = ""       # 文件名搜索过滤
        self.folder_filter = ""     # 子文件夹筛选（子树前缀匹配）
        self.aspect_target: float | None = None   # 长宽比筛选
        self._warm_queue: deque = deque()
        self._warm_active = 0
        self._warm_pending: set = set()
        self._scroll_restored_for: str | None = None
        self._cancelled = False
        self.oss: OssLibrary | None = None
        self.online_mode = False
        self.oss_index = OssIndex()
        self._index_bucket = ""  # 索引所属 Bucket（换桶后自动重建）
        self._cloud_keys = None   # 云端 key 缓存（懒加载，上传后增量维护）
        self.share_error = ""     # 最近一次分享失败原因（供 UI 提示）
        self._share_srv = None    # 分享服务端客户端（惰性构造）
        # 收藏同步：推送队列 + 合并定时器 + 独立线程池（不与缩略图抢线程）
        self._fav_pending: dict[str, dict] = {}
        self._fav_flush_timer = QTimer(self)
        self._fav_flush_timer.setSingleShot(True)
        self._fav_flush_timer.setInterval(300)
        self._fav_flush_timer.timeout.connect(self._flush_favorite_push)
        self._fav_pool = QThreadPool(self)
        self._fav_pool.setMaxThreadCount(1)   # 串行，保证推送顺序
        self._fav_syncing = False
        self.share_blocked = False   # 是否因“阻止公共访问”失败（可降级签名外链）

        # 目录变更监听：防抖后自动重扫
        self._watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._on_dir_changed_settled)
        self._watcher.directoryChanged.connect(lambda _p: self._reload_timer.start())
        # 程序自身写入的元数据（favorites.json / .qx_removed.json / Remove 内的移动）
        # 会让图片根目录 mtime 变化，若不加抑制，收藏一张或移出一张就会触发整库重扫，
        # 连带把页码和文件夹筛选清空。
        self._self_write_until = 0.0

    def _suppress_watch(self, seconds: float = 2.0) -> None:
        """标记「接下来这段时间的目录变化是程序自己造成的」，不触发重扫。"""
        self._self_write_until = time.monotonic() + seconds

    def _on_dir_changed_settled(self) -> None:
        if time.monotonic() < self._self_write_until:
            return
        self.reload_current()

    def _track(self, w) -> None:
        """保持 worker 的 Python 引用至其信号发出完毕。"""
        self._active.add(w)
        for name in ("batch", "ready", "finished", "failed"):
            sig = getattr(w.signals, name, None)
            if sig is not None:
                sig.connect(lambda *a, w=w: self._active.discard(w))

    # ---------------- 加载 ----------------
    def load_directory(self, path: Path, trash: bool = False) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self._cancelled = False
        self.trash_mode = trash
        if trash:
            self.cache_root = self.main_root or path
        else:
            self.main_root = path
            self.cache_root = path
        self.root = path
        self.all_items.clear()
        self._by_path.clear()
        self._queued.clear()
        self._pending_thumbs = 0
        self._scan_finished = False
        self._dup_done = False
        # 换库时页码/筛选必须复位：否则新库沿用旧页码会停在空页，
        # 旧的文件夹筛选也可能匹配不到任何东西
        self.page = 0
        self._pending_page = None      # 换库时不保留启动恢复的期望页码
        self.folder_filter = ""
        self._warm_queue.clear()
        self._warm_pending.clear()
        self._warm_active = 0
        self.favorites = FavoritesStore(path)
        self.delegate.image_root = self.cache_root
        self._watcher.removePaths(self._watcher.directories())
        self._watcher.addPath(str(path))
        self.status.emit(f"正在扫描 {path} …", 0)
        w = ScanWorker(path, is_cancelled=self.is_cancelled,
                       parallel=self.settings.scan_parallel)
        w.signals.batch.connect(lambda b, e, s=seq: self._on_batch(b, e, s))
        w.signals.finished.connect(lambda t, e, s=seq: self._on_scan_done(t, e, s))
        w.signals.failed.connect(lambda m: self.status.emit(f"扫描失败：{m}", 5000))
        self._track(w)
        self.pool.start(w)

    def _on_batch(self, batch, errors, seq: int) -> None:
        if seq != self._load_seq:
            return
        for it in batch:
            it.favorite = self.favorites.contains(it.path)
            self.all_items.append(it)
            self._by_path[str(it.path)] = it
        # 扫描期节流：每批都全量重排 + 重建模型会让大库（千张级）明显卡顿，
        # 这里最多每 150ms 刷新一次；扫描结束时 _on_scan_done 再强制刷一次。
        if self._scan_refresh_timer is None:
            self._scan_refresh_timer = QTimer(self)
            self._scan_refresh_timer.setSingleShot(True)
            self._scan_refresh_timer.setInterval(150)
            self._scan_refresh_timer.timeout.connect(self._flush_scan_refresh)
        if not self._scan_refresh_timer.isActive():
            self._scan_refresh_timer.start()
        self.status.emit(f"已加载 {len(self.all_items)} 张…", 0)

    def _flush_scan_refresh(self) -> None:
        if not self._scan_finished:
            self.refresh_view()

    def _on_scan_done(self, total, errors, seq: int) -> None:
        if seq != self._load_seq:
            return
        if self._scan_refresh_timer is not None:
            self._scan_refresh_timer.stop()
        self._scan_finished = True
        total_size = sum(i.size_bytes for i in self.all_items)
        prefix = "垃圾桶 — " if self.trash_mode else ""
        self.title_changed.emit(
            f"千寻影集 — {prefix}{total} 张 · 共 {human_size(total_size)}")
        msg = f"扫描完成：{total} 张图片"
        if errors:
            msg += f"，{errors} 个文件读取失败已跳过"
        self.status.emit(msg, 5000)
        self.refresh_view()
        self.scan_done.emit()
        self._warm_all_thumbs()
        # 扫描完成后从云端合并收藏：延迟到事件循环空闲再做，
        # 避免同步网络请求卡住「扫描完成」这一刻的 UI
        if not self.trash_mode and not self.online_mode:
            QTimer.singleShot(1200, self.sync_favorites)

    # ---------------- 视图组织 ----------------
    def refresh_view(self) -> None:
        items = list(self.all_items)
        if self.fav_only:
            items = [i for i in items if i.favorite]
        if self.filter_text:
            kw = self.filter_text.lower()
            items = [i for i in items if kw in i.path.name.lower()]
        if self.folder_filter:
            ff = self.folder_filter
            prefix = ff + "/"
            kept = []
            for i in items:
                f = self._item_folder(i)      # 每项只算一次（原实现调用了两次）
                if f == ff or f.startswith(prefix):
                    kept.append(i)
            items = kept
        if self.aspect_target is not None:
            t = self.aspect_target
            items = [i for i in items
                     if i.width and i.height
                     and abs(math.log(i.width / i.height / t)) <= ASPECT_TOL]
        self.view_items = self._sort(items)
        self._apply_to_model()

    def set_filter(self, text: str) -> None:
        self.filter_text = text.strip()
        self.refresh_view()

    def set_aspect(self, text: str) -> None:
        self.aspect_target = parse_aspect(text)
        self.refresh_view()

    # ---------------- 子文件夹筛选 ----------------
    def _item_folder(self, item) -> str:
        """返回项的相对父目录（posix）；在线项用 object key 父路径。

        性能要点：Path.resolve() 在 Windows 上要走 realpath 系统调用
        （本机实测 1.92ms/次，比 os.path.abspath 慢约 1500 倍）。
        这里改用 abspath + 前缀比较，并把基于 main_root 的结果缓存到 item 上，
        否则千张库单次筛选要几秒。"""
        if item.remote_key:
            return "/".join(item.remote_key.split("/")[:-1])
        cached = getattr(item, "_folder_cache", None)
        if cached is not None:
            return cached
        base = self.main_root if not self.online_mode else None
        if base is None:
            return ""
        try:
            base_abs = os.path.abspath(str(base))
            p_abs = os.path.abspath(str(item.path))
            rel = os.path.relpath(p_abs, base_abs)
            if rel.startswith(".."):
                return ""
            parent = os.path.dirname(rel)
            rel_parent = "" if parent in ("", ".") else parent.replace("\\", "/")
        except (ValueError, OSError):
            rel_parent = ""
        item._folder_cache = rel_parent
        return rel_parent

    def available_folders(self) -> list:
        """所有相对父目录及其祖先，排序返回。"""
        folders: set[str] = set()
        for it in self.all_items:
            f = self._item_folder(it)
            while f and f != ".":
                folders.add(f)
                f = f.rsplit("/", 1)[0] if "/" in f else ""
        return sorted(f for f in folders if f and f != ".")

    def set_folder_filter(self, folder: str) -> None:
        self.folder_filter = (folder or "").strip()
        self.refresh_view()

    def _sort(self, items):
        m = self.sort_mode
        if m == "time_asc":
            items.sort(key=lambda i: i.mtime)
        elif m == "time_desc":
            items.sort(key=lambda i: i.mtime, reverse=True)
        elif m == "size_asc":
            items.sort(key=lambda i: i.size_bytes)
        elif m == "size_desc":
            items.sort(key=lambda i: i.size_bytes, reverse=True)
        else:
            # 随机序按「路径 → 序号」固化：原实现每次刷新都对当前列表整体
            # shuffle，删掉一张后下标全变，整屏图都会换位置。
            # 现在只在新增图片时补号，删图不影响其余项的相对顺序。
            seed = (zlib.crc32(str(self.root).encode("utf-8", "surrogatepass"))
                    + self._seed_extra) & 0xFFFFFFFF
            order = self._rand_order
            if self._rand_seed != seed:
                # 只有「重新随机」(种子变化) 或首次进入目录才重建随机序；
                # 删图/增图只是让映射多/少一项，不能整体重排
                self._rand_seed = seed
                rnd = random.Random(seed)
                order.clear()
                for it in items:
                    order[str(it.path)] = rnd.random()
            missing = [str(it.path) for it in items if str(it.path) not in order]
            if missing:
                for p in missing:
                    order[p] = (zlib.crc32(
                        (p + str(seed)).encode("utf-8", "surrogatepass"))
                        & 0xFFFFFFFF) / 2 ** 32
            items.sort(key=lambda i: order.get(str(i.path), 0.0))
        return items

    def _apply_to_model(self) -> None:
        self.model.info_mode = (
            "size" if self.sort_mode.startswith("size")
            else "time" if self.sort_mode.startswith("time") else "random")
        if self.view_mode == "page":
            self.per_page = max(1, self.view.page_capacity())
            total = max(1, -(-len(self.view_items) // self.per_page))
            # 扫描是分批到达的：首批可能只够 1 页，直接夹取会把「上次页码」
            # 就地压成 0 且再也回不来。用 _pending_page 记住期望值，
            # 等总页数够大时再落地。
            if self._pending_page is not None:
                if total - 1 >= self._pending_page:
                    self.page = self._pending_page
                    self._pending_page = None
                else:
                    total = total          # 页数还不够，先停在第 0 页
            self.page = max(0, min(self.page, total - 1))
            shown = self.view_items[self.page * self.per_page:(self.page + 1) * self.per_page]
            self.model.set_items(shown)
            self.view.pager.set_state(self.page, total)
        else:
            self.model.set_items(self.view_items)
        self.view_reset.emit()

    def restore_page(self, page: int) -> None:
        """启动时恢复上次页码：记为期望值，待扫描出足够页数后生效。"""
        self._pending_page = max(0, int(page))
        self._apply_to_model()

    def set_sort(self, mode: str) -> None:
        self.sort_mode = mode
        self.settings.sort_mode = mode
        self.refresh_view()

    def reseed(self) -> None:
        self._seed_extra += 1
        self.refresh_view()
        self.status.emit("已重新随机排序", 2000)

    def set_fav_only(self, on: bool) -> None:
        self.fav_only = on
        self.refresh_view()

    def set_view_mode(self, mode: str, persist: bool = True) -> None:
        self.view_mode = mode
        if persist:
            self.settings.view_mode = mode
        self.view.pager.setVisible(mode == "page")
        self._apply_to_model()

    def set_page(self, page: int) -> None:
        # 上界在 _apply_to_model 里按 per_page 夹取；此处先规范为合法非负值
        self.page = max(0, int(page))
        self._apply_to_model()
        self.view.verticalScrollBar().setValue(0)

    def set_thumb_size(self, value: int) -> None:
        self.delegate.thumb_size = value
        self.settings.thumb_size = value
        from PySide6.QtCore import QSize
        hint = self.delegate.sizeHint(None, None)
        self.view.setGridSize(QSize(hint.width(), hint.height()))
        if self.view_mode == "page":
            self._apply_to_model()
        self.ensure_visible_thumbs(*self.view.visible_range())

    def on_view_resized(self) -> None:
        if self.view_mode == "page":
            self._apply_to_model()
        self.ensure_visible_thumbs(*self.view.visible_range())

    # ---------------- 缩略图调度 ----------------
    def current_tier(self) -> int:
        return 512 if self.delegate.thumb_size > 256 else 256

    def ensure_visible_thumbs(self, first: int, last: int) -> None:
        items = self.model.items()
        for row in range(max(0, first), min(len(items), last + 1)):
            self._submit_thumb(items[row], priority=1)

    def _submit_thumb(self, item, priority: int = 0, warm: bool = False) -> bool:
        if item.corrupted or self.root is None:
            return False
        tier = self.current_tier()
        key = (str(item.path), tier)
        if key in self._queued:
            return False
        self._queued.add(key)
        self._pending_thumbs += 1
        if warm:
            self._warm_pending.add(key)
        w = ThumbWorker(self.cache_root, item, tier,
                        with_phash=not bool(item.phash),
                        is_cancelled=self.is_cancelled,
                        oss=self.oss if item.remote_key else None)
        w.signals.ready.connect(self._on_thumb_ready)
        w.signals.failed.connect(self._on_thumb_failed)
        self._track(w)
        self.pool.start(w, priority)
        return True

    # ---------------- 预热泵：限量并发，可见高优先始终插队 ----------------
    def _warm_all_thumbs(self) -> None:
        self._warm_queue = deque(self.all_items)
        self._pump_warm()

    def _pump_warm(self) -> None:
        while self._warm_active < 8 and self._warm_queue:
            it = self._warm_queue.popleft()
            if self._submit_thumb(it, priority=-1, warm=True):
                self._warm_active += 1

    def _warm_done(self, path_str: str, size: int) -> None:
        key = (path_str, size)
        if key in self._warm_pending:
            self._warm_pending.discard(key)
            self._warm_active -= 1
            self._pump_warm()

    def _on_thumb_ready(self, path_str, size, cache_file, phash) -> None:
        item = self._by_path.get(path_str)
        if item is not None:
            if phash and not item.phash:
                item.phash = phash
            self._repaint_row(path_str)
        self.wall_update.emit()
        self._pending_thumbs -= 1
        self._queued.discard((path_str, size))   # 任务已结束，允许再次排队
        self._warm_done(path_str, size)
        if self._scan_finished and self._pending_thumbs <= 0 and not self._dup_done:
            self._dup_done = True
            self.run_dup_detect()

    def _on_thumb_failed(self, path_str, size) -> None:
        self._pending_thumbs -= 1
        self._queued.discard((path_str, size))   # 失败也要释放，否则该项永久无法重试
        self._warm_done(path_str, size)
        item = self._by_path.get(path_str)
        if item is not None:
            # 单次失败可能只是网络盘抖动 / 磁盘暂时不可写。
            # 直接标 corrupted 会被 _submit_thumb 永久跳过（该图再也不重试、
            # 不上传、不查重），所以按次数累计，超过阈值才认定为损坏。
            item.thumb_failures = getattr(item, "thumb_failures", 0) + 1
            if item.thumb_failures >= 3:
                item.corrupted = True
            self._repaint_row(path_str)
            self.wall_update.emit()

    def _repaint_row(self, path_str: str) -> None:
        row = self.model.row_of_path(path_str)
        if row >= 0:
            self.model.dataChanged.emit(self.model.index(row), self.model.index(row))

    # ---------------- 最爱 ----------------
    def toggle_favorite(self, item) -> None:
        if self.favorites is None or self.trash_mode:
            return
        item.favorite = self.favorites.toggle(item.path)
        self._suppress_watch()      # favorites.json 写在库根，别触发整库重扫
        self._repaint_row(str(item.path))
        self.wall_update.emit()
        if self.fav_only and not item.favorite:
            self.refresh_view()
        self.status.emit("已加入最爱 ★" if item.favorite else "已取消最爱", 2000)
        self._queue_favorite_push(item)

    def _favorite_key(self, item) -> str:
        """收藏的跨机标识：用相对图库根目录的路径（与云端 oss_key 同规则）。"""
        try:
            return item.path.resolve().relative_to(
                self.main_root.resolve()).as_posix()
        except (ValueError, AttributeError):
            return item.path.name

    # ---- 推送队列：合并短时间内多次变更，后台线程发出，绝不阻塞 UI ----
    def _queue_favorite_push(self, item) -> None:
        """把一条收藏变更放进待推送队列。

        设计：UI 线程只更新内存与本地文件；网络请求交给后台 worker。
        短时间内多次点击会合并成一次批量推送（服务端支持 items 数组）。"""
        srv = self.share_server()
        if srv is None or self.trash_mode:
            return
        key = self._favorite_key(item)
        self._fav_pending[key] = {
            "key": key,
            "favorite": bool(item.favorite),
            "updated_at": int(time.time() * 1000),
        }
        # 300ms 内的连续操作合并成一次；期间只留最后一次状态（LWW 语义）
        self._fav_flush_timer.start()

    def _flush_favorite_push(self) -> None:
        """把待推送队列交给后台线程（每批最多 200 条）。"""
        if not self._fav_pending:
            return
        srv = self.share_server()
        if srv is None:
            self._fav_pending.clear()
            return
        items = list(self._fav_pending.values())
        self._fav_pending.clear()
        w = FavoriteSyncWorker(srv, items=items, pull=False)
        w.signals.finished.connect(
            lambda sent, failed: self._on_fav_pushed(sent, failed))
        self._track(w)
        self._fav_pool.start(w)

    def _on_fav_pushed(self, sent: int, failed: int) -> None:
        if failed:
            # 静默：本地是权威，下次双向同步会以 LWW 收敛
            self.status.emit(f"收藏云端同步失败 {failed} 条（本地已保存）", 3000)

    # ---- 双向同步 ----
    def sync_favorites(self, notify: bool = False) -> None:
        """与云端双向同步收藏：先推本地最新变更，再拉云端并 LWW 合并。

        全程在后台线程：网络慢不会卡住界面。"""
        srv = self.share_server()
        if srv is None or self.favorites is None or self.trash_mode:
            return
        if self._fav_syncing:
            return                       # 避免重入（扫描完成 + 手动触发）
        self._fav_syncing = True
        base = self.main_root
        if base is None:
            self._fav_syncing = False
            return

        # 本地全部收藏（含时间戳）先推上去，保证「本地有、云端无」的条目不会丢
        local_items = [
            {"key": k, "favorite": True, "updated_at": self.favorites.updated_at(k)}
            for k in self.favorites.keys()
        ]
        # 本机记录过的「取消收藏」也要推（用 0 时间戳无意义，直接不推，
        # 取消动作已在 toggle 时实时推送）
        w = FavoriteSyncWorker(srv, items=local_items, pull=True)
        w.signals.finished.connect(
            lambda sent, failed: self._on_fav_sync_done(w, sent, failed, notify))
        self._track(w)
        self._fav_pool.start(w)

    def _on_fav_sync_done(self, worker, sent: int, failed: int, notify: bool) -> None:
        self._fav_syncing = False
        pulled = getattr(worker, "pulled", [])
        if not pulled:
            if notify:
                self.status.emit(
                    f"收藏已同步（上传 {sent} 条）"
                    + (f"，{failed} 条失败" if failed else ""), 4000)
            return

        base = self.main_root
        changed = 0
        if base is not None:
            for rec in pulled:
                key = str(rec.get("key") or "")
                if not key:
                    continue
                fav = bool(rec.get("favorite"))
                ts = int(rec.get("updated_at") or 0)
                # 只应用「云端更新」的条目；本地更新更晚的保持不变
                if not self.favorites.set_state(key, fav, ts):
                    continue
                # UI 标志必须显式同步：favorite 只在扫描批次里设过一次，
                # refresh_view() 不会重算它（否则云端取消后界面仍显示星标）。
                target = self._by_path.get(str((base / key).resolve()))
                if target is not None:
                    target.favorite = fav
                changed += 1
        if changed:
            self.favorites.save()
            self.refresh_view()
            self.status.emit(f"已从云端同步 {changed} 条收藏变更", 4000)
        elif notify:
            self.status.emit(
                f"收藏已同步（上传 {sent} 条，无远端变更）"
                + (f"，{failed} 条失败" if failed else ""), 4000)

    # 兼容旧调用名
    def sync_favorites_from_server(self) -> int:
        self.sync_favorites()
        return 0

    # ---------------- 图片操作 ----------------
    def remove_item(self, item) -> None:
        if self.online_mode or item.remote_key:
            self.status.emit("在线模式不支持移出，云端删除请到 OSS 控制台操作", 5000)
            return
        if self.trash_mode:
            # 垃圾桶里的文件已经在 Remove/ 内，再移出会把它在 Remove/ 里改名，
            # 并往 .qx_removed.json 写一条指向 Remove/ 的原路径，还原就乱了
            self.status.emit("垃圾桶内的图片请用「还原」，不要再次移出", 4000)
            return
        self._suppress_watch()      # 移出会改库根目录，别触发整库重扫
        w = MoveWorker(item.path, self.main_root or self.root)
        w.signals.finished.connect(self._on_moved)
        w.signals.failed.connect(lambda p, m: self.status.emit(f"移出失败：{m}", 5000))
        self._track(w)
        self.move_pool.start(w)

    def _on_moved(self, src, dst) -> None:
        item = self._by_path.pop(src, None)
        if item is not None and item in self.all_items:
            self.all_items.remove(item)
        self.refresh_view()
        self.wall_update.emit()
        self.status.emit(f"已移入 Remove：{Path(dst).name}", 3000)

    # ---------------- 垃圾桶 ----------------
    def reload_current(self) -> None:
        """重新扫描当前目录（手动 F5 / 目录变更防抖自动触发）。"""
        if self.online_mode:
            self.set_online(True, force=True)
            return
        if self.root is not None:
            self.status.emit("正在刷新…", 0)
            self.load_directory(self.root, trash=self.trash_mode)
    def set_trash_mode(self, on: bool) -> None:
        if on == self.trash_mode or self.main_root is None:
            return
        if on:
            self.load_directory(self.main_root / file_ops.REMOVE_DIR, trash=True)
        else:
            self.load_directory(self.main_root)

    def restore_item(self, item) -> None:
        self._suppress_watch()
        w = MoveWorker(item.path, self.main_root or self.root, restore=True)
        w.signals.finished.connect(self._on_restored)
        w.signals.failed.connect(lambda p, m: self.status.emit(f"还原失败：{m}", 5000))
        self._track(w)
        self.move_pool.start(w)

    def _on_restored(self, src, dst) -> None:
        item = self._by_path.pop(src, None)
        if item is not None and item in self.all_items:
            self.all_items.remove(item)
        self.refresh_view()
        self.wall_update.emit()
        self.status.emit(f"已还原：{Path(dst).name}", 3000)

    def keep_one(self, group, by: str) -> None:
        """重复组一键保留：by = 'size' | 'mtime'。
        本地模式其余可逆移出；在线模式其余云端删除（不可逆，UI 层需先确认）。"""
        keep = max(group, key=lambda i: i.size_bytes if by == "size" else i.mtime)
        rest = [it for it in group if it is not keep]
        if self.online_mode:
            self.remove_online_items(rest)
            self.status.emit(
                f"已保留{'最大' if by == 'size' else '最新'}，其余 {len(rest)} 张云端删除中…", 3000)
            return
        for it in rest:
            self.remove_item(it)
        self.status.emit(f"已保留{'最大' if by == 'size' else '最新'}，其余移出", 3000)

    def batch_keep(self, actives: list, by: str) -> None:
        """跨组批处理：每组保留一张（by='size'|'mtime'），其余移出/删除。
        actives: 每组的候选列表（已剔除排除项）。"""
        rest = []
        for active in actives:
            keep = max(active,
                       key=lambda i: i.size_bytes if by == "size" else i.mtime)
            rest.extend(it for it in active if it is not keep)
        if not rest:
            return
        if self.online_mode:
            self.remove_online_items(rest)
            self.status.emit(
                f"批处理 {len(actives)} 组：每组保留"
                f"{'最大' if by == 'size' else '最新'}，"
                f"其余 {len(rest)} 张云端删除中…", 5000)
            return
        for it in rest:
            self.remove_item(it)
        self.status.emit(
            f"批处理 {len(actives)} 组：每组保留"
            f"{'最大' if by == 'size' else '最新'}，其余 {len(rest)} 张移出", 3000)

    def remove_online_items(self, items) -> None:
        """删除云端对象并同步清理本地索引/视图（不可逆）。"""
        if not self.online_mode or self.oss is None or not items:
            return
        keymap = {str(it.path): it.remote_key for it in items if it.remote_key}
        w = OnlineDeleteWorker(self.oss, list(items),
                               is_cancelled=self.is_cancelled)
        w.signals.finished.connect(lambda ps: self._on_online_deleted(ps, keymap))
        w.signals.failed.connect(
            lambda p, m: self.status.emit(f"云端删除失败：{friendly_error(m)}", 8000))
        self._track(w)
        self.move_pool.start(w)

    def _on_online_deleted(self, paths, keymap) -> None:
        deleted_keys = {keymap.get(p) for p in paths}
        for p in paths:
            item = self._by_path.pop(p, None)
            if item is not None and item in self.all_items:
                self.all_items.remove(item)
        # 清理增量上传索引中指向已删对象的记录，避免后续上传误跳过
        stale = [ck for ck, rec in self.oss_index.data.items()
                 if rec.get("key") in deleted_keys]
        for ck in stale:
            del self.oss_index.data[ck]
        if stale:
            self.oss_index.save()
        self.refresh_view()
        self.wall_update.emit()
        self.status.emit(f"已删除 {len(paths)} 张云端重复图片", 3000)

    def save_item(self, item) -> bool:
        dest = self.settings.default_save_dir
        if not dest:
            return False  # 由主窗体弹目录对话框
        try:
            dst = file_ops.save_as(item.path, Path(dest))
            self.status.emit(f"已保存：{dst.name}", 3000)
        except Exception as exc:
            self.status.emit(f"保存失败：{exc}", 5000)
        return True

    def copy_item(self, item) -> None:
        pix = self.fast_pixmap(item)
        if not pix.isNull():
            file_ops.copy_pixmap(pix)
            self.status.emit("已复制图片到剪贴板", 2000)

    def reveal_item(self, item) -> None:
        file_ops.reveal_in_explorer(item.path)

    # ---------------- 大图浏览 ----------------
    def fast_pixmap(self, item) -> QPixmap:
        if self.cache_root is None:
            return QPixmap()
        for tier in (512, 256):
            fp = thumbnail.thumb_path(self.cache_root, item, tier)
            if fp.exists():
                pix = QPixmap(str(fp))
                if not pix.isNull():
                    return pix
        return QPixmap()

    def item_by_path(self, path_str: str):
        return self._by_path.get(path_str)

    def request_decode(self, item, callback) -> None:
        w = DecodeWorker(item, is_cancelled=self.is_cancelled,
                         oss=self.oss if item.remote_key else None)
        if callback is not None:
            w.signals.ready.connect(callback)
        w.signals.failed.connect(lambda p, m: self.status.emit(f"原图解码失败：{m}", 3000))
        self._track(w)
        self.pool.start(w)

    # ---------------- 查重 ----------------
    def find_duplicates(self, show_dialog: bool = True) -> None:
        self._show_dup_dialog = show_dialog
        self.status.emit("正在比对 pHash…", 0)
        self.run_dup_detect()

    def run_dup_detect(self) -> None:
        w = HashWorker(self.all_items, self.settings.dup_threshold,
                       image_root=self.cache_root,
                       oss=self.oss if self.online_mode else None,
                       is_cancelled=self.is_cancelled)
        w.signals.finished.connect(self._on_dups)
        w.signals.progress.connect(
            lambda d, t: self.status.emit(f"正在计算指纹 {d}/{t}…", 0))
        w.signals.failed.connect(
            lambda m: self.status.emit(f"查重失败：{m}", 5000))
        self._track(w)
        self.pool.start(w)

    # ---------------- 缓存管理 ----------------
    def is_cancelled(self) -> bool:
        return self._cancelled

    def request_cancel(self) -> None:
        """关闭时调用：通知工作线程尽快退出，避免退出期阻塞。"""
        self._cancelled = True

    # ---------------- OSS 在线库 ----------------
    def _sync_oss_index(self) -> None:
        """索引与云端 key 缓存按 Bucket 隔离，换桶后不误用旧桶记录。"""
        bucket = self.settings.oss_bucket if self.oss_configured() else ""
        if bucket == self._index_bucket:
            return
        self._index_bucket = bucket
        self.oss_index = OssIndex(bucket)
        self._cloud_keys = None

    def oss_configured(self) -> bool:
        s = self.settings
        return bool(s.oss_endpoint and s.oss_bucket and s.oss_ak_id
                    and s.oss_ak_secret)

    def build_oss(self) -> OssLibrary:
        s = self.settings
        self._sync_oss_index()
        return OssLibrary(s.oss_endpoint, s.oss_bucket, s.oss_ak_id,
                          s.oss_ak_secret)

    def set_online(self, on: bool, force: bool = False) -> bool:
        if on and not force and self.online_mode:
            return True
        if not on and not self.online_mode:
            return True
        if on:
            if not self.oss_configured():
                self.status.emit("请先在「上传到云」中配置 OSS", 5000)
                return False
            self._sync_oss_index()
            try:
                self.oss = self.build_oss()
            except Exception as exc:
                self.status.emit(f"OSS 初始化失败：{exc}", 5000)
                return False
            self.online_mode = True
            self.trash_mode = False
            self._load_seq += 1
            self._cancelled = False
            self.root = Path("oss://" + self.settings.oss_bucket)
            self.cache_root = thumbnail.cache_root_for(
                Path("oss@" + self.settings.oss_bucket))
            self.all_items.clear()
            self._by_path.clear()
            self._queued.clear()
            self._pending_thumbs = 0
            self._scan_finished = False
            self._dup_done = False
            self.favorites = None
            self.delegate.image_root = self.cache_root
            self._watcher.removePaths(self._watcher.directories())
            self.status.emit("正在列出在线库…", 0)
            w = ListWorker(self.oss, is_cancelled=self.is_cancelled)
            w.signals.batch.connect(self._on_online_batch)
            w.signals.finished.connect(self._on_online_done)
            w.signals.failed.connect(
                lambda m: self.status.emit(
                    f"在线库列表失败：{friendly_error(m)}", 8000))
            self._track(w)
            self.pool.start(w)
            return True
        # 切回本地
        self.online_mode = False
        self.oss = None
        if self.main_root is not None:
            self.load_directory(self.main_root)
        return True

    def _on_online_batch(self, rows) -> None:
        for key, size, mtime, w, h in rows:
            it = ImageItem(path=Path(key), size_bytes=size,
                           mtime=float(mtime), width=w, height=h,
                           remote_key=key)
            self.all_items.append(it)
            self._by_path[str(it.path)] = it
        self.refresh_view()
        self.status.emit(f"已加载 {len(self.all_items)} 张…", 0)

    def _on_online_done(self, total) -> None:
        self._scan_finished = True
        total_size = sum(i.size_bytes for i in self.all_items)
        self.title_changed.emit(
            f"千寻影集 — 在线 {total} 张 · 共 {human_size(total_size)}")
        self.status.emit(f"在线库加载完成：{total} 张", 5000)
        self.refresh_view()
        self.scan_done.emit()
        self._warm_all_thumbs()

    def create_upload_worker(self):
        """本地模式：生成增量上传任务。返回 (worker, 待传数, 跳过数)。

        跳过三类：本地索引已传、云端已存在（一次列举）、
        批内同内容重复（size+pHash 相同且设置开启时）。"""
        if self.online_mode or self.main_root is None:
            return None, 0, 0
        if not self.oss_configured():
            return None, 0, 0
        self._sync_oss_index()
        oss = self.build_oss()
        existing = oss.list_keys()
        skip_dups = self.settings.upload_skip_dups
        tasks = []
        skipped = 0
        outside = 0                     # 不在库内的文件：不能猜 key（会同名覆盖）
        seen: dict[tuple, bool] = {}
        used_keys: dict[str, Path] = {}  # key -> 首个占用者，检测批内撞键
        for it in self.all_items:
            if it.remote_key or it.corrupted:
                continue
            ck = thumbnail.cache_key(it)
            try:
                rel = it.path.resolve().relative_to(
                    self.main_root.resolve()).as_posix()
            except ValueError:
                outside += 1
                continue                # 跳过而不是退化成文件名
            key = OssIndex.make_key(rel)
            if key in used_keys:
                skipped += 1            # 批内撞键：保留先到的，避免互相覆盖
                continue
            used_keys[key] = it.path
            if self.oss_index.get(ck) or key in existing:
                if skip_dups and it.phash:
                    seen[(it.size_bytes, it.phash)] = True
                skipped += 1
                continue
            if skip_dups and it.phash:
                ident = (it.size_bytes, it.phash)
                if ident in seen:
                    skipped += 1
                    continue
                seen[ident] = True
            tasks.append((it.path, rel, ck))
        if outside:
            self.status.emit(
                f"有 {outside} 个文件不在当前图库目录内，已跳过上传（避免云端路径冲突）", 6000)
        w = UploadWorker(oss, self.oss_index, tasks,
                         is_cancelled=self.is_cancelled,
                         threads=self.settings.upload_threads)
        self._track(w)
        return w, len(tasks), skipped

    def _rel_key(self, item) -> str:
        """本地项对应的云端对象 key（与上传路径同一规则）。

        不在库内的文件（`relative_to` 失败）**绝不退化成文件名**：
        不同子目录下的同名图会算出同一个 key（qx/x.jpg），上传时互相覆盖。"""
        try:
            rel = item.path.resolve().relative_to(
                self.main_root.resolve()).as_posix()
        except (ValueError, AttributeError):
            return ""      # 调用方需处理空 key（跳过并提示），不能猜
        return OssIndex.make_key(rel)

    def resolve_cloud_key(self, item):
        """解析项的云端 key：remote_key → 本地索引 → 云端清单匹配（补登索引）。"""
        self._sync_oss_index()
        if item.remote_key:
            return item.remote_key
        rec = self.oss_index.get(thumbnail.cache_key(item))
        if rec:
            return rec["key"]
        oss = self._share_oss()
        if oss is None:
            return None
        if self._cloud_keys is None:
            try:
                self._cloud_keys = oss.list_keys()
            except Exception as exc:
                # 不要把「列举失败」降级成「云盘为空」并永久缓存：
                # 那会让之后所有分享都误报「尚未上传」。保持 None 以便下次重试。
                self.status.emit(f"云端清单获取失败：{friendly_error(exc)}", 6000)
                return None
        key = self._rel_key(item)
        if not key:
            return None
        if key in self._cloud_keys:
            self.oss_index.put(thumbnail.cache_key(item), key,
                               item.size_bytes, item.mtime)
            self.oss_index.save()
            return key
        return None

    def _share_oss(self):
        try:
            return self.oss if self.online_mode else (
                self.build_oss() if self.oss_configured() else None)
        except Exception:
            return None

    def share_server(self):
        """惰性构造分享服务端客户端（未启用/未配置时返回 None）。"""
        s = self.settings
        if not s.server_enabled or not s.server_base or not s.server_secret:
            return None
        if self._share_srv is None:
            from .core.share_server import ShareServer
            self._share_srv = ShareServer(s.server_base, s.server_secret)
        return self._share_srv

    def share_short_link(self, item) -> str | None:
        """通过服务端创建可撤销短链；失败返回 None 并把原因写进 share_error。

        未启用服务端时返回 None，由 UI 回退到直接签名外链。"""
        srv = self.share_server()
        if srv is None:
            return None
        self.share_error = ""
        key = self.resolve_cloud_key(item)
        if not key:
            self.share_error = "该图片尚未上传到云，无法生成短链"
            return None
        ok, res = srv.create_share(key, item.path.name)
        if not ok:
            self.share_error = str(res)
            return None
        return res

    def revoke_short_links(self, item) -> int:
        """按图片批量撤销其所有短链，返回撤销条数。"""
        srv = self.share_server()
        if srv is None:
            return 0
        key = self.resolve_cloud_key(item)
        if not key:
            return 0
        ok, n = srv.revoke_by_key(key)
        if not ok:
            self.status.emit(f"撤销失败：{n}", 6000)
            return 0
        return n

    def share_link(self, item, permanent: bool = False) -> str | None:
        """签名外链（≤7 天）；permanent=True 时对象设公共读，返回永久直链。

        失败时在 share_error / share_blocked 留下原因，供 UI 提示或降级。"""
        self.share_error = ""
        self.share_blocked = False
        oss = self._share_oss()
        if oss is None:
            self.status.emit("请先配置 OSS", 5000)
            return None
        key = self.resolve_cloud_key(item)
        if not key:
            self.status.emit("该图片尚未上传到云", 3000)
            return None
        if permanent:
            try:
                oss.make_public(key)
                return oss.public_url(key)
            except Exception as exc:
                self.share_error = friendly_error(exc)
                self.share_blocked = is_block_public_error(exc)
                self.status.emit(f"设置公共读失败：{self.share_error}", 8000)
                return None
        return oss.sign(key, self.settings.share_days * 24 * 3600)

    def revoke_share(self, item) -> bool:
        """撤回永久公开（对象恢复继承桶私有）。"""
        oss = self._share_oss()
        key = self.resolve_cloud_key(item) if oss else None
        if not oss or not key:
            return False
        try:
            oss.revoke_public(key)
            return True
        except Exception as exc:
            self.status.emit(f"撤回公共读失败：{friendly_error(exc)}", 8000)
            return False

    def upload_one(self, item) -> bool:
        """单张同步上传（忙等光标），成功后补登索引/云端缓存。"""
        oss = self._share_oss()
        if oss is None or self.main_root is None:
            self.status.emit("请先配置 OSS", 5000)
            return False
        ck = thumbnail.cache_key(item)
        key = self._rel_key(item)
        if not key:
            self.status.emit("该图片不在当前图库目录内，无法确定云端路径", 5000)
            return False
        w = UploadWorker(oss, self.oss_index, [(item.path, key[len("qx/"):], ck)],
                         is_cancelled=self.is_cancelled, threads=1)
        loop = QEventLoop()
        result = {"up": 0}
        w.signals.finished.connect(lambda up, fail: (result.update(up=up), loop.quit()))
        self._track(w)
        self.pool.start(w)
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            loop.exec()
        finally:
            QApplication.restoreOverrideCursor()
        if result["up"]:
            if self._cloud_keys is not None:
                self._cloud_keys.add(key)
            self.status.emit("上传完成", 3000)
            return True
        self.status.emit("上传失败", 5000)
        return False

    def cache_info(self) -> tuple[int, int]:
        """返回 (文件数, 总字节)。"""
        if self.cache_root is None:
            return 0, 0
        n = b = 0
        base = thumbnail.cache_root_for(self.cache_root)
        try:
            for f in base.rglob("*.jpg"):
                n += 1
                b += f.stat().st_size
        except OSError:
            pass
        return n, b

    def clean_cache_orphans(self) -> int:
        """删除当前库中已不存在图片的孤儿缓存，返回删除数。

        安全前置：垃圾桶模式下 cache_root 仍是主库，而 all_items 只有 Remove/
        里的几张——此时算出的 valid 集合极小，会把主库全部缓存误判为孤儿删光。
        扫描未完成时同理（还没扫到的图片会被当成已删除）。"""
        if self.cache_root is None or self.trash_mode or not self._scan_finished:
            return 0
        valid = {thumbnail.cache_key(it) for it in self.all_items}
        removed = 0
        base = thumbnail.cache_root_for(self.cache_root)
        if not base.exists():
            return 0
        for tier_dir in base.iterdir():
            if not tier_dir.is_dir():
                continue
            for f in tier_dir.glob("*.jpg"):
                if f.stem not in valid:
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
        return removed

    def clean_cache_all(self) -> None:
        if self.cache_root is not None:
            shutil.rmtree(thumbnail.cache_root_for(self.cache_root),
                          ignore_errors=True)
        # 在线原图临时缓存也一起清掉（此前完全没有清理入口）
        from .core.oss_service import app_data_dir
        shutil.rmtree(app_data_dir() / "originals", ignore_errors=True)

    def originals_info(self) -> tuple[int, int]:
        """在线原图临时缓存的 (文件数, 总字节)。"""
        from .core.oss_service import app_data_dir
        d = app_data_dir() / "originals"
        n = b = 0
        if not d.exists():
            return 0, 0
        try:
            for f in d.iterdir():
                if f.is_file():
                    n += 1
                    b += f.stat().st_size
        except OSError:
            pass
        return n, b

    def _on_dups(self, groups) -> None:
        for gi, g in enumerate(groups):
            for it in g:
                it.dup_group = gi
        if self.model.rowCount():
            self.model.dataChanged.emit(
                self.model.index(0), self.model.index(self.model.rowCount() - 1))
        self.wall_update.emit()
        if groups:
            self.status.emit(f"发现 {len(groups)} 组疑似重复", 5000)
        elif self._show_dup_dialog:
            self.status.emit("未发现疑似重复图片", 3000)
        if self._show_dup_dialog:
            self.dups_ready.emit(groups)
            self._show_dup_dialog = False
