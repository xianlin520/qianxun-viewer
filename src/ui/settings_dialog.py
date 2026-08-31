# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""设置对话框：默认读取目录 / 默认保存目录。"""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLineEdit, QPushButton, QWidget)


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
        super().accept()
