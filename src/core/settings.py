# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""程序级设置封装：QSettings（INI 格式，存用户目录）。"""
from __future__ import annotations

from PySide6.QtCore import QSettings

from ..utils import secret

ORG_NAME = "QianXun"
APP_NAME = "QianXunViewer"


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            ORG_NAME, APP_NAME)
        self._migrate_secret()

    def _get(self, key: str, default: str = "") -> str:
        v = self._s.value(key)
        return default if v is None else str(v)

    def _get_int(self, key: str, default: int) -> int:
        try:
            return int(self._get(key, str(default)))
        except ValueError:
            return default

    @property
    def default_open_dir(self) -> str:
        return self._get("default_open_dir")

    @default_open_dir.setter
    def default_open_dir(self, v: str) -> None:
        self._s.setValue("default_open_dir", v)

    @property
    def default_save_dir(self) -> str:
        return self._get("default_save_dir")

    @default_save_dir.setter
    def default_save_dir(self, v: str) -> None:
        self._s.setValue("default_save_dir", v)

    @property
    def view_mode(self) -> str:
        return self._get("view_mode", "scroll")

    @view_mode.setter
    def view_mode(self, v: str) -> None:
        self._s.setValue("view_mode", v)

    @property
    def sort_mode(self) -> str:
        return self._get("sort_mode", "random")

    @sort_mode.setter
    def sort_mode(self, v: str) -> None:
        self._s.setValue("sort_mode", v)

    @property
    def thumb_size(self) -> int:
        return self._get_int("thumb_size", 180)

    @thumb_size.setter
    def thumb_size(self, v: int) -> None:
        self._s.setValue("thumb_size", int(v))

    @property
    def last_dir(self) -> str:
        return self._get("last_dir")

    @last_dir.setter
    def last_dir(self, v: str) -> None:
        self._s.setValue("last_dir", v)

    @property
    def last_page(self) -> int:
        return self._get_int("last_page", 0)

    @last_page.setter
    def last_page(self, v: int) -> None:
        self._s.setValue("last_page", int(v))

    @property
    def last_scroll(self) -> int:
        return self._get_int("last_scroll", 0)

    @last_scroll.setter
    def last_scroll(self, v: int) -> None:
        self._s.setValue("last_scroll", int(v))

    @property
    def dup_threshold(self) -> int:
        return self._get_int("dup_threshold", 4)

    @dup_threshold.setter
    def dup_threshold(self, v: int) -> None:
        self._s.setValue("dup_threshold", int(v))

    @property
    def window_geo(self):
        return self._s.value("window_geo")

    @window_geo.setter
    def window_geo(self, v) -> None:
        self._s.setValue("window_geo", v)

    def sync(self) -> None:
        self._s.sync()

    def _migrate_secret(self) -> None:
        """历史版本 SK 为明文：启动时一次性改写为 DPAPI 密文。"""
        raw = self._s.value("oss_ak_secret")
        if raw and not str(raw).startswith(secret.PREFIX):
            self._s.setValue("oss_ak_secret", secret.protect(str(raw)))
            self._s.sync()

    # ---- OSS 在线配置（仅存本机用户目录） ----
    @property
    def oss_endpoint(self) -> str:
        return self._get("oss_endpoint")

    @oss_endpoint.setter
    def oss_endpoint(self, v: str) -> None:
        self._s.setValue("oss_endpoint", v)

    @property
    def oss_bucket(self) -> str:
        return self._get("oss_bucket")

    @oss_bucket.setter
    def oss_bucket(self, v: str) -> None:
        self._s.setValue("oss_bucket", v)

    @property
    def oss_ak_id(self) -> str:
        return self._get("oss_ak_id")

    @oss_ak_id.setter
    def oss_ak_id(self, v: str) -> None:
        self._s.setValue("oss_ak_id", v)

    @property
    def oss_ak_secret(self) -> str:
        return secret.unprotect(self._get("oss_ak_secret"))

    @oss_ak_secret.setter
    def oss_ak_secret(self, v: str) -> None:
        self._s.setValue("oss_ak_secret", secret.protect(v))

    # ---- 行为设置 ----
    @property
    def upload_threads(self) -> int:
        return max(1, min(8, self._get_int("upload_threads", 4)))

    @upload_threads.setter
    def upload_threads(self, v: int) -> None:
        self._s.setValue("upload_threads", int(v))

    @property
    def upload_skip_dups(self) -> bool:
        return str(self._get("upload_skip_dups", "1")) not in ("0", "false")

    @upload_skip_dups.setter
    def upload_skip_dups(self, v: bool) -> None:
        self._s.setValue("upload_skip_dups", "1" if v else "0")

    @property
    def share_days(self) -> int:
        return max(1, min(7, self._get_int("share_days", 7)))

    @share_days.setter
    def share_days(self, v: int) -> None:
        self._s.setValue("share_days", int(v))

    @property
    def scan_parallel(self) -> int:
        return max(1, min(16, self._get_int("scan_parallel", 8)))

    @scan_parallel.setter
    def scan_parallel(self, v: int) -> None:
        self._s.setValue("scan_parallel", int(v))

    @property
    def auto_load_last(self) -> bool:
        return str(self._get("auto_load_last", "1")) not in ("0", "false")

    @auto_load_last.setter
    def auto_load_last(self, v: bool) -> None:
        self._s.setValue("auto_load_last", "1" if v else "0")
