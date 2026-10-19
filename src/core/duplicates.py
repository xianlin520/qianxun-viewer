# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""pHash 重复检测：汉明距离 ≤ 阈值 判为疑似重复。

采用"簇代表"聚类：新成员必须与簇的首张代表图相似才入组，
避免 Union-Find 传递性把 A≈B≈C≈… 的漂移链合并成几十张的大组。
"""
from __future__ import annotations

from . import phash as _phash

DEFAULT_THRESHOLD = 4


def find_groups(items, threshold: int = DEFAULT_THRESHOLD) -> list[list]:
    """items: 含 phash 的 ImageItem 列表；返回若干重复组（每组 >1 项）。"""
    hashed = [(it, _phash.hex_to_int(it.phash)) for it in items if it.phash]
    clusters: list[list] = []   # [代表hash, [成员...]]
    for it, h in hashed:
        for c in clusters:
            if bin(h ^ c[0]).count("1") <= threshold:
                c[1].append(it)
                break
        else:
            clusters.append([h, [it]])
    return [c[1] for c in clusters if len(c[1]) > 1]
