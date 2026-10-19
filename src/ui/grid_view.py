# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""网格视图：QListView(IconMode) + 自定义 Delegate 绘制缩略图卡片。"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QPoint, QRect, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QPainter, QPixmap, QPixmapCache
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from ..core import thumbnail
from ..utils.format import human_size, human_time

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1
INFO_H = 24
PAD = 6
BUTTON_H = 26
CARD_ACTIONS = ["fav", "save", "copy", "reveal", "remove"]
CARD_GLYPHS = {"fav": "★", "save": "存", "copy": "拷", "reveal": "位", "remove": "移"}


class ImageModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._row_of: dict[str, int] = {}   # 路径 -> 行号，避免每次缩略图就绪都线性扫
        self.info_mode = "random"   # random / time / size

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == ROLE_ITEM:
            return item
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.path.name
        return None

    def items(self) -> list:
        return self._items

    def set_items(self, items) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._row_of = {str(it.path): i for i, it in enumerate(self._items)}
        self.endResetModel()

    def row_of_path(self, path_str: str) -> int:
        return self._row_of.get(path_str, -1)

    def info_text(self, item) -> str:
        if self.info_mode == "size":
            return f"{human_size(item.size_bytes)} · {item.width}×{item.height}"
        if self.info_mode == "time":
            return human_time(item.mtime)
        return item.path.name


class ThumbDelegate(QStyledItemDelegate):
    """卡片 = 缩略图 + 下方信息行 + 左上最爱星标 / 右上重复蓝标。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumb_size = 180
        self.image_root = None
        self.show_buttons = False   # 分页模式下卡片下方显示功能按钮
        self.trash_mode = False     # 垃圾桶模式下 “移” 换为 “还原”

    def sizeHint(self, option, index) -> QSize:
        h = self.thumb_size + PAD * 2 + INFO_H
        if self.show_buttons:
            h += BUTTON_H
        return QSize(self.thumb_size + PAD * 2, h)

    def actions(self) -> list:
        """当前模式下的按钮动作列表。"""
        acts = list(CARD_ACTIONS)
        if self.trash_mode:
            acts[acts.index("remove")] = "restore"
        return acts

    def glyph(self, action: str) -> str:
        if action == "restore":
            return "还原"
        return CARD_GLYPHS.get(action, "?")

    def button_rects(self, r: QRect) -> list:
        if not self.show_buttons:
            return []
        acts = self.actions()
        y = r.bottom() - BUTTON_H + 3
        h = BUTTON_H - 6
        w = (r.width() - 8) // len(acts)
        return [(a, QRect(r.x() + 4 + i * w, y, w, h)) for i, a in enumerate(acts)]

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(ROLE_ITEM)
        if item is None:
            return
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(QColor("#31406b"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor("#2c2d31"))
        else:
            painter.setBrush(QColor("#26272b"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, 6, 6)

        img_rect = QRect(r.x() + PAD, r.y() + PAD,
                         r.width() - PAD * 2,
                         r.height() - PAD * 2 - INFO_H - (BUTTON_H if self.show_buttons else 0))
        if item.corrupted:
            painter.fillRect(img_rect, QColor("#3a3b3e"))
            painter.setPen(QColor("#e57373"))
            painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "已损坏")
        else:
            tier = 512 if self.thumb_size > 256 else 256
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
                scaled = pix.scaled(img_rect.size(),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                x = img_rect.x() + (img_rect.width() - scaled.width()) // 2
                y = img_rect.y() + (img_rect.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            else:
                painter.fillRect(img_rect, QColor("#333438"))
                painter.setPen(QColor("#8a8f98"))
                painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "…")

        if item.favorite:
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(15)
            painter.setFont(f)
            painter.setPen(QColor("#ffd54f"))
            painter.drawText(QRect(r.x() + 4, r.y() + 2, 20, 20),
                             Qt.AlignmentFlag.AlignCenter, "★")
        if item.dup_group >= 0:
            painter.setBrush(QColor("#1e88e5"))
            painter.setPen(Qt.PenStyle.NoPen)
            badge = QRect(r.right() - 20, r.y() + 4, 16, 16)
            painter.drawEllipse(badge)
            painter.setPen(QColor("white"))
            f = painter.font()
            f.setBold(False)
            f.setPixelSize(10)
            painter.setFont(f)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "重")

        info_rect = QRect(r.x() + 2, r.bottom() - INFO_H + 2 - (BUTTON_H if self.show_buttons else 0),
                          r.width() - 4, INFO_H - 4)
        painter.setPen(QColor("#c7cbd4"))
        fm = painter.fontMetrics()
        text = fm.elidedText(index.model().info_text(item),
                             Qt.TextElideMode.ElideMiddle, info_rect.width())
        painter.drawText(info_rect, Qt.AlignmentFlag.AlignCenter, text)

        for action, brect in self.button_rects(r):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#3a3b3e"))
            painter.drawRoundedRect(brect, 4, 4)
            if action == "fav" and item.favorite:
                painter.setPen(QColor("#ffd54f"))
            elif action in ("remove", "restore"):
                painter.setPen(QColor("#e57373") if action == "remove" else QColor("#81c784"))
            else:
                painter.setPen(QColor("#c7cbd4"))
            painter.drawText(brect, Qt.AlignmentFlag.AlignCenter, self.glyph(action))
        painter.restore()


class GridView(QListView):
    visible_range_changed = Signal(int, int)
    geometry_changed = Signal()
    card_action = Signal(str, object)   # 动作名, QModelIndex

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(8)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pager = None  # 由主窗体注入
        self.buttons_enabled = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._emit_range)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._debounce.start())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._debounce.start()
        self.geometry_changed.emit()

    def mousePressEvent(self, e) -> None:
        # 分页模式下卡片功能按钮命中检测
        if self.buttons_enabled and e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            idx = self.indexAt(pos)
            d = self.itemDelegate()
            if idx.isValid() and d is not None:
                for action, brect in d.button_rects(self.visualRect(idx)):
                    if brect.contains(pos):
                        self.card_action.emit(action, idx)
                        return
        super().mousePressEvent(e)

    def _emit_range(self) -> None:
        first, last = self.visible_range()
        self.visible_range_changed.emit(first, last)

    def visible_range(self) -> tuple[int, int]:
        m = self.model()
        if m is None or m.rowCount() == 0:
            return 0, -1
        vp = self.viewport().rect()
        first = self.indexAt(vp.topLeft()).row()
        last = self.indexAt(QPoint(vp.left(), max(0, vp.bottom() - 1))).row()
        if first < 0:
            first = 0
        if last < 0:
            last = m.rowCount() - 1
        return first, last

    def page_capacity(self) -> int:
        d = self.itemDelegate()
        if d is None:
            return 1
        hint = d.sizeHint(None, None)
        sp = self.spacing()
        vp = self.viewport().size()
        cols = max(1, (vp.width() + sp) // (hint.width() + sp))
        rows = max(1, (vp.height() + sp) // (hint.height() + sp))
        return cols * rows
