# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""工作线程层：QRunnable + Qt 信号回传结果，禁止跨线程直接操作 UI。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from ..core import duplicates, scanner, thumbnail
from ..core.oss_service import app_data_dir
from ..utils import file_ops


def _emit(sig, *args) -> None:
    """退出期接收端可能先于线程销毁，静默忽略 RuntimeError。"""
    try:
        sig.emit(*args)
    except RuntimeError:
        pass


class ScanSignals(QObject):
    batch = Signal(list, int)      # 本批 items, 累计错误数
    finished = Signal(int, int)    # 总数, 错误数
    failed = Signal(str)


class ScanWorker(QRunnable):
    def __init__(self, root: Path, is_cancelled=None):
        super().__init__()
        self.root = root
        self.is_cancelled = is_cancelled
        self.signals = ScanSignals()

    def run(self):
        try:
            total = errors = 0
            for batch, errs in scanner.scan_batches(self.root):
                if self.is_cancelled and self.is_cancelled():
                    return
                errors += errs
                total += len(batch)
                _emit(self.signals.batch, batch, errors)
            _emit(self.signals.finished, total, errors)
        except Exception as exc:  # 目录被占用等
            _emit(self.signals.failed, str(exc))


class ThumbSignals(QObject):
    ready = Signal(str, int, str, str)   # item 路径, 档位, 缓存文件, phash
    failed = Signal(str, int)


class ThumbWorker(QRunnable):
    def __init__(self, image_root: Path, item, size: int, with_phash: bool = False,
                 is_cancelled=None, oss=None):
        super().__init__()
        self.image_root = image_root
        self.item = item
        self.size = size
        self.with_phash = with_phash
        self.is_cancelled = is_cancelled
        self.oss = oss
        self.signals = ThumbSignals()

    def run(self):
        if self.is_cancelled and self.is_cancelled():
            return
        if self.item.remote_key and self.oss is not None:
            # 在线项：下载 OSS IMG 处理结果作为缩略图
            out = thumbnail.thumb_path(self.image_root, self.item, self.size)
            if not out.exists():
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    self.oss.download_to(self.item.remote_key, out,
                                         thumb=self.size)
                except Exception:
                    self.signals.failed.emit(str(self.item.path), self.size)
                    return
            ph = thumbnail.phash_of_file(out) if self.with_phash else ""
            self.signals.ready.emit(str(self.item.path), self.size, str(out), ph)
            return
        out, ph = thumbnail.generate(self.image_root, self.item, self.size, self.with_phash)
        if out is not None:
            _emit(self.signals.ready, str(self.item.path), self.size, str(out), ph)
        else:
            _emit(self.signals.failed, str(self.item.path), self.size)


class DecodeSignals(QObject):
    ready = Signal(str, object)   # item 路径, QImage
    failed = Signal(str, str)


class DecodeWorker(QRunnable):
    def __init__(self, item, is_cancelled=None, oss=None):
        super().__init__()
        self.item = item
        self.is_cancelled = is_cancelled
        self.oss = oss
        self.signals = DecodeSignals()

    def run(self):
        if self.is_cancelled and self.is_cancelled():
            return
        if self.item.remote_key and self.oss is not None:
            dest = app_data_dir() / "originals" / \
                f"{thumbnail.cache_key(self.item)}.orig"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    self.oss.download_to(self.item.remote_key, dest)
            except Exception:
                _emit(self.signals.failed, str(self.item.path), "下载原图失败")
                return
            im = thumbnail.decode_original(dest)
        else:
            im = thumbnail.decode_original(self.item.path)
        if im is None:
            _emit(self.signals.failed, str(self.item.path), "解码失败或文件损坏")
            return
        data = im.tobytes("raw", "RGB")
        qimg = QImage(data, im.width, im.height, im.width * 3,
                      QImage.Format.Format_RGB888).copy()
        _emit(self.signals.ready, str(self.item.path), qimg)


class HashSignals(QObject):
    finished = Signal(list)   # 重复组 list[list[ImageItem]]


class HashWorker(QRunnable):
    def __init__(self, items, threshold: int = 4):
        super().__init__()
        self.items = items
        self.threshold = threshold
        self.signals = HashSignals()

    def run(self):
        _emit(self.signals.finished,
              duplicates.find_groups(self.items, self.threshold))


class ListSignals(QObject):
    batch = Signal(list)          # [(key, size, mtime, w, h), ...]
    finished = Signal(int)
    failed = Signal(str)


class ListWorker(QRunnable):
    """在线库列表：列对象 + 并发取宽高。"""

    def __init__(self, oss, is_cancelled=None):
        super().__init__()
        self.oss = oss
        self.is_cancelled = is_cancelled
        self.signals = ListSignals()

    def run(self):
        try:
            rows = self.oss.list_images()
            for i in range(0, len(rows), 64):
                if self.is_cancelled and self.is_cancelled():
                    return
                self.signals.batch.emit(rows[i:i + 64])
            self.signals.finished.emit(len(rows))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class UploadSignals(QObject):
    progress = Signal(int, int, str)   # 完成, 总数, 当前文件名
    finished = Signal(int)             # 成功上传数
    failed = Signal(str)


class UploadWorker(QRunnable):
    """批量增量上传；tasks: [(local, rel, ck), ...]。"""

    def __init__(self, oss, index, tasks, is_cancelled=None):
        super().__init__()
        self.oss = oss
        self.index = index
        self.tasks = tasks
        self.is_cancelled = is_cancelled
        self.signals = UploadSignals()

    def run(self):
        from ..core.oss_service import OssIndex
        uploaded = 0
        total = len(self.tasks)
        for i, (local, rel, ck) in enumerate(self.tasks):
            if self.is_cancelled and self.is_cancelled():
                break
            key = OssIndex.make_key(rel)
            try:
                self.oss.upload(local, key)
                st = local.stat()
                self.index.put(ck, key, st.st_size, st.st_mtime)
                self.index.save()
                uploaded += 1
            except Exception:
                pass
            self.signals.progress.emit(i + 1, total, local.name)
        self.signals.finished.emit(uploaded)


class MoveSignals(QObject):
    finished = Signal(str, str)   # 原路径, 新路径
    failed = Signal(str, str)

class MoveWorker(QRunnable):
    def __init__(self, src: Path, image_root: Path, restore: bool = False):
        super().__init__()
        self.src = src
        self.image_root = image_root
        self.restore = restore
        self.signals = MoveSignals()

    def run(self):
        try:
            if self.restore:
                dst = file_ops.restore_from_remove(self.src, self.image_root)
            else:
                dst = file_ops.move_to_remove(self.src, self.image_root)
            _emit(self.signals.finished, str(self.src), str(dst))
        except Exception as exc:
            _emit(self.signals.failed, str(self.src), str(exc))
