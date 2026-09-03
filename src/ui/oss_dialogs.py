# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""OSS 配置与上传到云对话框。"""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QVBoxLayout)


class OssConfigDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OSS 在线配置")
        self.settings = settings
        form = QFormLayout(self)
        self.ed_endpoint = QLineEdit(settings.oss_endpoint)
        self.ed_endpoint.setPlaceholderText("https://oss-cn-hangzhou.aliyuncs.com")
        self.ed_bucket = QLineEdit(settings.oss_bucket)
        self.ed_ak = QLineEdit(settings.oss_ak_id)
        self.ed_sk = QLineEdit(settings.oss_ak_secret)
        self.ed_sk.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Endpoint", self.ed_endpoint)
        form.addRow("Bucket", self.ed_bucket)
        form.addRow("AccessKey ID", self.ed_ak)
        form.addRow("AccessKey Secret", self.ed_sk)
        self.lbl = QLabel("AK/SK 仅保存在本机用户目录，不上传不入库")
        form.addRow(self.lbl)
        row = QHBoxLayout()
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test)
        row.addWidget(btn_test)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        form.addRow(row)

    def _collect(self):
        return (self.ed_endpoint.text().strip(), self.ed_bucket.text().strip(),
                self.ed_ak.text().strip(), self.ed_sk.text().strip())

    def _test(self) -> None:
        from ..core.oss_service import OssLibrary
        e, b, a, s = self._collect()
        if not (e and b and a and s):
            self.lbl.setText("请先填写完整四项")
            return
        try:
            name = OssLibrary(e, b, a, s).test()
            self.lbl.setText(f"连接成功：{name}")
        except Exception as exc:
            self.lbl.setText(f"连接失败：{exc}")

    def _save(self) -> None:
        st = self.settings
        e, b, a, s = self._collect()
        st.oss_endpoint = e
        st.oss_bucket = b
        st.oss_ak_id = a
        st.oss_ak_secret = s
        st.sync()
        self.accept()


class UploadDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("上传到云")
        self.controller = controller
        lay = QVBoxLayout(self)
        self.lbl = QLabel()
        lay.addWidget(self.lbl)
        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        btn_cfg = QPushButton("配置 OSS")
        btn_cfg.clicked.connect(
            lambda: OssConfigDialog(controller.settings, self).exec())
        btn_start = QPushButton("开始增量上传")
        btn_start.clicked.connect(self._start)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_cfg)
        row.addWidget(btn_start)
        row.addWidget(btn_close)
        lay.addLayout(row)
        self._refresh()

    def _refresh(self) -> None:
        self.lbl.setText("已配置 OSS" if self.controller.oss_configured()
                         else "未配置 OSS，请先点击「配置 OSS」")

    def _start(self) -> None:
        self._refresh()
        if not self.controller.oss_configured():
            return
        w, total, skipped = self.controller.create_upload_worker()
        if w is None:
            self.lbl.setText("当前无法上传（在线模式或未加载本地库）")
            return
        if total == 0:
            self.lbl.setText(f"无需上传（跳过已传 {skipped} 项）")
            return
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        w.signals.progress.connect(
            lambda d, t, n: (self.bar.setValue(d),
                             self.lbl.setText(f"上传 {d}/{t}：{n}")))
        w.signals.finished.connect(
            lambda up, fd: (self.bar.setValue(self.bar.maximum()),
                            self.lbl.setText(
                                f"完成：新传 {up}，跳过已传 {skipped}"
                                + (f"，失败 {fd}" if fd else ""))))
        self.controller.pool.start(w)
