# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""目录扫描：递归收集图片，跳过 Remove 与隐藏缓存目录。纯 Python，无 Qt 依赖。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from PIL import Image

from .image_item import ImageItem

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_SKIP_DIRS = {"remove", ".qx_cache"}


def _read_dimensions(path: Path) -> tuple[int, int]:
    """仅读头部获取分辨率，不解码像素。"""
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return 0, 0


def scan_batches(root: Path, batch_size: int = 64) -> Iterator[tuple[list[ImageItem], int]]:
    """生成器：逐批产出 (items, 本批累计错误数)。单文件损坏/无权限只计数不中断。"""
    batch: list[ImageItem] = []
    errors = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                st = path.stat()
            except OSError:
                errors += 1
                continue
            w, h = _read_dimensions(path)
            batch.append(
                ImageItem(path=path, size_bytes=st.st_size, mtime=st.st_mtime,
                          width=w, height=h, corrupted=(w == 0))
            )
            if len(batch) >= batch_size:
                yield batch, errors
                batch, errors = [], 0
    if batch or errors:
        yield batch, errors
