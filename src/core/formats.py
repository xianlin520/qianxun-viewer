# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""支持的图片扩展名。

此前 scanner 与 oss_service 各写一份：新增一种格式只改一处，
会出现「本地上传得了、在线库看不到」这种不报错的错位。
"""
from __future__ import annotations

IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
})
