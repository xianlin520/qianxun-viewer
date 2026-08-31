# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""大图浏览器：全屏覆盖层。滚轮缩放(1%~800%) / 拖拽平移 / ←→ 切换 / Esc 返回 / F 收藏。

先显示 512 档缓存图，DecodeWorker 后台解码原图完成后无缝替换。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class ViewerOverlay(QWidget):
    MIN_SCALE, MAX_SCALE = 0.01, 8.0

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self._pix = QPixmap()
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._index = -1
        self._drag_pos = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.hide()

    # ---------------- 生命周期 ----------------
    def open_at(self, index: int) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_index(index)

    def show_index(self, index: int) -> None:
        items = self.controller.view_items
        if not items:
            return
        self._index = max(0, min(index, len(items) - 1))
        item = items[self._index]
        self._pix = self.controller.fast_pixmap(item)   # 先 512 档缓存
        self._scale = self._fit_scale()
        self._offset = QPointF(0, 0)
        self.controller.request_decode(item, self._on_decoded)
        for d in (-1, 1):                                # 预加载前后各 1 张
            ni = self._index + d
            if 0 <= ni < len(items):
                self.controller.request_decode(items[ni], None)
        self.update()

    def _fit_scale(self) -> float:
        if self._pix.isNull():
            return 1.0
        r = self.rect()
        return min(r.width() / self._pix.width(), r.height() / self._pix.height()) * 0.95

    def _on_decoded(self, path_str, qimg) -> None:
        if self._index < 0:
            return
        cur = self.controller.view_items[self._index]
        if str(cur.path) == path_str:
            self._pix = QPixmap.fromImage(qimg)
            self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101112"))
        if not self._pix.isNull():
            p.translate(QPointF(self.rect().center()) + self._offset)
            p.scale(self._scale, self._scale)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._scale < 2.0)
            p.drawPixmap(QPoint(-self._pix.width() // 2, -self._pix.height() // 2), self._pix)
            p.resetTransform()
        if 0 <= self._index < len(self.controller.view_items):
            item = self.controller.view_items[self._index]
            p.setPen(QColor("#e8eaed"))
            star = "  ★" if item.favorite else ""
            p.drawText(12, 24, f"{item.path.name}{star}    "
                               f"{self._index + 1}/{len(self.controller.view_items)}    "
                               f"缩放 {self._scale * 100:.0f}%")
        p.end()

    # ---------------- 交互 ----------------
    def wheelEvent(self, e) -> None:
        if self._pix.isNull():
            return
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        new_scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self._scale * factor))
        if new_scale == self._scale:
            return
        center = QPointF(self.rect().center())
        mouse = QPointF(e.position())
        world = (mouse - center - self._offset) / self._scale   # 锚定鼠标位置
        self._offset = mouse - center - world * new_scale
        self._scale = new_scale
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_pos is not None:
            self._offset += e.position() - self._drag_pos
            self._drag_pos = e.position()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._drag_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, e) -> None:
        # 双击在 “适应窗口” 与 100% 之间切换
        if self._pix.isNull():
            return
        fit = self._fit_scale()
        if abs(self._scale - fit) > 1e-6:
            self._scale = fit
        else:
            self._scale = 1.0
        self._offset = QPointF(0, 0)
        self.update()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        items = self.controller.view_items
        if k == Qt.Key.Key_Escape:
            self.hide()
        elif k == Qt.Key.Key_Left:
            self.show_index(self._index - 1)
        elif k == Qt.Key.Key_Right:
            self.show_index(self._index + 1)
        elif k == Qt.Key.Key_F and 0 <= self._index < len(items):
            self.controller.toggle_favorite(items[self._index])
            self.update()
        else:
            super().keyPressEvent(e)
