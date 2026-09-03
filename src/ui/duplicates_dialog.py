# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""重复组面板：每组并排预览，可一键"保留最大/保留最新，其余移出"。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core import thumbnail
from ..utils.format import human_size, human_time

CELL = 170


class DuplicatesDialog(QDialog):
    def __init__(self, controller, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"疑似重复图片（{len(groups)} 组）")
        self.resize(980, 560)
        self.controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setSpacing(12)

        if not groups:
            lay.addWidget(QLabel("未发现疑似重复图片。"))

        for gi, group in enumerate(groups):
            title = QLabel(f"第 {gi + 1} 组（{len(group)} 张）")
            title.setStyleSheet("color:#8ab4f8;font-weight:bold;")
            lay.addWidget(title)

            row = QHBoxLayout()
            row.setSpacing(8)
            for item in group:
                cell = QVBoxLayout()
                lbl = QLabel()
                lbl.setFixedSize(CELL, CELL)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("background:#26272b;border-radius:6px;")
                pix = self._preview(item)
                if pix is not None and not pix.isNull():
                    lbl.setPixmap(pix.scaled(
                        CELL - 8, CELL - 8,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                else:
                    lbl.setText("无预览")
                cell.addWidget(lbl)
                info = QLabel(f"{item.path.name}\n"
                              f"{human_size(item.size_bytes)} · {human_time(item.mtime)}")
                info.setFixedWidth(CELL)
                info.setWordWrap(True)
                cell.addWidget(info)
                row.addLayout(cell)

            btns = QVBoxLayout()
            b1 = QPushButton("保留最大\n其余移出")
            b1.clicked.connect(lambda _=False, g=group: self._keep(g, "size"))
            b2 = QPushButton("保留最新\n其余移出")
            b2.clicked.connect(lambda _=False, g=group: self._keep(g, "mtime"))
            btns.addWidget(b1)
            btns.addWidget(b2)
            btns.addStretch(1)
            row.addLayout(btns)
            row_w = QWidget()
            row_w.setLayout(row)
            lay.addWidget(row_w)

            if gi != len(groups) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color:#3a3b3e;")
                lay.addWidget(line)
        lay.addStretch(1)
        host.adjustSize()
        scroll.setWidget(host)
        outer.addWidget(scroll)
        btn_redo = QPushButton("重新检测")
        btn_redo.clicked.connect(self._redo)
        outer.addWidget(btn_redo)

    def _redo(self) -> None:
        self.controller.find_duplicates(True)
        self.accept()

    def _preview(self, item) -> QPixmap:
        """优先复用任意档位本地缓存；均无时同步生成 256 档兜底。"""
        root = self.controller.cache_root or self.controller.root
        if root is None:
            return QPixmap()
        for tier in (256, 512):
            fp = thumbnail.thumb_path(root, item, tier)
            if fp.exists():
                pix = QPixmap(str(fp))
                if not pix.isNull():
                    return pix
        out, _ph = thumbnail.generate(root, item, 256)
        if out is not None:
            return QPixmap(str(out))
        return QPixmap()

    def _keep(self, group, by: str) -> None:
        self.controller.keep_one(group, by)
