# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""缩略图生成与磁盘缓存。

缓存目录为图片目录下隐藏的 .qx_cache/，按 256/512 两档存 JPEG；
缓存名 = sha1(绝对路径|大小|mtime)，文件变更后天然失效重建。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import phash as _phash

CACHE_DIR = ".qx_cache"
THUMB_SIZES = (256, 512)
MAX_DECODE_PIXELS = 120_000_000  # 原图解码像素上限，超限降采样防 OOM

Image.MAX_IMAGE_PIXELS = 200_000_000


def cache_key(item) -> str:
    raw = f"{item.path}|{item.size_bytes}|{item.mtime}"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()


def thumb_path(image_root: Path, item, size: int) -> Path:
    return image_root / CACHE_DIR / str(size) / f"{cache_key(item)}.jpg"


def has_cache(image_root: Path, item, size: int) -> bool:
    return thumb_path(image_root, item, size).exists()


def _phash_of(im: Image.Image) -> str:
    """在 32x32 灰度图上计算 64bit pHash。"""
    return _phash.phash_hex(im)


def phash_of_file(path: Path) -> str:
    try:
        with Image.open(path) as im:
            return _phash_of(im)
    except Exception:
        return ""


def generate(image_root: Path, item, size: int, with_phash: bool = False):
    """生成 size 档缩略图，返回 (缓存路径 | None, phash | '')。失败不抛异常。"""
    out = thumb_path(image_root, item, size)
    if out.exists():
        return out, (phash_of_file(out) if with_phash else "")
    for i in range(3):  # 慢速/网络介质退避重试，避免瞬时 IO 错误误判损坏
        try:
            with Image.open(item.path) as im:
                im = ImageOps.exif_transpose(im) or im
                im = im.convert("RGB")
                ph = _phash_of(im) if with_phash else ""
                im.thumbnail((size, size), Image.Resampling.LANCZOS)
                out.parent.mkdir(parents=True, exist_ok=True)
                im.save(out, "JPEG", quality=85)
            return out, ph
        except Exception:
            if i < 2:
                time.sleep(0.3 * (i + 1))
    return None, ""


def decode_original(path: Path) -> Image.Image | None:
    """解码原图；超像素上限时降采样解码。失败返回 None（含退避重试）。"""
    for i in range(3):
        try:
            with Image.open(path) as im:
                w, h = im.size
                if w * h > MAX_DECODE_PIXELS:
                    k = (w * h / MAX_DECODE_PIXELS) ** 0.5
                    try:
                        im.draft("RGB", (max(1, int(w / k)), max(1, int(h / k))))
                    except Exception:
                        pass
                im = ImageOps.exif_transpose(im) or im
                return im.convert("RGB")
        except Exception:
            if i < 2:
                time.sleep(0.3 * (i + 1))
    return None
