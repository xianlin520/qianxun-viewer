# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""分享记录管理：列出服务端已有的短链，支持单条撤销与复制。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..utils.format import human_size


def _fmt_time(ms) -> str:
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "—"


class SharesDialog(QDialog):
    """分享记录列表。数据来自服务端，撤销即时生效。"""

    COLS = ["创建时间", "图片", "短链", "访问", "最后访问", "状态"]

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分享记录")
        self.resize(940, 520)
        self.controller = controller
        self._rows: list[dict] = []

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

    # ---------------- 数据 ----------------
    def reload(self) -> None:
        srv = self.controller.share_server()
        if srv is None:
            self.lbl_summary.setText("未启用分享服务端（设置 → 启用分享服务端）")
            self.table.setRowCount(0)
            return
        ok, items = srv.list_shares(limit=500)
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
        revoked = [it for it in sel if it.get("revoked")]
        if revoked and len(revoked) == len(sel):
            QMessageBox.information(self, "提示", "选中的链接都已撤销，复制出去也无法访问。")
            return
        from PySide6.QtWidgets import QApplication
        text = "\n".join(it["url"] for it in sel if not it.get("revoked"))
        QApplication.clipboard().setText(text)
        self.lbl_summary.setText(f"已复制 {len(text.splitlines())} 条链接到剪贴板")

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
        done = failed = 0
        for it in sel:
            ok, _ = srv.revoke(it["token"])
            done += 1 if ok else 0
            failed += 0 if ok else 1
        self.lbl_summary.setText(
            f"已撤销 {done} 条" + (f"，{failed} 条失败" if failed else ""))
        self.reload()

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
        done = 0
        for it in active:
            ok, _ = srv.revoke(it["token"])
            done += 1 if ok else 0
        self.lbl_summary.setText(f"已撤销 {done} / {len(active)} 条")
        self.reload()
