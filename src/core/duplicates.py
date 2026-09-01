# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""pHash 重复检测：汉明距离 ≤ 6 判为疑似重复，Union-Find 分组。"""
from __future__ import annotations

from . import phash as _phash

DIST_THRESHOLD = 6


def find_groups(items) -> list[list]:
    """items: 含 phash 的 ImageItem 列表；返回若干重复组（每组 >1 项）。"""
    hashed = [(it, _phash.hex_to_int(it.phash)) for it in items if it.phash]
    n = len(hashed)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        hi = hashed[i][1]
        for j in range(i + 1, n):
            if bin(hi ^ hashed[j][1]).count("1") <= DIST_THRESHOLD:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra

    buckets: dict[int, list] = {}
    for idx in range(n):
        buckets.setdefault(find(idx), []).append(hashed[idx][0])
    return [g for g in buckets.values() if len(g) > 1]
