# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""重复组面板：每组并排预览，可一键"保留最大/保留最新，其余移出"。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core import thumbnail
from ..utils.format import human_size, human_time


class DuplicatesDialog(QDialog):
    def __init__(self, controller, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"疑似重复图片（{len(groups)} 组）")
        self.resize(960, 540)
        self.controller = controller

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        for group in groups:
            row = QHBoxLayout()
            for item in group:
                cell = QVBoxLayout()
                lbl = QLabel()
                pix = QPixmap(str(thumbnail.thumb_path(controller.root, item, 256)))
                if not pix.isNull():
                    lbl.setPixmap(pix.scaled(
                        160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                cell.addWidget(lbl)
                info = QLabel(f"{item.path.name}\n{human_size(item.size_bytes)} · {human_time(item.mtime)}")
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
            lay.addLayout(row)
        lay.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _keep(self, group, by: str) -> None:
        self.controller.keep_one(group, by)
