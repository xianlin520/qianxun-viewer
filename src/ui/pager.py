# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""分页控件条：首页 / 上一页 / 页码 / 下一页 / 末页。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class PagerBar(QWidget):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = 0
        self._total = 1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.btn_first = QPushButton("首页")
        self.btn_prev = QPushButton("上一页")
        self.label = QLabel("第 1 / 1 页")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next = QPushButton("下一页")
        self.btn_last = QPushButton("末页")
        for w in (self.btn_first, self.btn_prev, self.label,
                  self.btn_next, self.btn_last):
            lay.addWidget(w)
        self.btn_first.clicked.connect(lambda: self._goto(0))
        self.btn_prev.clicked.connect(lambda: self._goto(self._page - 1))
        self.btn_next.clicked.connect(lambda: self._goto(self._page + 1))
        self.btn_last.clicked.connect(lambda: self._goto(self._total - 1))

    def _goto(self, target: int) -> None:
        """夹取后再发信号。

        原实现四个 lambda 直接 emit(self._page ± 1)，而 _page 只在 set_state
        里更新：快速双击「下一页」会连发两次相同目标页码，页面不跳。
        也不夹取载荷，调用方忘记检查时会把 -1 / total 传进控制器。
        """
        target = max(0, min(int(target), self._total - 1))
        if target == self._page:
            return
        self.set_state(target, self._total)
        self.page_changed.emit(target)

    def set_state(self, page: int, total: int) -> None:
        self._total = max(1, total)
        self._page = max(0, min(page, self._total - 1))
        self.label.setText(f"第 {self._page + 1} / {self._total} 页")
        self.btn_first.setEnabled(self._page > 0)
        self.btn_prev.setEnabled(self._page > 0)
        self.btn_next.setEnabled(self._page < self._total - 1)
        self.btn_last.setEnabled(self._page < self._total - 1)
