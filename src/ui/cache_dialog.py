# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""缓存管理对话框：查看本地缓存占用，清理孤儿/全部缓存。"""
from __future__ import annotations

from PySide6.QtGui import QPixmapCache
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

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

    def _refresh(self, extra: str = "") -> None:
        """统一刷新文案。

        原实现在按钮槽里用 `self.label.setText(self.label.text() + ...)` 追加，
        连点两次「清理孤儿缓存」提示就叠成两行重复文案，也取不到干净数值。
        现在状态只在 _refresh 里写一次，附加说明作为参数传入。
        """
        n, b = self.controller.cache_info()
        root = self.controller.cache_root
        loc = thumbnail.cache_root_for(root) if root else "—"
        on, ob = self.controller.originals_info()
        text = (f"本地缓存目录：{loc}\n"
                f"缩略图：{n} 个文件 · 占用 {human_size(b)}\n"
                f"在线原图临时缓存：{on} 个文件 · 占用 {human_size(ob)}"
                f"（上限 2 GB，超出自动淘汰）\n"
                f"（缓存不写入图片目录，云同步不产生流量）")
        if extra:
            text += "\n" + extra
        self.label.setText(text)

    def _clean_orphans(self) -> None:
        n, _b = self.controller.cache_info()
        if n == 0:
            self._refresh(extra="缓存为空，无需清理。")
            return
        ans = QMessageBox.question(
            self, "清理孤儿缓存",
            "将删除当前库中已不存在图片的缩略图缓存。\n"
            "不影响任何图片文件，浏览时会自动重建。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ans != QMessageBox.StandardButton.Yes:
            return
        removed = self.controller.clean_cache_orphans()
        QPixmapCache.clear()
        self.controller.wall_update.emit()
        self._refresh(extra=f"已清理孤儿缓存 {removed} 个。")

    def _clean_all(self) -> None:
        n, b = self.controller.cache_info()
        ans = QMessageBox.question(
            self, "清空全部缓存",
            f"将删除当前库的全部 {n} 个缩略图缓存（占用 {human_size(b)}）。\n"
            "不影响任何图片文件，但之后浏览需要重新生成，大库会明显变慢。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.controller.clean_cache_all()
        QPixmapCache.clear()
        self.controller.wall_update.emit()
        self._refresh(extra="已清空全部缓存，浏览时将自动重建。")
