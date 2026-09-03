# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""重复组面板：每组并排预览，可一键"保留最大/保留最新，其余移出"。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QGraphicsOpacityEffect, QVBoxLayout, QWidget)

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
        hint = QLabel("单张勾选「排除」跳过误判图片；整组勾选「排除该组」跳过整组；"
                      "底部「一键保留最大/最新」批量处理所有未排除组。")
        hint.setStyleSheet("color:#8a8f98;")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setSpacing(12)

        if not groups:
            lay.addWidget(QLabel("未发现疑似重复图片。"))

        self._checks: list[list[QCheckBox]] = []
        self._groups = groups
        self._group_excl: list[QCheckBox] = []
        for gi, group in enumerate(groups):
            trow = QHBoxLayout()
            title = QLabel(f"第 {gi + 1} 组（{len(group)} 张）")
            title.setStyleSheet("color:#8ab4f8;font-weight:bold;")
            trow.addWidget(title)
            gchk = QCheckBox("排除该组")
            gchk.setStyleSheet("color:#8a8f98;")
            trow.addWidget(gchk)
            trow.addStretch(1)
            lay.addLayout(trow)
            self._group_excl.append(gchk)

            row = QHBoxLayout()
            row.setSpacing(8)
            checks: list[QCheckBox] = []
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
                eff = QGraphicsOpacityEffect(lbl)
                lbl.setGraphicsEffect(eff)
                cell.addWidget(lbl)
                info = QLabel(f"{item.path.name}\n"
                              f"{human_size(item.size_bytes)} · {human_time(item.mtime)}")
                info.setFixedWidth(CELL)
                info.setWordWrap(True)
                cell.addWidget(info)
                chk = QCheckBox("排除（非重复）")
                chk.setStyleSheet("color:#8a8f98;")
                chk.toggled.connect(
                    lambda on, e=eff: e.setOpacity(0.3 if on else 1.0))
                cell.addWidget(chk)
                checks.append(chk)
                row.addLayout(cell)
            self._checks.append(checks)

            btns = QVBoxLayout()
            online = self.controller.online_mode
            b1 = QPushButton("保留最大\n其余移出")
            b1.clicked.connect(
                lambda _=False, g=group, i=gi: self._keep(i, g, "size"))
            b2 = QPushButton("保留最新\n其余移出")
            b2.clicked.connect(
                lambda _=False, g=group, i=gi: self._keep(i, g, "mtime"))
            if online:
                for b in (b1, b2):
                    b.setToolTip("在线模式：确认后将永久删除云端重复对象（不可逆）")
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

        bottom = QHBoxLayout()
        online = self.controller.online_mode
        tip = ("在线模式：确认后将永久删除云端重复对象（不可逆）"
               if online else "本地模式：移出到 Remove/，可还原")
        bb1 = QPushButton("一键保留最大（处理未排除组）")
        bb1.setToolTip(tip)
        bb1.clicked.connect(lambda: self._batch("size"))
        bb2 = QPushButton("一键保留最新（处理未排除组）")
        bb2.setToolTip(tip)
        bb2.clicked.connect(lambda: self._batch("mtime"))
        btn_redo = QPushButton("重新检测")
        btn_redo.clicked.connect(self._redo)
        bottom.addWidget(bb1)
        bottom.addWidget(bb2)
        bottom.addWidget(btn_redo)
        outer.addLayout(bottom)

    def _redo(self) -> None:
        self.controller.find_duplicates(True)
        self.accept()

    def _preview(self, item) -> QPixmap:
        """优先复用任意档位本地缓存；本地项无缓存时生成 256 档兜底。
        在线项只读缓存（无本地文件，不尝试读伪路径）。"""
        root = self.controller.cache_root or self.controller.root
        if root is None:
            return QPixmap()
        for tier in (256, 512):
            fp = thumbnail.thumb_path(root, item, tier)
            if fp.exists():
                pix = QPixmap(str(fp))
                if not pix.isNull():
                    return pix
        if item.remote_key:
            return QPixmap()
        out, _ph = thumbnail.generate(root, item, 256)
        if out is not None:
            return QPixmap(str(out))
        return QPixmap()

    def _batch(self, by: str) -> None:
        """跨组一键批处理：每个未排除组保留一张，其余移出/删除。"""
        actives = []
        for gi, group in enumerate(self._groups):
            if self._group_excl[gi].isChecked():
                continue
            checks = self._checks[gi] if gi < len(self._checks) else []
            active = [it for it, c in zip(group, checks)
                      if not c.isChecked()]
            if len(active) >= 2:
                actives.append(active)
        if not actives:
            QMessageBox.information(self, "提示",
                                    "没有可处理的组（均被排除或不足 2 张）。")
            return
        n_del = sum(len(a) - 1 for a in actives)
        if self.controller.online_mode:
            ans = QMessageBox.question(
                self, "云端批量删除确认",
                f"将对 {len(actives)} 组永久删除 {n_del} 张云端重复图片"
                f"（不可恢复），每组仅保留"
                f"{'最大' if by == 'size' else '最新'}的一张。继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.controller.batch_keep(actives, by)
        self.accept()

    def _keep(self, gi: int, group, by: str) -> None:
        checks = self._checks[gi] if gi < len(self._checks) else []
        active = [it for it, c in zip(group, checks) if not c.isChecked()]
        if len(active) < 2:
            QMessageBox.information(self, "提示",
                                    "排除后该组不足 2 张，无需处理。")
            return
        if self.controller.online_mode:
            n = len(active) - 1
            ans = QMessageBox.question(
                self, "云端删除确认",
                f"将永久删除 {n} 张云端重复图片（不可恢复），\n"
                f"仅保留{'最大' if by == 'size' else '最新'}的一张。继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.controller.keep_one(active, by)
