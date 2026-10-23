# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""设置对话框：默认读取目录 / 默认保存目录。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QWidget)


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

        # ---- 分享服务端（Cloudflare Workers 短链）----
        self.chk_server = QCheckBox("启用分享服务端（生成可撤销短链）")
        self.chk_server.setChecked(settings.server_enabled)
        form.addRow(self.chk_server)

        self.edit_srv = QLineEdit(settings.server_base)
        self.edit_srv.setPlaceholderText("https://img.agentstack.vip")
        form.addRow("服务端地址", self.edit_srv)

        self.edit_srv_secret = QLineEdit(settings.server_secret)
        self.edit_srv_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_srv_secret.setPlaceholderText("与服务端共享的 HMAC 密钥")
        form.addRow("服务端密钥", self.edit_srv_secret)

        self.lbl_srv = QLabel("密钥与本机 OSS Secret 同样用 Windows DPAPI 加密存储。")
        self.lbl_srv.setStyleSheet("color:#8a8f98;")
        self.lbl_srv.setWordWrap(True)
        form.addRow(self.lbl_srv)

        row_srv = QHBoxLayout()
        btn_test_srv = QPushButton("测试服务端连接")
        btn_test_srv.clicked.connect(self._test_server)
        row_srv.addWidget(btn_test_srv)
        row_srv.addStretch(1)
        form.addRow(row_srv)

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

    def _test_server(self) -> None:
        """测服务端连通性（先 /health，再用密钥签一个只读请求）。"""
        base = self.edit_srv.text().strip().rstrip("/")
        sec = self.edit_srv_secret.text().strip()
        if not base:
            self.lbl_srv.setText("请先填写服务端地址")
            return
        from ..core.share_server import ShareServer
        srv = ShareServer(base, sec)
        ok, data = srv.health()
        if not ok:
            self.lbl_srv.setText(f"连接失败：{data}")
            return
        if not sec:
            self.lbl_srv.setText("服务端可达，但未填密钥（无法调用接口）")
            return
        ok2, res = srv.list_shares(limit=1)
        if ok2:
            self.lbl_srv.setText(
                f"连接成功：DB {data.get('db', '?')}，鉴权通过，现有 {len(res)} 条分享")
        else:
            self.lbl_srv.setText(f"服务端可达，但鉴权失败：{res}")

    def accept(self) -> None:
        self.settings.default_open_dir = self.edit_open.text().strip()
        self.settings.default_save_dir = self.edit_save.text().strip()
        self.settings.dup_threshold = self.spin_dup.value()
        self.settings.auto_load_last = self.chk_auto.isChecked()
        self.settings.scan_parallel = self.spin_scan.value()
        self.settings.upload_threads = self.spin_threads.value()
        self.settings.upload_skip_dups = self.chk_skipdup.isChecked()
        self.settings.share_days = self.spin_days.value()
        self.settings.server_enabled = self.chk_server.isChecked()
        self.settings.server_base = self.edit_srv.text().strip()
        self.settings.server_secret = self.edit_srv_secret.text().strip()
        super().accept()
