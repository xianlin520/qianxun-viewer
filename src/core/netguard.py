"""出网闸门与本地审计日志。

默认处于「本地模式」：任何出网调用都在发出前被拦下，请求不离开本机，
只在本地的 `egress.log` 记一行。这层不依赖 UI，也不依赖调用方自觉——
所有出网点（短链服务端、对象存储、更新检查）都必须先过 `require()`。

放开本地模式后，每次出网仍会记一行，供事后自查：谁在什么时候连了哪个主机。
日志只记主机名，不记路径与查询串——路径里可能带图片名，正是要保护的东西。

拦截时抛 `OfflineError`，它的文案是给用户看的，可以直接显示。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

#: 出网作用域。新增出网点时在这里登记，便于日志与统计对齐。
SCOPES = ("update", "server", "oss")

SCOPE_LABEL = {
    "update": "更新检查",
    "server": "短链服务端",
    "oss": "对象存储",
}

LOG_NAME = "egress.log"
LOG_MAX_BYTES = 512 * 1024     # 超过就轮转一次，只留一份历史

_lock = threading.Lock()
_stats = {scope: {"allowed": 0, "blocked": 0} for scope in SCOPES}


class OfflineError(RuntimeError):
    """本地模式拦下的出网请求。文案可直接展示给用户。"""


def log_path() -> Path:
    from .oss_service import app_data_dir
    return app_data_dir() / LOG_NAME


def is_local_only() -> bool:
    """当前是否处于本地模式。

    读不到设置时按最保守处理（当作本地模式），
    宁可让功能用不了，也不让内容意外发出去。
    """
    try:
        from .settings import AppSettings
        return bool(AppSettings().local_only)
    except Exception:
        return True


def _host(url: str) -> str:
    """只取主机名。路径与查询串不进日志。"""
    if not url:
        return ""
    text = url if "://" in url else f"https://{url}"
    try:
        return urlsplit(text).hostname or ""
    except Exception:
        return ""


def _record(scope: str, target: str, blocked: bool) -> None:
    host = _host(target)
    line = json.dumps({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "host": host,
        "blocked": blocked,
    }, ensure_ascii=False)
    with _lock:
        _stats.setdefault(scope, {"allowed": 0, "blocked": 0})
        _stats[scope]["blocked" if blocked else "allowed"] += 1
        try:
            path = log_path()
            if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
                path.replace(path.with_suffix(".log.1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            # 日志写不了也绝不能影响主流程，更不能因为写日志失败而放行
            pass


def require(scope: str, target: str = "") -> None:
    """出网前调用一次。

    本地模式：记一行后抛 OfflineError，调用方不得吞掉后继续联网。
    联网模式：记一行放行。
    """
    if scope not in SCOPES:
        raise ValueError(f"未登记的出网作用域：{scope}")
    if is_local_only():
        _record(scope, target, blocked=True)
        raise OfflineError(
            f"本地模式已开启，已拦下「{SCOPE_LABEL.get(scope, scope)}」的请求。"
            "内容没有离开本机。需要联网时到「设置 → 隐私」关掉本地模式。")
    _record(scope, target, blocked=False)


def stats() -> dict:
    """各作用域的放行/拦截计数（进程内，供自查与用例断言）。"""
    with _lock:
        return json.loads(json.dumps(_stats))


def reset_stats() -> None:
    with _lock:
        for scope in _stats:
            _stats[scope] = {"allowed": 0, "blocked": 0}
