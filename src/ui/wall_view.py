# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""图片墙视图（滚动模式）：justified 无缝拼接布局，不显示文件名。

每行按宽高比贪心凑满视口宽度，行高接近滑块目标值；
图片以 cover 方式裁切填充单元格，保证行间无缝隙。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPixmapCache
from PySide6.QtWidgets import QAbstractScrollArea

from ..core import thumbnail


class WallView(QAbstractScrollArea):
    item_clicked = Signal(int)              # view_items 下标
    visible_range_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._cells: list = []
        self._total_h = 0
        self.row_height = 180
        self.image_root = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._emit_range)

    # ---------------- 数据与布局 ----------------
    def set_items(self, items) -> None:
        self._items = list(items)
        self.relayout()
        self.update()

    def _aspect(self, item) -> float:
        if item.width and item.height:
            return max(0.2, min(5.0, item.width / item.height))
        return 1.0

    def relayout(self) -> None:
        vp_w = self.viewport().width()
        n = len(self._items)
        cells = [None] * n
        y = 0
        i = 0
        while i < n and vp_w > 0:
            ar_sum = 0.0
            j = i
            while j < n:
                ar_sum += self._aspect(self._items[j])
                if vp_w / ar_sum <= self.row_height:
                    break
                j += 1
            j = min(j, n - 1)
            row_h = max(1, int(vp_w / ar_sum))
            x = 0
            for k in range(i, j + 1):
                w = int(round(row_h * self._aspect(self._items[k])))
                if k == j:
                    w = vp_w - x          # 末格取余宽，保证行内无缝
                cells[k] = QRect(x, y, w, row_h)
                x += w
            y += row_h
            i = j + 1
        self._cells = cells
        self._total_h = y
        sb = self.verticalScrollBar()
        sb.setRange(0, max(0, y - self.viewport().height()))
        sb.setPageStep(max(1, self.viewport().height()))
        sb.setSingleStep(120)
        self._debounce.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.relayout()

    # ---------------- 命中与可见范围 ----------------
    def index_at(self, view_pos) -> int:
        p = QPoint(int(view_pos.x()), int(view_pos.y()) + self.verticalScrollBar().value())
        for idx, cell in enumerate(self._cells):
            if cell is not None and cell.contains(p):
                return idx
        return -1

    def visible_range(self) -> tuple[int, int]:
        v = self.verticalScrollBar().value()
        bot = v + self.viewport().height()
        first = last = -1
        for idx, cell in enumerate(self._cells):
            if cell is None:
                continue
            if cell.bottom() >= v and cell.y() <= bot:
                if first < 0:
                    first = idx
                last = idx
        return (first if first >= 0 else 0, last)

    def _on_scroll(self, *_a) -> None:
        self.update()
        self._debounce.start()

    def _emit_range(self) -> None:
        first, last = self.visible_range()
        self.visible_range_changed.emit(first, last)

    # ---------------- 交互 ----------------
    def wheelEvent(self, e) -> None:
        # 图片墙加速滚动：每格滚轮至少滚动一行高度
        step = max(120, self.row_height)
        dy = e.angleDelta().y()
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() - int(dy / 120 * step))
        e.accept()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self.index_at(e.position())
            if idx >= 0:
                self.item_clicked.emit(idx)
                return
        super().mousePressEvent(e)

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor("#202124"))
        v = self.verticalScrollBar().value()
        p.translate(0, -v)
        view_top, view_bot = v, v + self.viewport().height()
        tier = 512 if self.row_height > 256 else 256
        for item, cell in zip(self._items, self._cells):
            if cell is None or cell.bottom() < view_top or cell.y() > view_bot:
                continue
            if item.corrupted:
                p.fillRect(cell, QColor("#3a3b3e"))
                p.setPen(QColor("#e57373"))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, "已损坏")
            else:
                key = f"{item.path}|{tier}"
                pix = QPixmapCache.find(key)
                if pix is None or pix.isNull():
                    if self.image_root is not None:
                        fp = thumbnail.thumb_path(self.image_root, item, tier)
                        if fp.exists():
                            pix = QPixmap(str(fp))
                            if not pix.isNull():
                                QPixmapCache.insert(key, pix)
                if pix is not None and not pix.isNull():
                    scaled = pix.scaled(cell.size(),
                                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
                    sx = (scaled.width() - cell.width()) // 2
                    sy = (scaled.height() - cell.height()) // 2
                    p.drawPixmap(cell, scaled, QRect(sx, sy, cell.width(), cell.height()))
                else:
                    p.fillRect(cell, QColor("#2c2d31"))
            if item.favorite:
                f = p.font()
                f.setBold(True)
                f.setPixelSize(15)
                p.setFont(f)
                p.setPen(QColor("#ffd54f"))
                p.drawText(QRect(cell.x() + 4, cell.y() + 2, 20, 20),
                           Qt.AlignmentFlag.AlignCenter, "★")
            if item.dup_group >= 0:
                p.setBrush(QColor("#1e88e5"))
                p.setPen(Qt.PenStyle.NoPen)
                badge = QRect(cell.right() - 20, cell.y() + 4, 16, 16)
                p.drawEllipse(badge)
                p.setPen(QColor("white"))
                f = p.font()
                f.setBold(False)
                f.setPixelSize(10)
                p.setFont(f)
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, "重")
        p.end()
