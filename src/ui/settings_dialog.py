# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""设置对话框：默认读取目录 / 默认保存目录。"""
from __future__ import annotations

from . import theme
from .async_call import AsyncCaller

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QWidget)


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

        # 外观：切换立刻生效，不必重启。QSS 与自绘配色都从 theme 取，
        # 这里只负责换调色板并让已经画出来的控件重绘。
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItem("深色（默认）", "dark")
        self.cmb_theme.addItem("浅色", "light")
        self.cmb_theme.setCurrentIndex(max(0, self.cmb_theme.findData(settings.theme)))
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow("外观", self.cmb_theme)
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
        self.lbl_srv.setStyleSheet(theme.muted())
        self.lbl_srv.setWordWrap(True)
        form.addRow(self.lbl_srv)

        row_srv = QHBoxLayout()
        btn_test_srv = QPushButton("测试服务端连接")
        self.btn_test_srv = btn_test_srv
        btn_test_srv.clicked.connect(self._test_server)
        row_srv.addWidget(btn_test_srv)
        row_srv.addStretch(1)
        form.addRow(row_srv)

        # ---- 隐私：本地模式 ----
        self.chk_local_only = QCheckBox("本地模式（不联网，默认开启）")
        self.chk_local_only.setChecked(settings.local_only)
        self.chk_local_only.setToolTip(
            "开启后，对象存储上传/下载、短链服务端、更新检查全部被拦下，\n"
            "请求不会离开本机；被拦下的尝试只记到本地的出网日志。")
        form.addRow(self.chk_local_only)

        self.lbl_privacy = QLabel(
            "本地模式下，图片、目录名、文件名都留在本机。\n"
            "关掉本地模式后，以下动作才会真正出网：\n"
            "· 上传到云：图片文件本身会传到你的 OSS；\n"
            "· 生成短链：服务端会记录对象 key（默认已改成路径哈希，不含文件名）与你的备注；\n"
            "· 同步收藏：收藏项的对象 key 会上传，用于多机合并；\n"
            "· 检查更新：只查 Gitee Releases，不上报任何本地信息。\n"
            "每次出网都会在本地 egress.log 记一行，只记主机名。")
        self.lbl_privacy.setStyleSheet(theme.muted())
        self.lbl_privacy.setWordWrap(True)
        form.addRow(self.lbl_privacy)

        row_log = QHBoxLayout()
        self.btn_egress_log = QPushButton("查看出网日志")
        self.btn_egress_log.clicked.connect(self._show_egress_log)
        row_log.addWidget(self.btn_egress_log)
        row_log.addStretch(1)
        form.addRow(row_log)

        # ---- 更新检测 ----
        self.chk_update = QCheckBox("启动后自动检测新版本（仅查询 Gitee Releases）")
        self.chk_update.setChecked(settings.check_updates)
        form.addRow(self.chk_update)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_theme_changed(self) -> None:
        """切换外观：立刻落库并重绘。取消对话框也不回滚，所见即所得。"""
        name = self.cmb_theme.currentData()
        if not name:
            return
        self.settings.theme = name
        theme.apply(name)

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
        """测服务端连通性（先 /health，再用密钥签一个只读请求）。

        请求全部放后台线程。此前在模态框的槽函数里同步发请求，
        地址填错或不可达时窗口冻结 20~60 秒，Windows 标「未响应」，
        用户连取消都点不动。
        """
        base = self.edit_srv.text().strip().rstrip("/")
        sec = self.edit_srv_secret.text().strip()
        if not base:
            self.lbl_srv.setText("请先填写服务端地址")
            return

        from ..core.share_server import ShareServer
        srv = ShareServer(base, sec)

        def job():
            ok, data = srv.health()
            if not ok:
                return {"stage": "health", "ok": False, "err": data}
            if not sec:
                return {"stage": "health", "ok": True, "data": data, "no_secret": True}
            ok2, res = srv.list_shares(limit=1)
            if not ok2:
                return {"stage": "auth", "ok": False, "err": res}
            items = res[0] if isinstance(res, tuple) else res
            return {"stage": "auth", "ok": True, "data": data, "count": len(items)}

        if getattr(self, "_srv_async", None) is None:
            self._srv_async = AsyncCaller(self)
        self.btn_test_srv.setEnabled(False)
        self.lbl_srv.setText("正在连接…")
        self._srv_async.run(job, on_done=self._on_server_tested,
                            on_fail=self._on_server_test_failed)

    def _on_server_test_failed(self, exc) -> None:
        self.btn_test_srv.setEnabled(True)
        detail = str(exc) if isinstance(exc, BaseException) else str(exc)
        self.lbl_srv.setText(f"连接失败：{detail}")

    def _on_server_tested(self, result) -> None:
        self.btn_test_srv.setEnabled(True)
        if not result["ok"]:
            prefix = "连接失败" if result["stage"] == "health" else "服务端可达，但鉴权失败"
            self.lbl_srv.setText(f"{prefix}：{result['err']}")
            return
        data = result.get("data") or {}
        if result.get("no_secret"):
            self.lbl_srv.setText("服务端可达，但未填密钥（无法调用接口）")
            return
        self.lbl_srv.setText(
            f"连接成功：DB {data.get('db', '?')}，鉴权通过，现有 {result['count']} 条分享")

    def _show_egress_log(self) -> None:
        """打开出网日志所在目录（不弹日志内容，避免误读成程序输出）。"""
        from ..core import netguard
        path = netguard.log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("", "utf-8")
            import os
            os.startfile(str(path))       # noqa: S606 - 用户主动点开的本地文件
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", f"{type(exc).__name__}: {exc}")

    def _confirm_online(self) -> bool:
        """关掉本地模式要显式确认：这一步之后内容才可能离开本机。"""
        if self.chk_local_only.isChecked() or not self.settings.local_only:
            return True
        r = QMessageBox.question(
            self, "关闭本地模式",
            "关掉本地模式后，你主动触发的上传、生成短链、同步收藏才会连网。\n\n"
            "默认的上传 key 是路径哈希，云端看不到目录名与文件名；\n"
            "把 key 模式改成「保留目录结构」则会把相对路径一并显示在云端。\n\n"
            "确定关闭本地模式吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

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
        self.settings.check_updates = self.chk_update.isChecked()
        # 隐私开关放最后：确认被拒绝时整轮不保存，避免「一半改了」
        if not self._confirm_online():
            return
        self.settings.local_only = self.chk_local_only.isChecked()
        super().accept()
