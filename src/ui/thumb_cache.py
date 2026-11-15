# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""缩略图缓存门面：三个视图共用同一套键规则。

此前 tier 判定写在 controllers / grid_view / wall_view 三处，
缓存键拼接又各写一套（图片墙用 `|c`、网格用 `|k`，两个后缀没有任何文档）。
加一档 1024 或调整键格式要同步改三个文件六处，漏一处不报错，
只静默掉命中率，表现出来就是「滚动变涩」。

现在视图只调这里，不再直接碰 QPixmapCache 与 thumb_path。
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QPixmapCache

from ..core import thumbnail

# 档位直接由 thumbnail.THUMB_SIZES 派生，不另写一份数字：
# 加一档 1024 时只改 thumbnail 一处，这里的判定与取图顺序自动跟上。
TIER_ORDER = tuple(sorted(thumbnail.THUMB_SIZES, reverse=True))   # 优先取大档
TIER_LARGE = TIER_ORDER[0]
TIER_SMALL = TIER_ORDER[-1]


class ScaleMode(Enum):
    """缩放语义。取代原来裸写的 'c' / 'k' 两个后缀。"""

    FIT = "fit"        # 完整显示，可能留边（网格卡片）
    COVER = "cover"    # 填满并裁切（图片墙无缝拼接）


def tier_for(px: int) -> int:
    """按目标显示像素选档位：取第一个不小于 px 的档，都不够就用最大档。"""
    for tier in sorted(thumbnail.THUMB_SIZES):
        if px <= tier:
            return tier
    return TIER_LARGE


def _pixmap_key(item, tier: int) -> str:
    # 键里带 cache_key（含 size/mtime）：外部改了同名图片后自动失效，
    # 否则 F5 重建了磁盘缩略图、界面仍命中旧 pixmap
    return f"{thumbnail.cache_key(item)}|{tier}"


class ThumbCache:
    """只读缓存访问器。缺缓存时返回 None，由调用方显示占位。"""

    def pixmap(self, image_root, item, tier: int):
        """取该档位的原始缩略图（不生成、不缩放）。"""
        key = _pixmap_key(item, tier)
        pix = QPixmapCache.find(key)
        if pix is not None and not pix.isNull():
            return pix
        if image_root is None:
            return None
        fp = thumbnail.thumb_path(image_root, item, tier)
        if not fp.exists():
            return None
        pix = QPixmap(str(fp))
        if pix.isNull():
            return None
        QPixmapCache.insert(key, pix)
        return pix

    def scaled(self, image_root, item, tier: int, width: int, height: int,
               mode: ScaleMode = ScaleMode.FIT):
        """取按目标尺寸缩放后的图，结果按「键+尺寸+模式」缓存。"""
        if width <= 0 or height <= 0:
            return None
        key = f"{_pixmap_key(item, tier)}|{width}x{height}|{mode.value}"
        cached = QPixmapCache.find(key)
        if cached is not None and not cached.isNull():
            return cached

        pix = self.pixmap(image_root, item, tier)
        if pix is None:
            return None
        ar = (Qt.AspectRatioMode.KeepAspectRatio
              if mode is ScaleMode.FIT
              else Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        out = pix.scaled(QSize(width, height), ar,
                         Qt.TransformationMode.SmoothTransformation)
        if out.isNull():
            return None
        QPixmapCache.insert(key, out)
        return out

    def best(self, image_root, item):
        """任意档位已有的缓存（优先大档）。用于预览这类不定档位的场合。

        绝不在这里生成 —— 同步生成会让打开查重面板卡住：
        一个 40 张的组实测 649ms 全卡在 UI 线程。
        """
        for tier in TIER_ORDER:
            pix = self.pixmap(image_root, item, tier)
            if pix is not None:
                return pix
        return None


# 全局单例：缓存本身是进程级的 QPixmapCache，无状态
THUMBS = ThumbCache()
