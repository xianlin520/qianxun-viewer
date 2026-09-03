# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""主窗体：工具栏 / 网格 / 分页 / 状态栏 / 快捷键 / 状态恢复。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QIcon, QActionGroup
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSlider, QStatusBar, QToolBar, QVBoxLayout,
                               QWidget)

from .. import meta
from ..controllers import ASPECT_PRESETS, SORT_MODES, LibraryController
from ..core.settings import AppSettings
from ..utils import file_ops
from ..utils.paths import base_dir
from .cache_dialog import CacheDialog
from .duplicates_dialog import DuplicatesDialog
from .grid_view import GridView, ImageModel, ThumbDelegate
from .oss_dialogs import OssConfigDialog, UploadDialog
from .pager import PagerBar
from .settings_dialog import SettingsDialog
from .viewer import ViewerOverlay
from .wall_view import WallView

ASSETS = base_dir() / "assets"


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = AppSettings()
        self.setWindowTitle("千寻图片查看器")
        self.setWindowIcon(QIcon(str(ASSETS / "logo.png")))
        self.resize(1280, 720)
        geo = self.settings.window_geo
        if geo:
            self.restoreGeometry(geo)
        self.setAcceptDrops(True)

        self.model = ImageModel(self)
        self.delegate = ThumbDelegate(self)
        self.delegate.thumb_size = self.settings.thumb_size
        self.view = GridView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(self.delegate)
        self.view.setGridSize(self.delegate.sizeHint(None, None))
        self.pager = PagerBar(self)
        self.view.pager = self.pager
        self.pager.hide()
        self.wall = WallView(self)
        self._hint = QLabel("点击「打开目录」或将文件夹拖拽到窗口\n加载图片目录", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("color:#8a8f98;font-size:15px;background:transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._build_toolbar(lay)
        lay.addWidget(self.wall, 1)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.pager, 0)
        self._status = QStatusBar(self)
        lay.addWidget(self._status, 0)

        self.controller = LibraryController(self.model, self.view,
                                            self.delegate, self.settings)
        self.viewer = ViewerOverlay(self, self.controller)
        self._click_was_selected = False
        self._ratio_hinted = False
        self._wire()
        self._restore_state()

    # ---------------- 构建 ----------------
    def _build_toolbar(self, lay) -> None:
        tb = QToolBar("工具栏")
        tb.setMovable(False)
        tb.setFloatable(False)
        lay.addWidget(tb)

        self.btn_open = QPushButton("打开目录")
        tb.addWidget(self.btn_open)

        self.combo_sort = QComboBox()
        for _key, label in SORT_MODES:
            self.combo_sort.addItem(label)
        tb.addWidget(self.combo_sort)

        self.btn_reseed = QPushButton("重新随机")
        tb.addWidget(self.btn_reseed)

        tb.addWidget(QLabel(" 缩略图 "))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(96, 320)
        self.slider.setFixedWidth(140)
        tb.addWidget(self.slider)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索文件名…")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.setFixedWidth(160)
        tb.addWidget(self.edit_search)

        self.combo_folder = QComboBox()
        self.combo_folder.setFixedWidth(140)
        self.combo_folder.setToolTip("按子文件夹筛选（含其子树）")
        tb.addWidget(self.combo_folder)

        self.btn_mode = QPushButton("分页模式")
        self.btn_mode.setCheckable(True)
        tb.addWidget(self.btn_mode)

        self.btn_online = QPushButton("在线库")
        self.btn_online.setCheckable(True)
        tb.addWidget(self.btn_online)

        self.btn_more = QPushButton("更多 ▾")
        tb.addWidget(self.btn_more)

        # ---- 「更多」菜单：收纳低频操作，工具栏保持精简 ----
        self.menu_more = QMenu(self)
        self.act_refresh = self.menu_more.addAction("刷新 (F5)")
        self.act_dup = self.menu_more.addAction("查找重复")
        self.act_fav = self.menu_more.addAction("仅看最爱")
        self.act_fav.setCheckable(True)
        self.menu_aspect = self.menu_more.addMenu("长宽比筛选")
        self._aspect_group = QActionGroup(self)
        self._aspect_group.setExclusive(True)
        for p in ASPECT_PRESETS:
            a = self.menu_aspect.addAction(p)
            a.setCheckable(True)
            self._aspect_group.addAction(a)
            a.triggered.connect(lambda _=False, t=p: self._apply_aspect(t))
        self.menu_aspect.addSeparator()
        self._aspect_custom_act = None
        self.menu_aspect.addAction("自定义…").triggered.connect(
            self._custom_aspect)
        self.menu_more.addSeparator()
        self.act_trash = self.menu_more.addAction("垃圾桶")
        self.act_trash.setCheckable(True)
        self.act_upload = self.menu_more.addAction("上传到云")
        self.menu_more.addSeparator()
        self.act_cache = self.menu_more.addAction("缓存管理")
        self.act_settings = self.menu_more.addAction("设置")
        self.act_about = self.menu_more.addAction("关于")
        self.btn_more.setMenu(self.menu_more)

    def _wire(self) -> None:
        self.btn_open.clicked.connect(self._open_dir)
        self.act_refresh.triggered.connect(self.controller.reload_current)
        self.combo_sort.currentIndexChanged.connect(
            lambda i: self.controller.set_sort(SORT_MODES[i][0]))
        self.btn_reseed.clicked.connect(self.controller.reseed)
        self.slider.valueChanged.connect(self.controller.set_thumb_size)
        self.act_fav.toggled.connect(self.controller.set_fav_only)
        self.act_fav.toggled.connect(lambda _on: self._sync_more_badge())
        self.act_dup.triggered.connect(
            lambda: self.controller.find_duplicates(True))
        self.btn_mode.toggled.connect(
            lambda on: self.controller.set_view_mode("page" if on else "scroll"))
        self.btn_mode.toggled.connect(lambda _on: self._sync_mode_ui())
        self.act_settings.triggered.connect(self._open_settings)
        self.act_about.triggered.connect(self._show_about)
        self.act_cache.triggered.connect(
            lambda: CacheDialog(self.controller, self).show())
        self.act_upload.triggered.connect(
            lambda: UploadDialog(self.controller, self).show())
        self.btn_online.toggled.connect(self._on_online_toggled)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(
            lambda: self.controller.set_filter(self.edit_search.text()))
        self.edit_search.textChanged.connect(lambda _t: self._search_timer.start())
        self.combo_folder.currentIndexChanged.connect(self._on_folder_changed)
        self.controller.scan_done.connect(self._refresh_folders)

        self.view.visible_range_changed.connect(self.controller.ensure_visible_thumbs)
        self.view.geometry_changed.connect(self.controller.on_view_resized)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.pressed.connect(self._on_pressed)
        self.view.clicked.connect(self._on_clicked)
        self.view.card_action.connect(self._on_card_action)
        self.pager.page_changed.connect(self.controller.set_page)

        self.wall.visible_range_changed.connect(self.controller.ensure_visible_thumbs)
        self.wall.item_clicked.connect(lambda i: self.viewer.open_at(i))
        self.wall.customContextMenuRequested.connect(self._wall_context)
        self.controller.wall_update.connect(self.wall.update)
        self.act_trash.toggled.connect(self._on_trash_toggled)
        self.act_trash.toggled.connect(lambda _on: self._sync_more_badge())
        self.slider.valueChanged.connect(self._on_slider)

        self.controller.status.connect(
            lambda m, t: self._status.showMessage(m, t))
        self.controller.title_changed.connect(self.setWindowTitle)
        self.controller.dups_ready.connect(self._show_dups)
        self.controller.view_reset.connect(self._on_view_reset)
        self.controller.scan_done.connect(self._restore_scroll)

        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("F5"), self, self.controller.reload_current)
        QShortcut(QKeySequence("R"), self,
                  self._guard(lambda: self.controller.trash_mode and [
                      self.controller.restore_item(i) for i in self._selected_items()]))
        # 大图浏览器打开时由 viewer 自行处理按键，避免双重触发
        QShortcut(QKeySequence("F"), self,
                  self._guard(lambda: [self.controller.toggle_favorite(i)
                                       for i in self._selected_items()]))
        QShortcut(QKeySequence("Del"), self,
                  self._guard(lambda: [self.controller.remove_item(i)
                                       for i in self._selected_items()]))
        QShortcut(QKeySequence("Ctrl+S"), self,
                  self._guard(lambda: self._selected_items() and self._save(
                      self._selected_items()[0])))
        QShortcut(QKeySequence("Ctrl+C"), self,
                  self._guard(lambda: self._selected_items() and self.controller.copy_item(
                      self._selected_items()[0])))
        QShortcut(QKeySequence("Ctrl+O"), self,
                  self._guard(lambda: self._selected_items() and self.controller.reveal_item(
                      self._selected_items()[0])))

    def _guard(self, fn):
        def wrapper():
            if not self.viewer.isVisible():
                fn()
        return wrapper

    # ---------------- 视图模式 / 垃圾桶 ----------------
    def _on_view_reset(self) -> None:
        self.wall.image_root = self.controller.cache_root
        self.wall.set_items(self.controller.view_items)
        self._update_hint()
        if self.controller.view_mode == "page":
            self.controller.ensure_visible_thumbs(*self.view.visible_range())
        else:
            self.controller.ensure_visible_thumbs(*self.wall.visible_range())

    def _sync_mode_ui(self) -> None:
        page = self.controller.view_mode == "page"
        self.wall.setVisible(not page)
        self.view.setVisible(page)
        self.delegate.show_buttons = page
        self.view.buttons_enabled = page
        self.view.setGridSize(self.delegate.sizeHint(None, None))
        if page:
            self.controller.ensure_visible_thumbs(*self.view.visible_range())
        else:
            self.controller.ensure_visible_thumbs(*self.wall.visible_range())

    def _on_slider(self, value: int) -> None:
        self.wall.row_height = value
        self.wall.relayout()

    def _on_folder_changed(self, idx: int) -> None:
        if idx <= 0:
            self.controller.set_folder_filter("")
        else:
            self.controller.set_folder_filter(self.combo_folder.currentText())

    def _refresh_folders(self) -> None:
        cur = self.combo_folder.currentText()
        self.combo_folder.blockSignals(True)
        self.combo_folder.clear()
        self.combo_folder.addItem("全部文件夹")
        self.combo_folder.addItems(self.controller.available_folders())
        i = self.combo_folder.findText(cur)
        self.combo_folder.setCurrentIndex(i if i >= 0 else 0)
        self.combo_folder.blockSignals(False)
        if i > 0:
            self.controller.set_folder_filter(cur)

    def _sync_more_badge(self) -> None:
        """「更多」按钮上以 ● 提示菜单内有生效中的状态。"""
        act = self._aspect_group.checkedAction()
        aspect_on = act is not None and act.text() not in ("", ASPECT_PRESETS[0])
        active = (self.act_fav.isChecked() or self.act_trash.isChecked()
                  or aspect_on)
        self.btn_more.setText("更多 ●" if active else "更多 ▾")

    def _apply_aspect(self, text: str) -> None:
        self.controller.set_aspect(text)
        self._sync_more_badge()

    def _custom_aspect(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        cur = ""
        if self._aspect_custom_act is not None:
            cur = self._aspect_custom_act.text().replace("自定义 ", "")
        text, ok = QInputDialog.getText(
            self, "自定义长宽比",
            "输入比例如 1.5:3，或单个浮点（宽÷高）：", text=cur)
        if not ok or not text.strip():
            return
        t = text.strip()
        if self._aspect_custom_act is None:
            a = self.menu_aspect.addAction("")
            a.setCheckable(True)
            self._aspect_group.addAction(a)
            a.triggered.connect(
                lambda _=False: self._apply_aspect(
                    self._aspect_custom_act.text().replace("自定义 ", "")))
            self._aspect_custom_act = a
        self._aspect_custom_act.setText(f"自定义 {t}")
        self._aspect_custom_act.setChecked(True)
        self._apply_aspect(t)

    def _on_online_toggled(self, on: bool) -> None:
        if on and not self.controller.oss_configured():
            OssConfigDialog(self.settings, self).exec()
        if on and not self.controller.oss_configured():
            self.btn_online.blockSignals(True)
            self.btn_online.setChecked(False)
            self.btn_online.blockSignals(False)
            return
        ok = self.controller.set_online(on)
        if not ok:
            self.btn_online.blockSignals(True)
            self.btn_online.setChecked(False)
            self.btn_online.blockSignals(False)
        self._sync_mode_ui()

    def _on_trash_toggled(self, on: bool) -> None:
        self.act_fav.blockSignals(True)
        self.act_fav.setChecked(False)
        self.act_fav.blockSignals(False)
        self.controller.set_fav_only(False)
        self.delegate.trash_mode = on
        self.controller.set_trash_mode(on)
        self._sync_mode_ui()

    def _update_hint(self) -> None:
        if self.controller.root is None:
            self._hint.setText("点击「打开目录」或将文件夹拖拽到窗口\n加载图片目录")
            self._hint.show()
        elif not self.controller.all_items:
            self._hint.setText("垃圾桶是空的" if self.controller.trash_mode
                               else "该目录下没有图片")
            self._hint.show()
        else:
            self._hint.hide()
        self._hint.raise_()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, f"关于 {meta.APP_NAME}",
            f"<b>{meta.APP_NAME}</b> {meta.APP_EN} v{meta.VERSION}<br><br>"
            f"缩略图优先 · 全程异步 · 无损操作<br><br>{meta.COPYRIGHT}")

    # ---------------- 拖拽加载 ----------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                if self.act_trash.isChecked():
                    self.act_trash.blockSignals(True)
                    self.act_trash.setChecked(False)
                    self.act_trash.blockSignals(False)
                    self.delegate.trash_mode = False
                self.controller.load_directory(p)
                e.acceptProposedAction()
                return

    # ---------------- 状态恢复 ----------------
    def _restore_state(self) -> None:
        s = self.settings
        self.btn_mode.blockSignals(True)
        self.btn_mode.setChecked(s.view_mode == "page")
        self.btn_mode.blockSignals(False)
        self.controller.set_view_mode(s.view_mode or "scroll", persist=False)

        keys = [k for k, _ in SORT_MODES]
        mode = s.sort_mode if s.sort_mode in keys else "random"
        self.combo_sort.blockSignals(True)
        self.combo_sort.setCurrentIndex(keys.index(mode))
        self.combo_sort.blockSignals(False)
        self.controller.sort_mode = mode

        self.slider.blockSignals(True)
        self.slider.setValue(self.delegate.thumb_size)
        self.slider.blockSignals(False)
        self.controller.set_thumb_size(self.delegate.thumb_size)
        self.wall.row_height = self.delegate.thumb_size

        self.controller.page = s.last_page
        self._sync_mode_ui()
        start = s.default_open_dir or (
            s.last_dir if s.auto_load_last else "")
        if start and Path(start).is_dir():
            self.controller.load_directory(Path(start))

    def _restore_scroll(self) -> None:
        root = self.controller.root
        if (root and str(root) == self.settings.last_dir
                and self.controller._scroll_restored_for != str(root)):
            self.controller._scroll_restored_for = str(root)
            self.view.verticalScrollBar().setValue(self.settings.last_scroll)

    def closeEvent(self, e) -> None:
        s = self.settings
        if self.controller.root:
            s.last_dir = str(self.controller.root)
        s.view_mode = self.controller.view_mode
        s.sort_mode = self.controller.sort_mode
        s.thumb_size = self.delegate.thumb_size
        s.last_page = self.controller.page
        s.last_scroll = self.view.verticalScrollBar().value()
        s.window_geo = self.saveGeometry()
        s.sync()
        # 通知工作线程取消并等待线程池收尾，
        # 避免网络 IO 任务在解释器退出时阻塞进程（后台残留）
        self.controller.request_cancel()
        self.controller.pool.waitForDone(4000)
        self.controller.move_pool.waitForDone(2000)
        super().closeEvent(e)

    # ---------------- 交互 ----------------
    def _open_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择图片目录",
                                             str(self.controller.main_root or self.controller.root or ""))
        if d:
            if self.act_trash.isChecked():
                self.act_trash.blockSignals(True)
                self.act_trash.setChecked(False)
                self.act_trash.blockSignals(False)
                self.delegate.trash_mode = False
            self.controller.load_directory(Path(d))

    def _open_settings(self) -> None:
        SettingsDialog(self.settings, self).exec()

    def _selected_items(self) -> list:
        if self.controller.view_mode == "page":
            rows = sorted({i.row() for i in self.view.selectedIndexes()})
            items = self.model.items()
            return [items[r] for r in rows if r < len(items)]
        vi = self.controller.view_items
        return [vi[i] for i in sorted(self.wall.selection) if i < len(vi)]

    def _on_pressed(self, index) -> None:
        self._click_was_selected = index.row() in {
            i.row() for i in self.view.selectedIndexes()}

    def _on_clicked(self, index) -> None:
        # 再次点击已选中的缩略图 → 进入大图浏览器
        if self._click_was_selected:
            self._open_viewer_at(index.row())

    def _open_viewer_at(self, model_row: int) -> None:
        items = self.model.items()
        if model_row >= len(items):
            return
        item = items[model_row]
        try:
            vi = self.controller.view_items.index(item)
        except ValueError:
            return
        self.viewer.open_at(vi)

    def _context_menu(self, pos) -> None:
        items = self._selected_items()
        if not items:
            return
        menu, acts = self._build_menu(items)
        self._run_menu_action(menu.exec(self.view.mapToGlobal(pos)), acts, items)

    def _wall_context(self, pos) -> None:
        idx = self.wall.index_at(pos)
        if idx < 0 or idx >= len(self.controller.view_items):
            return
        items = self._selected_items() or [self.controller.view_items[idx]]
        menu, acts = self._build_menu(items)
        self._run_menu_action(menu.exec(self.wall.mapToGlobal(pos)), acts, items)

    def _build_menu(self, items) -> tuple:
        menu = QMenu(self)
        acts = {}
        acts["share"] = menu.addAction("复制外链（限时签名）")
        acts["share_perm"] = menu.addAction("复制永久链接（对象公共读）")
        acts["revoke_perm"] = menu.addAction("撤回永久公开")
        if self.controller.online_mode:
            acts["copy"] = menu.addAction("复制图片")
            return menu, acts
        if self.controller.trash_mode:
            acts["restore"] = menu.addAction("还原")
            acts["reveal"] = menu.addAction("打开所在位置 (Ctrl+O)")
            acts["copy"] = menu.addAction("复制图片 (Ctrl+C)")
        else:
            acts["fav"] = menu.addAction("切换最爱 (F)")
            acts["save"] = menu.addAction("另存为 (Ctrl+S)")
            acts["copy"] = menu.addAction("复制图片 (Ctrl+C)")
            acts["copyfile"] = menu.addAction("复制文件")
            acts["reveal"] = menu.addAction("打开所在位置 (Ctrl+O)")
            acts["remove"] = menu.addAction("移出图片 (Del)")
        return menu, acts

    def _run_menu_action(self, act, acts, items) -> None:
        if act is None:
            return
        dispatch = {
            "share": lambda: self._copy_share_link(items[0]),
            "share_perm": lambda: self._copy_share_link(items[0], True),
            "revoke_perm": lambda: self._revoke_share(items[0]),
            "fav": lambda: [self.controller.toggle_favorite(i) for i in items],
            "save": lambda: self._save(items[0]),
            "copy": lambda: self.controller.copy_item(items[0]),
            "copyfile": lambda: file_ops.copy_file(items[0].path),
            "reveal": lambda: self.controller.reveal_item(items[0]),
            "remove": lambda: [self.controller.remove_item(i) for i in items],
            "restore": lambda: [self.controller.restore_item(i) for i in items],
        }
        for key, action in acts.items():
            if action == act:
                dispatch[key]()
                return

    def _on_card_action(self, action, index) -> None:
        items = self.model.items()
        if index.row() >= len(items):
            return
        item = items[index.row()]
        if action == "fav":
            self.controller.toggle_favorite(item)
        elif action == "save":
            self._save(item)
        elif action == "copy":
            self.controller.copy_item(item)
        elif action == "reveal":
            self.controller.reveal_item(item)
        elif action == "remove":
            self.controller.remove_item(item)
        elif action == "restore":
            self.controller.restore_item(item)

    def _copy_share_link(self, item, permanent: bool = False) -> None:
        if (self.controller.oss_configured() and not item.remote_key
                and not self.controller.resolve_cloud_key(item)):
            ans = QMessageBox.question(
                self, "未上传到云",
                "该图片尚未上传到云，是否立即上传并获取链接？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if ans != QMessageBox.StandardButton.Yes:
                return
            if not self.controller.upload_one(item):
                return
        link = self.controller.share_link(item, permanent)
        if link:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(link)
            msg = ("已复制永久链接（对象已设公共读）" if permanent
                   else "已复制签名外链（限时有效）")
            self._status.showMessage(msg, 3000)

    def _revoke_share(self, item) -> None:
        if self.controller.revoke_share(item):
            self._status.showMessage("已撤回永久公开（恢复私有）", 3000)

    def _save(self, item) -> None:
        if not self.controller.save_item(item):
            d = QFileDialog.getExistingDirectory(self, "选择保存目录")
            if d:
                try:
                    dst = file_ops.save_as(item.path, Path(d))
                    self._status.showMessage(f"已保存：{dst.name}", 3000)
                except Exception as exc:
                    self._status.showMessage(f"保存失败：{exc}", 5000)

    def _show_dups(self, groups) -> None:
        DuplicatesDialog(self.controller, groups, self).show()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.viewer.isVisible():
            self.viewer.setGeometry(self.rect())
        self._hint.setGeometry(self.wall.geometry())
        if not self._ratio_hinted and self.height() > 0:
            if abs(self.width() / self.height() - 2.0) > 0.6:
                self._ratio_hinted = True
                self._status.showMessage("提示：最佳窗口比例约为 2:1", 4000)
