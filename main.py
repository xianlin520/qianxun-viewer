# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""入口：启动即拉起 Logo 启动画面，重型依赖延迟到闪屏之后加载。"""
import sys


def main() -> int:
    # 轻量依赖先行：闪屏必须尽快出现
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPixmapCache
    from PySide6.QtWidgets import QApplication, QSplashScreen

    app = QApplication(sys.argv)
    app.setApplicationName("QianXunViewer")
    app.setOrganizationName("QianXun")

    from src import meta
    from src.utils.paths import base_dir

    # 启动画面第一优先：Logo 尽快上屏，其余全部后置
    logo = QPixmap(str(base_dir() / "assets" / "logo.png"))
    splash = QSplashScreen(logo.scaled(
        220, 220, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.showMessage(
        f"千寻影集 v{meta.VERSION} 启动中…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        Qt.GlobalColor.darkGray)
    splash.show()
    app.processEvents()

    # 单实例保护：已有实例则激活并退出（闪屏已上屏后再做）
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    key = "QianXunViewer-SingleInstance"
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"activate")
        sock.flush()
        sock.waitForBytesWritten(500)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    app.setStyle("Fusion")

    app.setApplicationVersion(meta.VERSION)
    QPixmapCache.setCacheLimit(300 * 1024)  # KB：网格缩略图 QPixmap 内存缓存上限
    qss = base_dir() / "src" / "ui" / "styles.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text("utf-8"))

    # 重型依赖（PySide6 全模块/PIL/numpy/oss2 链）延迟到闪屏之后
    from src.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    splash.finish(win)

    def _activate() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(200)
            conn.disconnectFromServer()
        win.showNormal()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(_activate)
    app._qx_single_server = server  # 保持引用
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
