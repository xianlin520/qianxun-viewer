# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""核心数据模型 ImageItem。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImageItem:
    path: Path
    size_bytes: int
    mtime: float
    width: int = 0         # 扫描时经 Pillow 快速读取头部获得
    height: int = 0
    phash: str = ""       # 查重用（64bit hex）
    favorite: bool = False
    dup_group: int = -1   # 重复组编号
    corrupted: bool = False
    remote_key: str = ""  # 在线项的 OSS object key（非空=在线项）
