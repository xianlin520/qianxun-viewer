# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""缓存管理对话框：查看本地缓存占用，清理孤儿/全部缓存。"""
from __future__ import annotations

from PySide6.QtGui import QPixmapCache
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import thumbnail
from ..utils.format import human_size


class CacheDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("缩略图缓存管理")
        self.controller = controller
        lay = QVBoxLayout(self)
        self.label = QLabel()
        lay.addWidget(self.label)

        btn_orphan = QPushButton("清理孤儿缓存（当前库已不存在图片的缓存）")
        btn_all = QPushButton("清空当前目录全部缓存")
        btn_close = QPushButton("关闭")
        row = QHBoxLayout()
        row.addWidget(btn_orphan)
        row.addWidget(btn_all)
        row.addWidget(btn_close)
        lay.addLayout(row)

        btn_orphan.clicked.connect(self._clean_orphans)
        btn_all.clicked.connect(self._clean_all)
        btn_close.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        n, b = self.controller.cache_info()
        root = self.controller.cache_root
        loc = thumbnail.cache_root_for(root) if root else "—"
        self.label.setText(f"本地缓存目录：{loc}\n"
                           f"共 {n} 个文件 · 占用 {human_size(b)}\n"
                           f"（缓存不写入图片目录，云同步不产生流量）")

    def _clean_orphans(self) -> None:
        removed = self.controller.clean_cache_orphans()
        QPixmapCache.clear()
        self.controller.wall_update.emit()
        self._refresh()
        self.label.setText(self.label.text() + f"\n已清理孤儿缓存 {removed} 个。")

    def _clean_all(self) -> None:
        self.controller.clean_cache_all()
        QPixmapCache.clear()
        self.controller.wall_update.emit()
        self._refresh()
        self.label.setText(self.label.text() + "\n已清空全部缓存，浏览时将自动重建。")
