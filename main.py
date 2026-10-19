# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""入口：启动即拉起 Logo 启动画面，重型依赖延迟到闪屏之后加载。"""
import sys
import time
from pathlib import Path

_MUTEX_NAME = "Global\\QianXunViewer-SingleInstance-Mutex"
_ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance_mutex():
    """用 Windows 命名互斥体判定是否已有实例在跑。

    返回互斥体句柄（本进程是首个实例）或 None（已有实例）。
    CreateMutexW 是内核级原子操作；本机实测 4 进程同时启动只有 1 个拿到。

    注意：不要换成 QLockFile —— 实测在本机 4 进程并发时有 2 个能同时拿到锁，
    也不要依赖 QLocalServer.removeServer + listen，二者组合不是原子操作，
    两个进程会互相摘掉对方注册的名字、各自 listen 成功，最终开出两个窗口。"""
    if not hasattr(__import__("ctypes"), "windll"):
        return object()          # 非 Windows：退化为不做单实例限制
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if not handle:
        return object()          # 创建失败时不要阻止启动
    return None if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS else handle


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

    # 单实例保护：已有实例则激活并退出（闪屏已上屏后再做）。
    # 用 Windows 命名互斥体做互斥：QLocalServer 的 removeServer+listen 不是原子操作，
    # QLockFile 本机实测也非可靠互斥（4 进程同时启动会 2 个拿到锁）。
    # CreateMutexW 是内核级原子操作，实测 4 进程并发只有 1 个 PRIMARY。
    _mutex = _acquire_single_instance_mutex()
    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    key = "QianXunViewer-SingleInstance"

    # 先尝试连上已有实例；连得上就直接让它激活
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"activate")
        sock.flush()
        sock.waitForBytesWritten(500)
        return 0

    if _mutex is None:
        # 已有实例：它可能还没 listen，短暂重试后再退出
        for _ in range(20):
            app.processEvents()
            sock = QLocalSocket()
            sock.connectToServer(key)
            if sock.waitForConnected(100):
                sock.write(b"activate")
                sock.flush()
                sock.waitForBytesWritten(300)
                break
            time.sleep(0.05)
        return 0

    QLocalServer.removeServer(key)
    server = QLocalServer()
    if not server.listen(key):
        # 监听失败说明另有实例占用了名字，不要继续起窗口
        return 0

    app.setStyle("Fusion")

    app.setApplicationVersion(meta.VERSION)
    QPixmapCache.setCacheLimit(300 * 1024)  # KB：网格缩略图 QPixmap 内存缓存上限
    qss = base_dir() / "src" / "ui" / "styles.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text("utf-8"))

    # 必须在 MainWindow 构造之前接上 newConnection：构造期间（加载 PySide6
    # 全模块/PIL/扫目录）可能收到激活请求，QLocalServer 会把它放进 pending 队列，
    # 而 newConnection 信号不会为「接信号之前」的连接补发。
    # 用延迟引用避免 _activate 早于 win 存在。
    win_holder: dict = {}

    def _activate() -> None:
        while server.hasPendingConnections():     # 把攒下的请求全部捞出来
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.waitForReadyRead(200)
                conn.disconnectFromServer()
        win = win_holder.get("win")
        if win is None:
            return
        win.showNormal()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(_activate)
    app._qx_single_server = server  # 保持引用
    app._qx_mutex = _mutex          # 保持互斥体句柄引用，进程存活期间不释放

    # 重型依赖（PySide6 全模块/PIL/numpy/oss2 链）延迟到闪屏之后
    from src.ui.main_window import MainWindow
    win = MainWindow()
    win_holder["win"] = win
    win.show()
    splash.finish(win)

    # 补一次 drain：启动期间到达的连接现在才有人处理
    if server.hasPendingConnections():
        QTimer.singleShot(0, _activate)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
