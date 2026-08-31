# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""程序级设置封装：QSettings（INI 格式，存用户目录）。"""
from __future__ import annotations

from PySide6.QtCore import QSettings

ORG_NAME = "QianXun"
APP_NAME = "QianXunViewer"


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                            ORG_NAME, APP_NAME)

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

    def sync(self) -> None:
        self._s.sync()

    @property
    def window_geo(self):
        return self._s.value("window_geo")

    @window_geo.setter
    def window_geo(self, v) -> None:
        self._s.setValue("window_geo", v)
