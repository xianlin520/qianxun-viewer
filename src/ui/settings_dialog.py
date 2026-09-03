# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""设置对话框：默认读取目录 / 默认保存目录。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QSpinBox, QWidget)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("程序设置")
        self.settings = settings
        form = QFormLayout(self)
        self.edit_open = QLineEdit(settings.default_open_dir)
        self.edit_save = QLineEdit(settings.default_save_dir)
        form.addRow("默认读取目录", self._row(self.edit_open))
        form.addRow("默认保存目录", self._row(self.edit_save))
        self.spin_dup = QSpinBox()
        self.spin_dup.setRange(0, 12)
        self.spin_dup.setValue(settings.dup_threshold)
        self.spin_dup.setToolTip("pHash 汉明距离阈值：越小越严格，\n"
                                 "出现“不像的也被判重复”时请调小")
        form.addRow("查重严格度（汉明距离阈值）", self.spin_dup)

        self.chk_auto = QCheckBox("启动时自动加载上次目录")
        self.chk_auto.setChecked(settings.auto_load_last)
        form.addRow(self.chk_auto)

        self.spin_scan = QSpinBox()
        self.spin_scan.setRange(1, 16)
        self.spin_scan.setValue(settings.scan_parallel)
        form.addRow("扫描并行线程数", self.spin_scan)

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 8)
        self.spin_threads.setValue(settings.upload_threads)
        form.addRow("上传并发线程数", self.spin_threads)

        self.chk_skipdup = QCheckBox("上传时跳过同内容重复文件（省流量）")
        self.chk_skipdup.setChecked(settings.upload_skip_dups)
        form.addRow(self.chk_skipdup)

        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 7)
        self.spin_days.setValue(settings.share_days)
        form.addRow("外链有效期（天）", self.spin_days)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _row(self, edit: QLineEdit) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(edit)
        btn = QPushButton("浏览…")
        btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
        lay.addWidget(btn)
        return w

    def _browse(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
        if d:
            edit.setText(d)

    def accept(self) -> None:
        self.settings.default_open_dir = self.edit_open.text().strip()
        self.settings.default_save_dir = self.edit_save.text().strip()
        self.settings.dup_threshold = self.spin_dup.value()
        self.settings.auto_load_last = self.chk_auto.isChecked()
        self.settings.scan_parallel = self.spin_scan.value()
        self.settings.upload_threads = self.spin_threads.value()
        self.settings.upload_skip_dups = self.chk_skipdup.isChecked()
        self.settings.share_days = self.spin_days.value()
        super().accept()
