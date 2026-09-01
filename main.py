# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""千寻图片查看器入口。"""
import sys

from PySide6.QtGui import QPixmapCache
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.paths import base_dir
from src import meta

_SINGLE_KEY = "QianXunViewer-SingleInstance"


def _acquire_single_instance() -> QLocalServer | None:
    """单实例保护：已有实例运行时返回 None 并通知其激活。"""
    sock = QLocalSocket()
    sock.connectToServer(_SINGLE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"activate")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return None
    QLocalServer.removeServer(_SINGLE_KEY)
    server = QLocalServer()
    if not server.listen(_SINGLE_KEY):
        return server  # 监听失败不阻断启动
    return server


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("QianXunViewer")
    app.setOrganizationName("QianXun")
    app.setApplicationVersion(meta.VERSION)
    server = _acquire_single_instance()
    if server is None:
        return 0  # 已通知现有实例，本进程退出
    app.setStyle("Fusion")
    QPixmapCache.setCacheLimit(300 * 1024)  # KB：网格缩略图 QPixmap 内存缓存上限
    qss = base_dir() / "src" / "ui" / "styles.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text("utf-8"))
    win = MainWindow()
    server.newConnection.connect(lambda: (win.showNormal(), win.raise_(),
                                          win.activateWindow()))
    app._qx_single_server = server  # 保持引用
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
