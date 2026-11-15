# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""程序级设置封装：QSettings（INI 格式，存用户目录）。

每个设置项由一个 `_Field` 描述符声明，键名直接取字段名，只写一次。
此前是 24 组逐字重复的 `@property`/`@x.setter`，键名在读写两侧各写一遍：
改名漏改一侧不会报错，只会「读旧键、写新键」，静默不一致。
其中两个键还是 DPAPI 加密存储的，错了要重新填凭据才能发现。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

from ..utils import secret

ORG_NAME = "QianXun"
APP_NAME = "QianXunViewer"

_FALSE = ("0", "false", "False", "")


class _Field:
    """一个设置项：读时按类型还原并夹取范围，写时按类型落库。

    kind:
        "str"  字符串，缺失时为空串
        "int"  整数，按 lo/hi 夹取
        "bool" 落库为 "1"/"0"
        "raw"  原样存取（QByteArray 之类，不做 str 转换）
    """

    def __init__(self, default="", *, kind="str", lo=None, hi=None,
                 protect=False, normalize=None):
        self.default = default
        self.kind = kind
        self.lo = lo
        self.hi = hi
        self.protect = protect
        self.normalize = normalize
        self.name = ""

    def __set_name__(self, owner, name):
        # 键名 = 字段名。这是整个文件里唯一一处「键叫什么」的定义。
        self.name = name

    # ---- 读 ----
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        raw = obj._s.value(self.name)
        if self.kind == "raw":
            return raw

        if self.protect:
            return secret.unprotect("" if raw is None else str(raw))

        text = str(self.default) if raw is None else str(raw)

        if self.kind == "bool":
            return text.strip() not in _FALSE

        if self.kind == "int":
            try:
                n = int(text)
            except (TypeError, ValueError):
                n = int(self.default)
            if self.lo is not None:
                n = max(self.lo, n)
            if self.hi is not None:
                n = min(self.hi, n)
            return n

        return text

    # ---- 写 ----
    def __set__(self, obj, value):
        if self.normalize is not None:
            value = self.normalize(value)
        if self.kind == "raw":
            obj._s.setValue(self.name, value)
            return
        if self.protect:
            obj._s.setValue(self.name, secret.protect(value or ""))
            return
        if self.kind == "bool":
            obj._s.setValue(self.name, "1" if value else "0")
            return
        if self.kind == "int":
            obj._s.setValue(self.name, int(value))
            return
        obj._s.setValue(self.name, "" if value is None else str(value))


def _strip_slash(v) -> str:
    return (v or "").strip().rstrip("/")


def _strip(v) -> str:
    return (v or "").strip()


class AppSettings:
    # ---- 目录与视图 ----
    default_open_dir = _Field("")
    default_save_dir = _Field("")
    view_mode = _Field("scroll")
    sort_mode = _Field("random")
    thumb_size = _Field(180, kind="int")
    last_dir = _Field("")
    last_page = _Field(0, kind="int")
    last_scroll = _Field(0, kind="int")
    dup_threshold = _Field(4, kind="int")
    window_geo = _Field(None, kind="raw")

    # ---- OSS 在线配置（仅存本机用户目录） ----
    oss_endpoint = _Field("")
    oss_bucket = _Field("")
    oss_ak_id = _Field("")
    oss_ak_secret = _Field("", protect=True)          # DPAPI 加密

    # ---- 行为设置 ----
    upload_threads = _Field(4, kind="int", lo=1, hi=8)
    upload_skip_dups = _Field(True, kind="bool")
    share_days = _Field(7, kind="int", lo=1, hi=7)
    scan_parallel = _Field(8, kind="int", lo=1, hi=16)
    auto_load_last = _Field(True, kind="bool")

    # ---- 分享服务端（Cloudflare Workers 短链） ----
    server_base = _Field("", normalize=_strip_slash)
    server_secret = _Field("", protect=True)          # DPAPI 加密
    server_enabled = _Field(False, kind="bool")

    # ---- 更新检测 ----
    skipped_version = _Field("", normalize=_strip)
    check_updates = _Field(True, kind="bool")

    def __init__(self) -> None:
        self._s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            ORG_NAME, APP_NAME)
        self._migrate_secret()

    @classmethod
    def fields(cls) -> dict[str, _Field]:
        """全部设置项：供一致性用例与文档生成使用。"""
        out = {}
        for klass in reversed(cls.__mro__):
            for name, val in vars(klass).items():
                if isinstance(val, _Field):
                    out[name] = val
        return out

    def sync(self) -> None:
        self._s.sync()

    def _migrate_secret(self) -> None:
        """历史版本 SK 为明文：启动时一次性改写为 DPAPI 密文。"""
        raw = self._s.value("oss_ak_secret")
        if raw and not str(raw).startswith(secret.PREFIX):
            self._s.setValue("oss_ak_secret", secret.protect(str(raw)))
            self._s.sync()
