# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""重复组面板：每组并排预览，可一键"保留最大/保留最新，其余移出"。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QGraphicsOpacityEffect, QVBoxLayout, QWidget)

from .thumb_cache import THUMBS
from ..utils.format import human_size, human_time

CELL = 170


class _LazyOpacity:
    """按需创建 QGraphicsOpacityEffect。

    常态什么都不挂；只有用户勾选「排除（非重复）」时才加效果，
    取消勾选就移除，避免几十张预览同时走离屏合成。
    """

    def __init__(self, widget):
        self._w = widget
        self._eff = None

    def set_dim(self, on: bool) -> None:
        if on:
            if self._eff is None:
                self._eff = QGraphicsOpacityEffect(self._w)
            self._eff.setOpacity(0.3)
            self._w.setGraphicsEffect(self._eff)
        elif self._eff is not None:
            self._w.setGraphicsEffect(None)
            self._eff = None


class DuplicatesDialog(QDialog):
    def __init__(self, controller, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"疑似重复图片（{len(groups)} 组）")
        self.resize(980, 560)
        self.controller = controller
        self._busy = False          # 批处理/单组操作进行中标志，防连点重复移出

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
        # 每组的两个操作按钮与结果文案：处理过就置灰，避免对同一组二次操作
        self._row_btns: list[tuple[QPushButton, QPushButton]] = []
        self._row_status: list[QLabel] = []
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
                # 不给每张预览都挂 QGraphicsOpacityEffect：
                # 该效果会让 QLabel 走离屏合成，几十组 × 每组数张时
                # 首次打开明显延迟、滚动发涩。改成勾选时按需挂上。
                eff = _LazyOpacity(lbl)
                cell.addWidget(lbl)
                info = QLabel(f"{item.path.name}\n"
                              f"{human_size(item.size_bytes)} · {human_time(item.mtime)}")
                info.setFixedWidth(CELL)
                info.setWordWrap(True)
                cell.addWidget(info)
                chk = QCheckBox("排除（非重复）")
                chk.setStyleSheet("color:#8a8f98;")
                chk.toggled.connect(lambda on, e=eff: e.set_dim(on))
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
            st_lbl = QLabel("")
            st_lbl.setStyleSheet("color:#6ee7a8;font-size:11px;")
            st_lbl.setWordWrap(True)
            st_lbl.setFixedWidth(96)
            btns.addWidget(b1)
            btns.addWidget(b2)
            btns.addWidget(st_lbl)
            btns.addStretch(1)
            self._row_btns.append((b1, b2))
            self._row_status.append(st_lbl)
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
        """优先复用任意档位本地缓存；**不再同步生成**。

        原实现缓存缺失时会同步调用 thumbnail.generate()，一个 40 张的组
        实测要 649ms 全部卡在 UI 线程（每张都要解码原图）。
        现在只读已有缓存，缺失则显示占位，由查重流程/浏览过程填充。"""
        root = self.controller.cache_root or self.controller.root
        if root is None:
            return QPixmap()
        pix = THUMBS.best(root, item)
        return pix if pix is not None else QPixmap()

    def _batch(self, by: str) -> None:
        """跨组一键批处理：每个未排除组保留一张，其余移出/删除。"""
        if self._busy:
            return                      # 防连点：上一次批处理尚未走完
        actives = []
        actives_idx = []
        for gi, group in enumerate(self._groups):
            if self._group_excl[gi].isChecked():
                continue
            active = self._collect_active(gi, group)
            if len(active) >= 2:
                actives.append(active)
                actives_idx.append(gi)
        if not actives:
            QMessageBox.information(self, "提示",
                                    "没有可处理的组（均被排除或不足 2 张）。")
            return
        n_del = sum(len(a) - 1 for a in actives)
        if not self._confirm_online(n_del, by, f"将对 {len(actives)} 组，"):
            return
        self._busy = True       # 批处理期间拒绝再次触发
        try:
            self.controller.batch_keep(actives, by)
        finally:
            self._busy = False
        # 逐组写明结果再关闭，让用户知道都处理了哪些组
        for gi, active in zip(actives_idx, actives):
            kept = max(active, key=lambda i: i.size_bytes if by == "size" else i.mtime)
            self._mark_processed(gi, kept.path.name, len(active) - 1)
        self.accept()

    def _collect_active(self, gi: int, group) -> list:
        """该组里未被「排除」勾选的项。"""
        checks = self._checks[gi] if gi < len(self._checks) else []
        return [it for it, c in zip(group, checks) if not c.isChecked()]

    def _confirm_online(self, n: int, by: str, scope: str) -> bool:
        """在线模式不可逆删除，统一在这里确认。"""
        if not self.controller.online_mode:
            return True
        ans = QMessageBox.question(
            self, "云端删除确认",
            f"将永久删除 {n} 张云端重复图片（不可恢复），\n"
            f"{scope}仅保留{'最大' if by == 'size' else '最新'}的一张。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def _mark_processed(self, gi: int, kept_name: str, moved: int) -> None:
        """处理过的组置灰并写明结果。

        此前 _keep 成功后界面毫无变化，用户会再点一次或接着点「一键保留」，
        对已经在 Remove/ 的文件再移出，产生重复记录和改名，
        还会让「保留最新」把已移出项也算进去从而选错对象。
        """
        if gi < len(self._row_btns):
            for b in self._row_btns[gi]:
                b.setEnabled(False)
        if gi < len(self._row_status):
            self._row_status[gi].setText(f"已提交：保留 {kept_name}\n移出 {moved} 张")

    def _keep(self, gi: int, group, by: str) -> None:
        if self._busy:
            return                      # 防连点：避免同组被重复移出
        active = self._collect_active(gi, group)
        if len(active) < 2:
            QMessageBox.information(self, "提示",
                                    "排除后该组不足 2 张，无需处理。")
            return
        if not self._confirm_online(len(active) - 1, by, ""):
            return
        kept = max(active, key=lambda i: i.size_bytes if by == "size" else i.mtime)
        self._busy = True
        try:
            self.controller.keep_one(active, by)
        finally:
            self._busy = False
        self._mark_processed(gi, kept.path.name, len(active) - 1)
