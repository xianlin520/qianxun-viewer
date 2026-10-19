# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""目录扫描：递归收集图片，跳过 Remove 与隐藏缓存目录。纯 Python，无 Qt 依赖。

文件头读取（stat+分辨率）按目录批内 8 线程并行，网络盘/慢速介质显著提速；
瞬时 IO 失败退避重试，仍失败才计错误/标记损坏。
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

from PIL import Image

from .image_item import ImageItem

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_SKIP_DIRS = {"remove", ".qx_cache"}
_PARALLEL = 8


def _read_dimensions(path: Path, retries: int = 3) -> tuple[int, int]:
    """仅读头部获取分辨率；慢速介质瞬时失败时退避重试。"""
    for i in range(retries):
        try:
            with Image.open(path) as im:
                return im.size
        except Exception:
            if i < retries - 1:
                time.sleep(0.2 * (i + 1))
    return 0, 0


def _scan_one(path: Path) -> tuple[ImageItem | None, bool]:
    try:
        st = path.stat()
    except OSError:
        try:  # 网络盘瞬时失败重试一次
            time.sleep(0.2)
            st = path.stat()
        except OSError:
            return None, True
    w, h = _read_dimensions(path)
    return (ImageItem(path=path, size_bytes=st.st_size, mtime=st.st_mtime,
                      width=w, height=h, corrupted=(w == 0)), False)


def scan_batches(root: Path, batch_size: int = 64,
                 parallel: int = _PARALLEL) -> Iterator[tuple[list[ImageItem], int]]:
    """生成器：逐批产出 (items, 本批错误数)。

    注意 errors 是**本批**计数、每批产出后归零：ScanWorker 侧负责
    跨批累加（errors += errs）。若这里改成累计值，worker 再累加就会重复计数。
    （stat 失败才算错误；能 stat 但解不出分辨率的走 item.corrupted 标记。）"""
    batch: list[ImageItem] = []
    errors = 0
    with ThreadPoolExecutor(parallel) as ex:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d.lower() not in _SKIP_DIRS and not d.startswith("."))
            cands = [Path(dirpath) / n for n in sorted(filenames)
                     if Path(n).suffix.lower() in IMAGE_EXTS]
            if not cands:
                continue
            for item, err in ex.map(_scan_one, cands):
                if err or item is None:
                    errors += 1
                    continue
                batch.append(item)
                if len(batch) >= batch_size:
                    yield batch, errors
                    batch, errors = [], 0
    if batch or errors:
        yield batch, errors
