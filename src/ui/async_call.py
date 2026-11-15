# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""后台执行器：把阻塞调用（网络、慢磁盘）挪出 UI 线程。

这个模式原先只在分享记录对话框里实现过一次，于是更新检测、
「测试连接」这几处漏在外面，各自在 UI 线程同步跑网络请求，
地址填错时窗口会假死十几秒到一分钟。抽成公共件后，
新增的阻塞调用只有一种写法。

用法：
    self.async_ = AsyncCaller(self)
    self.async_.run(
        lambda: srv.health(),
        on_done=self._on_health,
        on_fail=self._on_health_fail,
    )

回调都在 UI 线程执行（Qt 跨线程信号默认排队投递）。
AsyncCaller 随宿主控件销毁，未完成的回调不会打到已删除的控件上。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    """执行一个无参可调用对象，结果通过信号回传。"""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.signals = _Signals()
        self.cancelled = threading.Event()

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:      # noqa: BLE001  —— 后台异常必须转成信号
            if not self.cancelled.is_set():
                try:
                    self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
                except RuntimeError:
                    pass              # 接收端已销毁（窗口关闭），静默
            return
        if self.cancelled.is_set():
            return
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass


class AsyncCaller(QObject):
    """持有一组后台任务。

    强引用保存在 self._jobs 里，直到任务结束才移除 ——
    QRunnable 被 GC 掉会连带信号对象消失，表现为「回调永远不来」。
    """

    def __init__(self, parent=None, max_threads: int | None = None):
        super().__init__(parent)
        self._jobs: set[_Job] = set()
        if max_threads:
            self._pool = QThreadPool(self)
            self._pool.setMaxThreadCount(max_threads)
        else:
            self._pool = QThreadPool.globalInstance()

    def run(self, fn, on_done=None, on_fail=None) -> None:
        job = _Job(fn)
        self._jobs.add(job)

        def _cleanup(*_):
            self._jobs.discard(job)

        if on_done is not None:
            job.signals.done.connect(on_done)
        if on_fail is not None:
            job.signals.failed.connect(on_fail)
        job.signals.done.connect(_cleanup)
        job.signals.failed.connect(_cleanup)

        self._pool.start(job)

    def cancel_all(self) -> None:
        """标记全部任务为已取消：结果会被丢弃，回调不再触发。"""
        for job in list(self._jobs):
            job.cancelled.set()
        self._jobs.clear()

    def busy(self) -> bool:
        return bool(self._jobs)
