# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""图片墙视图（滚动模式）：justified 无缝拼接布局，不显示文件名。

每行按宽高比贪心凑满视口宽度，行高接近滑块目标值；
图片以 cover 方式裁切填充单元格，保证行间无缝隙。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QEvent, QTimer, Signal
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
        self._focus = -1
        self.selection: set[int] = set()   # 多选集合（Ctrl/Shift）
        self._anchor: int | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # 视口上的滚轮事件不会走到子类的 wheelEvent，
        # 用事件过滤器在 viewport 上拦截保证加速滚动生效
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._emit_range)

    # ---------------- 数据与布局 ----------------
    def set_items(self, items) -> None:
        self._items = list(items)
        if self._focus >= len(self._items):
            self._focus = -1
        self.selection.clear()
        self._anchor = None
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
            last_row = (j == n - 1)
            row_h = max(1, int(vp_w / ar_sum))
            if last_row:
                # 末行不拉伸铺满：按目标行高自然宽度左对齐，
                # 避免单张图被拉成巨型模糊块
                row_h = min(row_h, self.row_height)
            x = 0
            for k in range(i, j + 1):
                w = int(round(row_h * self._aspect(self._items[k])))
                if not last_row and k == j:
                    w = vp_w - x          # 行内无缝：末格取余宽
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
    def eventFilter(self, obj, e) -> bool:
        if obj is self.viewport() and e.type() == QEvent.Type.Wheel:
            self._wheel_scroll(e.angleDelta().y())
            return True
        return super().eventFilter(obj, e)

    def wheelEvent(self, e) -> None:
        self._wheel_scroll(e.angleDelta().y())
        e.accept()

    def _wheel_scroll(self, dy: int) -> None:
        # 图片墙加速滚动：每格滚轮至少滚动一行高度
        step = max(120, self.row_height)
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() - int(dy / 120 * step))

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self.index_at(e.position())
            mods = e.modifiers()
            if idx < 0:                      # 点空白清除选择
                self.selection.clear()
                self._anchor = None
                self.update()
                return
            if mods & Qt.KeyboardModifier.ControlModifier:
                if idx in self.selection:
                    self.selection.discard(idx)
                else:
                    self.selection.add(idx)
                self._anchor = idx
                self.update()
                return
            if mods & Qt.KeyboardModifier.ShiftModifier \
                    and self._anchor is not None:
                a, b = sorted((self._anchor, idx))
                self.selection = set(range(a, b + 1))
                self.update()
                return
            self.selection = {idx}
            self._anchor = idx
            self._focus = idx
            self.update()
            self.item_clicked.emit(idx)
            return
        if e.button() == Qt.MouseButton.RightButton:
            idx = self.index_at(e.position())
            if idx >= 0 and idx not in self.selection:
                self.selection = {idx}
                self._anchor = idx
                self.update()
        super().mousePressEvent(e)

    def keyPressEvent(self, e) -> None:
        # 键盘导航：方向键移动焦点，Enter 进大图
        n = len(self._items)
        if n == 0:
            super().keyPressEvent(e)
            return
        k = e.key()
        if k == Qt.Key.Key_Return or k == Qt.Key.Key_Enter:
            if self._focus >= 0:
                self.item_clicked.emit(self._focus)
            return
        if k not in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                     Qt.Key.Key_Up, Qt.Key.Key_Down):
            super().keyPressEvent(e)
            return
        if self._focus < 0:
            new = 0
        elif k == Qt.Key.Key_Left:
            new = max(0, self._focus - 1)
        elif k == Qt.Key.Key_Right:
            new = min(n - 1, self._focus + 1)
        else:
            new = self._vertical_neighbor(self._focus, up=(k == Qt.Key.Key_Up))
        if new != self._focus:
            self._focus = new
            self._ensure_visible(new)
            self.update()

    def _vertical_neighbor(self, idx: int, up: bool) -> int:
        cur = self._cells[idx]
        if cur is None:
            return idx
        cx = cur.center().x()
        best, best_d = idx, None
        for i, cell in enumerate(self._cells):
            if cell is None or i == idx:
                continue
            if up and cell.y() >= cur.y():
                continue
            if not up and cell.y() <= cur.y():
                continue
            d = abs(cell.center().x() - cx) + abs(cell.y() - cur.y()) * 0.01
            if best_d is None or d < best_d:
                best_d = d
                best = i
        return best

    def _ensure_visible(self, idx: int) -> None:
        cell = self._cells[idx]
        if cell is None:
            return
        sb = self.verticalScrollBar()
        v = sb.value()
        vp_h = self.viewport().height()
        if cell.y() < v:
            sb.setValue(cell.y())
        elif cell.bottom() > v + vp_h:
            sb.setValue(cell.bottom() - vp_h)

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor("#202124"))
        v = self.verticalScrollBar().value()
        p.translate(0, -v)
        view_top, view_bot = v, v + self.viewport().height()
        tier = 512 if self.row_height > 256 else 256
        for idx, (item, cell) in enumerate(zip(self._items, self._cells)):
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
            if idx == self._focus:
                pen = p.pen()
                p.setPen(QColor("#8ab4f8"))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(cell.adjusted(1, 1, -1, -1))
                p.setPen(pen)
            if idx in self.selection:
                pen = p.pen()
                p.setPen(QColor("#ffd54f"))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(cell.adjusted(2, 2, -2, -2))
                p.setPen(pen)
        p.end()
