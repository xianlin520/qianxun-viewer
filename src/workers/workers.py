# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""工作线程层：QRunnable + Qt 信号回传结果，禁止跨线程直接操作 UI。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from ..core import duplicates, scanner, thumbnail
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
                 is_cancelled=None):
        super().__init__()
        self.image_root = image_root
        self.item = item
        self.size = size
        self.with_phash = with_phash
        self.is_cancelled = is_cancelled
        self.signals = ThumbSignals()

    def run(self):
        if self.is_cancelled and self.is_cancelled():
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
    def __init__(self, item, is_cancelled=None):
        super().__init__()
        self.item = item
        self.is_cancelled = is_cancelled
        self.signals = DecodeSignals()

    def run(self):
        if self.is_cancelled and self.is_cancelled():
            return
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
    def __init__(self, items):
        super().__init__()
        self.items = items
        self.signals = HashSignals()

    def run(self):
        _emit(self.signals.finished, duplicates.find_groups(self.items))


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
