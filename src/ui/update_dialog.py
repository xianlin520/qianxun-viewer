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
        # setOpenExternalLinks(True) 只对富文本里的 <a> 生效；
        # 配 setPlainText 时裸 URL 不会被识别成链接，点了没反应
        self.view.setHtml(self._tidy_html(info.notes)
                          or "（该版本没有提供更新说明）")
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
    def _tidy_html(text: str) -> str:
        """最小 Markdown → HTML，只为让链接可点。

        不引入 markdown 依赖：只处理标题、分隔线与裸 URL。
        裸 URL 包进 <a> 后 setOpenExternalLinks 才真正生效。
        """
        import html as _html
        import re as _re

        url_re = _re.compile(r"(https?://[^\s<]+)")
        out = []
        for raw in (text or "").splitlines():
            line = raw.rstrip()
            esc = _html.escape(line)
            esc = url_re.sub(
                lambda m: '<a href="%s">%s</a>' % (m.group(1), m.group(1)), esc)
            if line.startswith("### "):
                out.append("<b>【%s】</b>" % esc[4:])
            elif line.startswith("## "):
                out.append("<br><b>■ %s</b>" % esc[3:])
            elif line.startswith("# "):
                out.append("<b>■ %s</b>" % esc[2:])
            elif line.strip() in ("---", "***"):
                out.append("<hr>")
            else:
                out.append(esc)
        return "<br>".join(out).strip()

    def _open_page(self) -> None:
        """打开浏览器；失败时不关闭对话框，改为提供复制链接。

        原实现 except 后照样 accept()：无默认浏览器或被安全软件拦下时，
        用户点按钮 → 对话框关闭 → 什么都没发生，也没法重试。
        """
        try:
            opened = webbrowser.open(self.info.page_url)
        except Exception:                              # noqa: BLE001
            opened = False
        if opened:
            self.accept()
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.info.page_url)
        self.btn_open.setText("打开失败，已复制链接")
        self.btn_open.setEnabled(False)

    def _later(self) -> None:
        self.skipped = True
        self.reject()
