# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""控制层：加载 / 排序 / 分页 / 筛选 / 缩略图调度 / 操作分发。"""
from __future__ import annotations

import math
import random
import shutil
import zlib
from collections import deque
from pathlib import Path

from PySide6.QtCore import (QFileSystemWatcher, QObject, QThreadPool, QTimer,
                            Signal)
from PySide6.QtGui import QPixmap

from .core import thumbnail
from .core.favorites import FavoritesStore
from .core.image_item import ImageItem
from .core.oss_service import SHARE_EXPIRES, OssIndex, OssLibrary
from .core.settings import AppSettings
from .utils import file_ops
from .utils.format import human_size
from .workers.workers import (DecodeWorker, HashWorker, ListWorker, MoveWorker,
                              ScanWorker, ThumbWorker, UploadWorker)

SORT_MODES = [("random", "随机"), ("time_asc", "时间正序"), ("time_desc", "时间倒序"),
              ("size_asc", "大小正序"), ("size_desc", "大小倒序")]

ASPECT_TOL = 0.10          # 长宽比容差（对数距离，约 ±10%）
ASPECT_PRESETS = ["全部", "1:1", "4:3", "3:2", "16:9", "2:1",
                  "3:4", "2:3", "9:16", "1:2"]


def parse_aspect(text: str):
    """解析 'a:b' 或单个浮点（宽/高）；无效/全部 返回 None。"""
    text = (text or "").strip()
    if not text or text in ("全部", "all", "*"):
        return None
    try:
        if ":" in text:
            a, b = text.split(":", 1)
            a, b = float(a), float(b)
            return a / b if a > 0 and b > 0 else None
        v = float(text)
        return v if v > 0 else None
    except ValueError:
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
        self.per_page = 1
        self._seed_extra = 0
        self._by_path: dict[str, ImageItem] = {}
        self._queued: set[tuple[str, int]] = set()
        self._pending_thumbs = 0
        self._scan_finished = False
        self._dup_done = False
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

        # 目录变更监听：防抖后自动重扫
        self._watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self.reload_current)
        self._watcher.directoryChanged.connect(lambda _p: self._reload_timer.start())

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
        self.favorites = FavoritesStore(path)
        self.delegate.image_root = self.cache_root
        self._watcher.removePaths(self._watcher.directories())
        self._watcher.addPath(str(path))
        self.status.emit(f"正在扫描 {path} …", 0)
        w = ScanWorker(path, is_cancelled=self.is_cancelled)
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
        self.refresh_view()
        self.status.emit(f"已加载 {len(self.all_items)} 张…", 0)

    def _on_scan_done(self, total, errors, seq: int) -> None:
        if seq != self._load_seq:
            return
        self._scan_finished = True
        total_size = sum(i.size_bytes for i in self.all_items)
        prefix = "垃圾桶 — " if self.trash_mode else ""
        self.title_changed.emit(
            f"千寻图片查看器 — {prefix}{total} 张 · 共 {human_size(total_size)}")
        msg = f"扫描完成：{total} 张图片"
        if errors:
            msg += f"，{errors} 个文件读取失败已跳过"
        self.status.emit(msg, 5000)
        self.refresh_view()
        self.scan_done.emit()
        self._warm_all_thumbs()

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
            items = [i for i in items
                     if self._item_folder(i) == ff
                     or self._item_folder(i).startswith(ff + "/")]
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
        """返回项的相对父目录（posix）；在线项用 object key 父路径。"""
        if item.remote_key:
            return "/".join(item.remote_key.split("/")[:-1])
        base = self.main_root if not self.online_mode else None
        if base is not None:
            try:
                return item.path.resolve().relative_to(
                    base.resolve()).parent.as_posix()
            except ValueError:
                return ""
        return ""

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
            # 固定种子：同目录同批加载结果稳定；"重新随机"换种子
            seed = (zlib.crc32(str(self.root).encode("utf-8", "surrogatepass"))
                    + self._seed_extra) & 0xFFFFFFFF
            random.Random(seed).shuffle(items)
        return items

    def _apply_to_model(self) -> None:
        self.model.info_mode = (
            "size" if self.sort_mode.startswith("size")
            else "time" if self.sort_mode.startswith("time") else "random")
        if self.view_mode == "page":
            self.per_page = max(1, self.view.page_capacity())
            total = max(1, -(-len(self.view_items) // self.per_page))
            self.page = max(0, min(self.page, total - 1))
            shown = self.view_items[self.page * self.per_page:(self.page + 1) * self.per_page]
            self.model.set_items(shown)
            self.view.pager.set_state(self.page, total)
        else:
            self.model.set_items(self.view_items)
        self.view_reset.emit()

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
        self.page = max(0, page)
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
        self._warm_done(path_str, size)
        if self._scan_finished and self._pending_thumbs <= 0 and not self._dup_done:
            self._dup_done = True
            self.run_dup_detect()

    def _on_thumb_failed(self, path_str, size) -> None:
        self._pending_thumbs -= 1
        self._warm_done(path_str, size)
        item = self._by_path.get(path_str)
        if item is not None:
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
        self._repaint_row(str(item.path))
        self.wall_update.emit()
        if self.fav_only and not item.favorite:
            self.refresh_view()
        self.status.emit("已加入最爱 ★" if item.favorite else "已取消最爱", 2000)

    # ---------------- 图片操作 ----------------
    def remove_item(self, item) -> None:
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
        """重复组一键保留：by = 'size' | 'mtime'，其余移出。"""
        keep = max(group, key=lambda i: i.size_bytes if by == "size" else i.mtime)
        for it in group:
            if it is not keep:
                self.remove_item(it)
        self.status.emit(f"已保留{'最大' if by == 'size' else '最新'}，其余移出", 3000)

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
        w = HashWorker(self.all_items, self.settings.dup_threshold)
        w.signals.finished.connect(self._on_dups)
        self._track(w)
        self.pool.start(w)

    # ---------------- 缓存管理 ----------------
    def is_cancelled(self) -> bool:
        return self._cancelled

    def request_cancel(self) -> None:
        """关闭时调用：通知工作线程尽快退出，避免退出期阻塞。"""
        self._cancelled = True

    # ---------------- OSS 在线库 ----------------
    def oss_configured(self) -> bool:
        s = self.settings
        return bool(s.oss_endpoint and s.oss_bucket and s.oss_ak_id
                    and s.oss_ak_secret)

    def build_oss(self) -> OssLibrary:
        s = self.settings
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
                lambda m: self.status.emit(f"在线库列表失败：{m}", 5000))
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
            f"千寻图片查看器 — 在线 {total} 张 · 共 {human_size(total_size)}")
        self.status.emit(f"在线库加载完成：{total} 张", 5000)
        self.refresh_view()
        self.scan_done.emit()
        self._warm_all_thumbs()

    def create_upload_worker(self):
        """本地模式：生成增量上传任务。返回 (worker, 待传数, 跳过数)。"""
        if self.online_mode or self.main_root is None:
            return None, 0, 0
        if not self.oss_configured():
            return None, 0, 0
        oss = self.build_oss()
        tasks = []
        skipped = 0
        for it in self.all_items:
            if it.remote_key or it.corrupted:
                continue
            ck = thumbnail.cache_key(it)
            if self.oss_index.get(ck):
                skipped += 1
                continue
            try:
                rel = it.path.resolve().relative_to(
                    self.main_root.resolve()).as_posix()
            except ValueError:
                rel = it.path.name
            tasks.append((it.path, rel, ck))
        w = UploadWorker(oss, self.oss_index, tasks,
                         is_cancelled=self.is_cancelled)
        self._track(w)
        return w, len(tasks), skipped

    def share_link(self, item) -> str | None:
        """返回 ≤7 天签名外链；本地项未上传时返回 None 并提示。"""
        try:
            oss = self.oss if self.online_mode else (
                self.build_oss() if self.oss_configured() else None)
        except Exception:
            oss = None
        if oss is None:
            self.status.emit("请先配置 OSS", 5000)
            return None
        key = item.remote_key
        if not key:
            rec = self.oss_index.get(thumbnail.cache_key(item))
            if not rec:
                self.status.emit("该图片尚未上传到云，请先「上传到云」", 5000)
                return None
            key = rec["key"]
        return oss.sign(key, SHARE_EXPIRES)

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
        """删除当前库中已不存在图片的孤儿缓存，返回删除数。"""
        if self.cache_root is None:
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
