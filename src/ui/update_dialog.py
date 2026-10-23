# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""新版本提示对话框：显示版本号与更新说明，可打开发布页。"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QTextBrowser, QVBoxLayout)

from .. import meta
from ..core.updater import ReleaseInfo


class UpdateDialog(QDialog):
    def __init__(self, info: ReleaseInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发现新版本")
        self.resize(620, 460)
        self.info = info
        self.skipped = False        # 用户是否选择「稍后再说」

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)

        title = QLabel(f"<b>{info.name}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        lay.addWidget(title)

        cur = QLabel(f"当前版本 {meta.VERSION}　→　最新版本 {info.version}")
        cur.setStyleSheet("color:#8a8f98;")
        lay.addWidget(cur)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        # Releases 的 body 是 Markdown，这里做最小可读化：
        # 只把裸换行保留、去掉行首 # 标记，避免引入 markdown 依赖
        self.view.setPlainText(self._tidy(info.notes) or "（该版本没有提供更新说明）")
        lay.addWidget(self.view, 1)

        buttons = QDialogButtonBox(self)
        self.btn_open = buttons.addButton("打开发布页",
                                          QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_later = buttons.addButton("稍后再说",
                                           QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_open.clicked.connect(self._open_page)
        self.btn_later.clicked.connect(self._later)
        lay.addWidget(buttons)

    @staticmethod
    def _tidy(text: str) -> str:
        lines = []
        for ln in (text or "").splitlines():
            s = ln.rstrip()
            if s.startswith("### "):
                lines.append("【" + s[4:] + "】")
            elif s.startswith("## "):
                lines.append("\n■ " + s[3:])
            elif s.startswith("# "):
                lines.append("■ " + s[2:])
            elif s.strip() in ("---", "***"):
                lines.append("─" * 40)
            else:
                lines.append(s)
        return "\n".join(lines).strip()

    def _open_page(self) -> None:
        try:
            webbrowser.open(self.info.page_url)
        except Exception:
            pass
        self.accept()

    def _later(self) -> None:
        self.skipped = True
        self.reject()
