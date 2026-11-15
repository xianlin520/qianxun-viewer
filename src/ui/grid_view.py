# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""网格视图：QListView(IconMode) + 自定义 Delegate 绘制缩略图卡片。"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QPoint, QRect, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from .thumb_cache import THUMBS, ScaleMode, tier_for
from ..utils.format import human_size, human_time
from . import theme

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1
ROLE_INFO = Qt.ItemDataRole.UserRole + 2   # 信息行文案，delegate 只认这个角色
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
        if role == ROLE_INFO:
            # 通过角色暴露，delegate 不必知道模型是 ImageModel。
            # 插一层 QSortFilterProxyModel 做排序/过滤时，index.model()
            # 会变成代理对象，那里没有 info_text()，绘制会抛 AttributeError。
            return self.info_text(item)
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

    def card_size(self) -> QSize:
        """卡片尺寸的纯计算版本。

        外部调用方（分页容量、控制器）不该为了问尺寸而伪造 None 参数去调
        Qt 的虚函数 —— 当前 sizeHint 不读 option/index 才侥幸能跑，
        一旦有人给它加上 `if option.state & ...`，打开分页视图就 AttributeError。
        """
        h = self.thumb_size + PAD * 2 + INFO_H
        if self.show_buttons:
            h += BUTTON_H
        return QSize(self.thumb_size + PAD * 2, h)

    def sizeHint(self, option, index) -> QSize:   # noqa: ARG002
        return self.card_size()

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
            painter.setBrush(QColor(theme.BG_CARD_SEL))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor(theme.BG_CARD_HOVER))
        else:
            painter.setBrush(QColor(theme.BG_CARD))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, 6, 6)

        img_rect = QRect(r.x() + PAD, r.y() + PAD,
                         r.width() - PAD * 2,
                         r.height() - PAD * 2 - INFO_H - (BUTTON_H if self.show_buttons else 0))
        if item.corrupted:
            painter.fillRect(img_rect, QColor(theme.BG_CORRUPTED))
            painter.setPen(QColor(theme.DANGER))
            painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "已损坏")
        else:
            # 缓存键与缩放规则统一走 ThumbCache，视图不再自己拼键
            scaled = THUMBS.scaled(self.image_root, item, tier_for(self.thumb_size),
                                   img_rect.width(), img_rect.height(),
                                   ScaleMode.FIT)
            if scaled is not None:
                x = img_rect.x() + (img_rect.width() - scaled.width()) // 2
                y = img_rect.y() + (img_rect.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            else:
                painter.fillRect(img_rect, QColor(theme.BG_PLACEHOLDER))
                painter.setPen(QColor(theme.FG_MUTED))
                painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "…")

        if item.favorite:
            painter.save()          # 角标会改字体，必须成对 save/restore，
            painter.setPen(QColor(theme.STAR))   # 否则下方信息行字号被污染
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(15)
            painter.setFont(f)
            painter.drawText(QRect(r.x() + 4, r.y() + 2, 20, 20),
                             Qt.AlignmentFlag.AlignCenter, "★")
            painter.restore()
        if item.dup_group >= 0:
            painter.save()
            painter.setBrush(QColor(theme.DUP))
            painter.setPen(Qt.PenStyle.NoPen)
            badge = QRect(r.right() - 20, r.y() + 4, 16, 16)
            painter.drawEllipse(badge)
            painter.setPen(QColor("white"))
            f = painter.font()
            f.setBold(False)
            f.setPixelSize(10)
            painter.setFont(f)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "重")
            painter.restore()

        info_rect = QRect(r.x() + 2, r.bottom() - INFO_H + 2 - (BUTTON_H if self.show_buttons else 0),
                          r.width() - 4, INFO_H - 4)
        painter.setPen(QColor(theme.FG_SECONDARY))
        fm = painter.fontMetrics()
        text = fm.elidedText(index.data(ROLE_INFO) or "",
                             Qt.TextElideMode.ElideMiddle, info_rect.width())
        painter.drawText(info_rect, Qt.AlignmentFlag.AlignCenter, text)

        for action, brect in self.button_rects(r):
            painter.setPen(Qt.PenStyle.NoPen)
            # 按钮底色独立成 theme.BG_BUTTON：之前借用 theme.BG_CORRUPTED，
            # 改「损坏图」配色会连带改掉五个按钮的底色
            painter.setBrush(QColor(theme.BG_BUTTON))
            painter.drawRoundedRect(brect, 4, 4)
            if action == "fav" and item.favorite:
                painter.setPen(QColor(theme.STAR))
            elif action in ("remove", "restore"):
                painter.setPen(QColor(theme.DANGER) if action == "remove" else QColor(theme.SUCCESS))
            else:
                painter.setPen(QColor(theme.FG_SECONDARY))
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

        # 尺寸变化单独防抖。此前 resizeEvent 里既 start 防抖、又立刻
        # emit geometry_changed，等于拖窗口边缘时每个像素重算一次页容量，
        # 分页模式下列表跳动、单核打满；图片墙那边是 60ms 防抖，两边手感不一致。
        self._geo_debounce = QTimer(self)
        self._geo_debounce.setSingleShot(True)
        self._geo_debounce.setInterval(50)
        self._geo_debounce.timeout.connect(self.geometry_changed.emit)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._debounce.start()
        self._geo_debounce.start()

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
        # 视图还没完成布局时 indexAt 无命中。此前直接退化成「整个模型可见」，
        # 于是切换页/首次显示会对全部条目派发缩略图请求，大库下瞬间打满线程池。
        # 用一页容量做上界，宁可少报一屏也不全量。
        if first < 0:
            first = 0
            cache_cap = max(1, self.page_capacity())
        else:
            cache_cap = None
        if last < 0:
            cap = cache_cap or max(1, self.page_capacity())
            last = min(m.rowCount() - 1, first + cap - 1)
        return first, last

    def page_capacity(self) -> int:
        d = self.itemDelegate()
        if d is None:
            return 1
        # 默认 delegate 没有 card_size（只有本文件的 ThumbDelegate 有），
        # 这里兜一下，避免「换 delegate 后打开分页视图就崩」。
        size = getattr(d, "card_size", None)
        if callable(size):
            hint = size()
        else:
            from PySide6.QtWidgets import QStyleOptionViewItem
            hint = d.sizeHint(QStyleOptionViewItem(), QModelIndex())
        sp = self.spacing()
        vp = self.viewport().size()
        cols = max(1, (vp.width() + sp) // (hint.width() + sp))
        rows = max(1, (vp.height() + sp) // (hint.height() + sp))
        return cols * rows
