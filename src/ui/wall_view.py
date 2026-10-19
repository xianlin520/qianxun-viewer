# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""图片墙视图（滚动模式）：justified 无缝拼接布局，不显示文件名。

每行按宽高比贪心凑满视口宽度，行高接近滑块目标值；
图片以 cover 方式裁切填充单元格，保证行间无缝隙。
"""
from __future__ import annotations

import bisect

from PySide6.QtCore import QPoint, QRect, Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPixmapCache
from PySide6.QtWidgets import QAbstractScrollArea

from ..core import thumbnail
from .theme import ACCENT, BG_APP, BG_CARD_HOVER, BG_CORRUPTED, DANGER, DUP, STAR


def _wheel_delta(e) -> int:
    """统一取滚轮增量。

    鼠标滚轮给 angleDelta（1/8 度）；触控板/高精度设备只有 pixelDelta，
    angleDelta 为 0。只读 angleDelta 会让触控板完全滚不动（且事件还被吞掉）。"""
    d = e.angleDelta().y()
    if d:
        return d
    return int(e.pixelDelta().y() * 3)   # 像素量级与角度量级不同，约 3 倍折算


class WallView(QAbstractScrollArea):
    item_clicked = Signal(int)              # view_items 下标
    visible_range_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._cells: list = []
        self._rows: list[tuple[int, int, int]] = []   # (行顶 y, 首下标, 末下标)
        self._row_tops: list[int] = []                # 行顶列表，供二分
        self._total_h = 0
        self.row_height = 180
        self.image_root = None
        self._focus = -1
        self.selection: set[int] = set()   # 多选集合（Ctrl/Shift）
        self._anchor: int | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # 视口上的滚轮事件不会走到子类的 wheelEvent，
        # 用事件过滤器在视口上拦截保证加速滚动生效
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._emit_range)
        # 拖窗口边会连续 resize，防抖后再重排
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(60)
        self._relayout_timer.timeout.connect(self.relayout)

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
        rows: list[tuple[int, int, int]] = []   # (行顶 y, 首下标, 末下标)
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
            rows.append((y, i, j))
            y += row_h
            i = j + 1
        self._cells = cells
        self._rows = rows
        self._row_tops = [r[0] for r in rows]
        self._total_h = y
        sb = self.verticalScrollBar()
        sb.setRange(0, max(0, y - self.viewport().height()))
        sb.setPageStep(max(1, self.viewport().height()))
        sb.setSingleStep(120)
        self._debounce.start()

    def _visible_rows(self, top: int, bot: int) -> tuple[int, int]:
        """返回与 [top, bot] 相交的行区间 [首行, 末行]（含），用二分定位。"""
        if not self._rows:
            return (0, -1)
        # 首个「行底 >= top」的行：行顶列表上二分后回退一位即可覆盖跨行
        k = bisect.bisect_right(self._row_tops, top) - 1
        first = max(0, k)
        last = first
        while last + 1 < len(self._rows) and self._rows[last + 1][0] <= bot:
            last += 1
        return (first, last)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # 拖窗口边会连续触发 resize，防抖后再重排，避免每帧都跑全量贪心
        self._relayout_timer.start()

    # ---------------- 命中与可见范围 ----------------
    def index_at(self, view_pos) -> int:
        p = QPoint(int(view_pos.x()), int(view_pos.y()) + self.verticalScrollBar().value())
        # 先二分定位到行，再只在该行内找格子（原实现对全部格子线性扫描）
        if self._rows:
            k = bisect.bisect_right(self._row_tops, p.y()) - 1
            if k >= 0:
                for idx in range(self._rows[k][1], self._rows[k][2] + 1):
                    cell = self._cells[idx]
                    if cell is not None and cell.contains(p):
                        return idx
            return -1
        for idx, cell in enumerate(self._cells):
            if cell is not None and cell.contains(p):
                return idx
        return -1

    def visible_range(self) -> tuple[int, int]:
        v = self.verticalScrollBar().value()
        bot = v + self.viewport().height()
        first_row, last_row = self._visible_rows(v, bot)
        if last_row < first_row:
            return (0, -1)
        return (self._rows[first_row][1], self._rows[last_row][2])

    def _on_scroll(self, *_a) -> None:
        self.update()
        self._debounce.start()

    def _emit_range(self) -> None:
        first, last = self.visible_range()
        self.visible_range_changed.emit(first, last)

    # ---------------- 交互 ----------------
    def eventFilter(self, obj, e) -> bool:
        if obj is self.viewport() and e.type() == QEvent.Type.Wheel:
            self._wheel_scroll(_wheel_delta(e))
            return True
        return super().eventFilter(obj, e)

    def wheelEvent(self, e) -> None:
        self._wheel_scroll(_wheel_delta(e))
        e.accept()

    def _wheel_scroll(self, dy: int) -> None:
        # 图片墙加速滚动：每格滚轮至少滚动一行高度
        if not dy:
            return
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
        # 键盘导航：方向键移动焦点并同步选择，Enter 进大图
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
            # 焦点必须与选择同步：否则方向键移动蓝框后，
            # Del / F / Ctrl+C 仍作用在旧的 selection 上，移错文件
            self.selection = {new}
            self._anchor = new
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
        p.fillRect(self.viewport().rect(), QColor(BG_APP))
        v = self.verticalScrollBar().value()
        p.translate(0, -v)
        view_top, view_bot = v, v + self.viewport().height()
        tier = 512 if self.row_height > 256 else 256
        # 只遍历可见行（原实现每帧遍历全部 items，2 万张时约 9.5ms 纯循环开销）
        first_row, last_row = self._visible_rows(view_top, view_bot)
        if last_row < first_row:
            p.end()
            return
        start = self._rows[first_row][1]
        end = self._rows[last_row][2]
        for idx in range(start, end + 1):
            item = self._items[idx]
            cell = self._cells[idx]
            if cell is None:
                continue
            if item.corrupted:
                p.fillRect(cell, QColor(BG_CORRUPTED))
                p.setPen(QColor(DANGER))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, "已损坏")
            else:
                # 已按目标像素裁好缓存：命中则直接贴图，
                # 避免每帧对每个可见格重复做一次 SmoothTransformation
                ck = thumbnail.cache_key(item)
                skey = f"{ck}|{tier}|{cell.width()}x{cell.height()}|c"
                scaled = QPixmapCache.find(skey)
                if scaled is None or scaled.isNull():
                    key = f"{ck}|{tier}"
                    pix = QPixmapCache.find(key)
                    if pix is None or pix.isNull():
                        if self.image_root is not None:
                            fp = thumbnail.thumb_path(self.image_root, item, tier)
                            if fp.exists():
                                pix = QPixmap(str(fp))
                                if not pix.isNull():
                                    QPixmapCache.insert(key, pix)
                    if pix is not None and not pix.isNull():
                        scaled = pix.scaled(
                            cell.size(),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
                        QPixmapCache.insert(skey, scaled)
                if scaled is not None and not scaled.isNull():
                    sx = (scaled.width() - cell.width()) // 2
                    sy = (scaled.height() - cell.height()) // 2
                    p.drawPixmap(cell, scaled, QRect(sx, sy, cell.width(), cell.height()))
                else:
                    p.fillRect(cell, QColor(BG_CARD_HOVER))
            if item.favorite:
                f = p.font()
                f.setBold(True)
                f.setPixelSize(15)
                p.setFont(f)
                p.setPen(QColor(STAR))
                p.drawText(QRect(cell.x() + 4, cell.y() + 2, 20, 20),
                           Qt.AlignmentFlag.AlignCenter, "★")
            if item.dup_group >= 0:
                p.setBrush(QColor(DUP))
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
                p.setPen(QColor(ACCENT))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(cell.adjusted(1, 1, -1, -1))
                p.setPen(pen)
            if idx in self.selection:
                pen = p.pen()
                p.setPen(QColor(STAR))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(cell.adjusted(2, 2, -2, -2))
                p.setPen(pen)
        p.end()
