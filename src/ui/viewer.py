# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""大图浏览器：全屏覆盖层。滚轮缩放(1%~800%) / 拖拽平移 / ←→ 切换 / Esc 返回 / F 收藏。

先显示 512 档缓存图，DecodeWorker 后台解码原图完成后无缝替换。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget


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
        self._user_zoomed = False
        self._rotate = 0
        # 可见的操作按钮：上一张 / 下一张 / 旋转 / 退出
        self._btn_prev = QPushButton("‹", self)
        self._btn_next = QPushButton("›", self)
        self._btn_rotate = QPushButton("⟳", self)
        self._btn_close = QPushButton("✕", self)
        self._btn_prev.setToolTip("上一张 (←)")
        self._btn_next.setToolTip("下一张 (→)")
        self._btn_rotate.setToolTip("旋转 90° (R)")
        self._btn_close.setToolTip("退出 (Esc)")
        for b in (self._btn_prev, self._btn_next, self._btn_rotate, self._btn_close):
            b.setFixedSize(40, 40)
        self._btn_prev.clicked.connect(lambda: self.show_index(self._index - 1))
        self._btn_next.clicked.connect(lambda: self.show_index(self._index + 1))
        self._btn_rotate.clicked.connect(self.rotate90)
        self._btn_close.clicked.connect(self.hide)
        self.hide()

    # ---------------- 生命周期 ----------------
    def open_at(self, index: int) -> None:
        self.setGeometry(self.parentWidget().rect())
        self._place_buttons()
        self.show()
        self.raise_()
        self.setFocus()
        self.show_index(index)

    def _place_buttons(self) -> None:
        w = self.width()
        self._btn_close.move(w - 52, 12)
        self._btn_rotate.move(w - 96, 12)
        self._btn_next.move(w - 140, 12)
        self._btn_prev.move(w - 184, 12)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_buttons()

    def show_index(self, index: int) -> None:
        items = self.controller.view_items
        if not items:
            return
        self._index = max(0, min(index, len(items) - 1))
        item = items[self._index]
        self._pix = self.controller.fast_pixmap(item)   # 先 512 档缓存
        self._user_zoomed = False
        self._rotate = 0
        # 适应窗口但不放大超过 100%，避免小缓存图导致原图被拉得过大
        self._scale = min(self._fit_scale(), 1.0)
        self._offset = QPointF(0, 0)
        self.controller.request_decode(item, self._on_decoded)
        for d in (-1, 1):                                # 预加载前后各 1 张
            ni = self._index + d
            if 0 <= ni < len(items):
                self.controller.request_decode(items[ni], None)
        self.update()

    def _fit_scale(self) -> float:
        """适应窗口的缩放比；控件尚未布局（宽/高为 0）时返回 1.0。

        返回 0 会让 _scale=0，随后 wheelEvent 里的
        (mouse - center - offset) / _scale 直接除零；即使被 isNull 侥幸挡住，
        画面也会停在不可缩放的 0 倍状态。"""
        if self._pix.isNull():
            return 1.0
        r = self.rect()
        if r.width() <= 0 or r.height() <= 0:
            return 1.0
        pw, ph = self._pix.width(), self._pix.height()
        if self._rotate % 180 == 90:
            pw, ph = ph, pw
        if pw <= 0 or ph <= 0:
            return 1.0
        return min(r.width() / pw, r.height() / ph) * 0.95

    def rotate90(self) -> None:
        self._rotate = (self._rotate + 90) % 360
        if not self._user_zoomed:
            self._scale = min(self._fit_scale(), 1.0)
            self._offset = QPointF(0, 0)
        self.update()

    def _on_decoded(self, path_str, qimg) -> None:
        if self._index < 0:
            return
        cur = self.controller.view_items[self._index]
        if str(cur.path) == path_str:
            self._pix = QPixmap.fromImage(qimg)
            if not self._user_zoomed:
                # 原图到达后按原图重新适应（仍不超 100%）
                self._scale = min(self._fit_scale(), 1.0)
                self._offset = QPointF(0, 0)
            self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101112"))
        if not self._pix.isNull():
            p.translate(QPointF(self.rect().center()) + self._offset)
            p.scale(self._scale, self._scale)
            if self._rotate:
                p.rotate(self._rotate)
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
        if self._pix.isNull() or not self._scale:
            self._scale = self._fit_scale() or 1.0
        # 优先用 angleDelta（鼠标滚轮）；触控板/高精度设备只有 pixelDelta，
        # 此时若继续按 angleDelta 判定会把所有滚动当成“向下”而持续缩小。
        delta = e.angleDelta().y()
        if delta == 0:
            delta = e.pixelDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self._scale * factor))
        if new_scale == self._scale:
            return
        center = QPointF(self.rect().center())
        mouse = QPointF(e.position())
        world = (mouse - center - self._offset) / self._scale   # 锚定鼠标位置
        self._offset = mouse - center - world * new_scale
        self._scale = new_scale
        self._user_zoomed = True
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
            # 小图适应窗口会算出几十倍放大，必须夹到 MAX_SCALE 以内；
            # 同时对小图不应放大超过 100%，否则 40×40 会被糊成一片
            self._scale = max(self.MIN_SCALE,
                              min(fit, self.MAX_SCALE, 1.0))
        else:
            self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._user_zoomed = True
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
        elif k == Qt.Key.Key_R:
            self.rotate90()
        else:
            super().keyPressEvent(e)
