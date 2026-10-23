# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""分享记录管理：列出服务端已有的短链，支持单条/批量撤销、复制。

所有网络请求都在后台线程执行 —— 之前版本在 UI 线程同步循环调用，
选中 11 条撤销会让窗口「未响应」数秒（实测 CF 单次往返 300~1000ms）。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)


def _fmt_time(ms) -> str:
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "—"


class _WorkerSignals(QObject):
    done = Signal(object)          # 任意结果（list / dict / True）
    failed = Signal(str)


class _Worker(QRunnable):
    """把任意阻塞调用丢到后台线程。fn 的返回值通过 done 信号回传。"""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:                      # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.done.emit(result)


class SharesDialog(QDialog):
    """分享记录列表。数据来自服务端，撤销即时生效。"""

    COLS = ["创建时间", "图片", "短链", "访问", "最后访问", "状态"]

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分享记录")
        self.resize(940, 520)
        self.controller = controller
        self._rows: list[dict] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)     # 串行，避免并发打满
        self._busy = False
        self._workers: list = []            # 保活，防止运行中被 GC

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        self.lbl_summary = QLabel("正在加载…")
        self.lbl_summary.setStyleSheet("color:#8a8f98;")
        lay.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, len(self.COLS), self)
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_copy = QPushButton("复制选中链接")
        self.btn_revoke = QPushButton("撤销选中")
        self.btn_revoke_all = QPushButton("撤销全部有效")
        self.btn_close = QPushButton("关闭")
        for b in (self.btn_refresh, self.btn_copy, self.btn_revoke,
                  self.btn_revoke_all, self.btn_close):
            row.addWidget(b)
        lay.addLayout(row)

        self.btn_refresh.clicked.connect(self.reload)
        self.btn_copy.clicked.connect(self._copy_selected)
        self.btn_revoke.clicked.connect(self._revoke_selected)
        self.btn_revoke_all.clicked.connect(self._revoke_all)
        self.btn_close.clicked.connect(self.accept)

        self.reload()

    # ---------------- 通用：后台执行 ----------------
    def _run(self, fn, on_done, busy_text: str = "", on_fail=None) -> None:
        """在后台线程跑 fn，完成后回调 on_done(结果)。期间禁用按钮。"""
        if busy_text:
            self.lbl_summary.setText(busy_text)
        self._set_buttons(False)
        w = _Worker(fn)
        w.signals.done.connect(lambda r: self._finish(on_done, r))
        w.signals.failed.connect(
            lambda msg: self._finish_failed(on_fail, msg))
        self._workers.append(w)
        self._pool.start(w)

    def _finish(self, on_done, result) -> None:
        self._set_buttons(True)
        self._workers.clear()       # 该 worker 已回调完成，可释放
        try:
            on_done(result)
        except Exception as exc:                      # noqa: BLE001
            self.lbl_summary.setText(f"处理结果出错：{type(exc).__name__}: {exc}")

    def _finish_failed(self, on_fail, msg: str) -> None:
        self._set_buttons(True)
        self._workers.clear()
        if on_fail is not None:
            on_fail(msg)
        else:
            self.lbl_summary.setText(f"操作失败：{msg}")

    def _set_buttons(self, enabled: bool) -> None:
        for b in (self.btn_refresh, self.btn_copy, self.btn_revoke,
                  self.btn_revoke_all):
            b.setEnabled(enabled)

    # ---------------- 数据 ----------------
    def reload(self) -> None:
        srv = self.controller.share_server()
        if srv is None:
            self.lbl_summary.setText("未启用分享服务端（设置 → 启用分享服务端）")
            self.table.setRowCount(0)
            return
        self._run(
            lambda: srv.list_shares(limit=500),
            self._on_listed,
            busy_text="正在加载…",
            on_fail=lambda m: self.lbl_summary.setText(f"加载失败：{m}"),
        )

    def _on_listed(self, result) -> None:
        ok, items = result
        if not ok:
            self.lbl_summary.setText(f"加载失败：{items}")
            return
        self._rows = items
        active = sum(1 for it in items if not it.get("revoked"))
        total_hits = sum(it.get("hits") or 0 for it in items)
        self.lbl_summary.setText(
            f"共 {len(items)} 条，其中有效 {active} 条 · 累计访问 {total_hits} 次")
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(len(self._rows))
        for r, it in enumerate(self._rows):
            oss_key = it.get("oss_key") or ""
            name = oss_key.rsplit("/", 1)[-1]
            revoked = bool(it.get("revoked"))
            cells = [
                _fmt_time(it.get("created_at")),
                name,
                it.get("url") or "",
                str(it.get("hits") or 0),
                _fmt_time(it.get("last_hit")),
                "已撤销" if revoked else "有效",
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if revoked:
                    cell.setForeground(Qt.GlobalColor.gray)
                if c == 3:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, cell)

    # ---------------- 操作 ----------------
    def _selected(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._rows[r] for r in rows if r < len(self._rows)]

    def _copy_selected(self) -> None:
        sel = self._selected()
        if not sel:
            QMessageBox.information(self, "提示", "请先选中记录。")
            return
        usable = [it for it in sel if not it.get("revoked")]
        if not usable:
            QMessageBox.information(
                self, "提示", "选中的链接都已撤销，复制出去也无法访问。")
            return
        from PySide6.QtWidgets import QApplication
        text = "\n".join(it["url"] for it in usable)
        QApplication.clipboard().setText(text)
        self.lbl_summary.setText(f"已复制 {len(usable)} 条链接到剪贴板")

    def _revoke_selected(self) -> None:
        sel = [it for it in self._selected() if not it.get("revoked")]
        if not sel:
            QMessageBox.information(self, "提示", "没有可撤销的有效链接。")
            return
        ans = QMessageBox.question(
            self, "撤销分享链接",
            f"将撤销选中的 {len(sel)} 条短链，之后访问显示 410 已失效。\n\n"
            "已发出去的链接无法恢复。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        srv = self.controller.share_server()
        if srv is None:
            return
        tokens = [it["token"] for it in sel]

        def work():
            done = failed = 0
            for t in tokens:
                ok, _ = srv.revoke(t)
                done += 1 if ok else 0
                failed += 0 if ok else 1
            return (done, failed)

        self._run(work, self._on_revoked,
                  busy_text=f"正在撤销 {len(tokens)} 条…")

    def _revoke_all(self) -> None:
        active = [it for it in self._rows if not it.get("revoked")]
        if not active:
            QMessageBox.information(self, "提示", "当前没有有效链接。")
            return
        ans = QMessageBox.question(
            self, "撤销全部分享链接",
            f"将撤销全部 {len(active)} 条有效短链。\n\n"
            "这会让所有已分享出去的链接立即失效，无法恢复。确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        srv = self.controller.share_server()
        if srv is None:
            return
        tokens = [it["token"] for it in active]

        def work():
            done = 0
            for t in tokens:
                ok, _ = srv.revoke(t)
                done += 1 if ok else 0
            return (done, len(tokens) - done)

        self._run(work, self._on_revoked,
                  busy_text=f"正在撤销全部 {len(tokens)} 条…")

    def _on_revoked(self, result) -> None:
        done, failed = result
        self.lbl_summary.setText(
            f"已撤销 {done} 条" + (f"，{failed} 条失败" if failed else ""))
        self.reload()
