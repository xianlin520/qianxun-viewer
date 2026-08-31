# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""千寻图片查看器入口。"""
import sys

from PySide6.QtGui import QPixmapCache
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.paths import base_dir
from src import meta


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("QianXunViewer")
    app.setOrganizationName("QianXun")
    app.setApplicationVersion(meta.VERSION)
    app.setStyle("Fusion")
    QPixmapCache.setCacheLimit(300 * 1024)  # KB：网格缩略图 QPixmap 内存缓存上限
    qss = base_dir() / "src" / "ui" / "styles.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text("utf-8"))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
