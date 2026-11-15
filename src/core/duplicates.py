# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""pHash 重复检测：汉明距离 ≤ 阈值 判为疑似重复。

采用"簇代表"聚类：新成员必须与簇的首张代表图相似才入组，
避免 Union-Find 传递性把 A≈B≈C≈… 的漂移链合并成几十张的大组。

索引方式：64bit 指纹切成 4 段 16bit，只对「代表图」建倒排。
鸽巢原理保证：若总距离 ≤ t，则至少有一段的距离 ≤ t/4，
所以查候选时只需探每段 t//4 位以内的邻居，不必两两比较。
内容全不同的图库此前是 n(n-1)/2 次异或（2 万张约 2 亿次），现在接近线性。
"""
from __future__ import annotations

from functools import lru_cache

from . import phash as _phash

DEFAULT_THRESHOLD = 4
BANDS = 4
BAND_BITS = 16
BAND_MASK = (1 << BAND_BITS) - 1


def _band_values(h: int) -> tuple[int, int, int, int]:
    return (
        (h >> 48) & BAND_MASK,
        (h >> 32) & BAND_MASK,
        (h >> 16) & BAND_MASK,
        h & BAND_MASK,
    )


@lru_cache(maxsize=8192)
def _close_band_values(v: int, k: int) -> tuple[int, ...]:
    """与 v 的汉明距离 ≤ k 的全部 16bit 值。k 越大集合膨胀越快，见下方上限。"""
    out = [v]
    if k <= 0:
        return tuple(out)

    bits = [1 << i for i in range(BAND_BITS)]
    for b in bits:                                  # 距离 1
        out.append(v ^ b)
    if k >= 2:
        for i in range(BAND_BITS):                  # 距离 2
            for j in range(i + 1, BAND_BITS):
                out.append(v ^ bits[i] ^ bits[j])
    if k >= 3:
        for i in range(BAND_BITS):                  # 距离 3
            for j in range(i + 1, BAND_BITS):
                for m in range(j + 1, BAND_BITS):
                    out.append(v ^ bits[i] ^ bits[j] ^ bits[m])
    return tuple(out)


def find_groups(items, threshold: int = DEFAULT_THRESHOLD, is_cancelled=None) -> list[list]:
    """items: 含 phash 的 ImageItem 列表；返回若干重复组（每组 >1 项）。

    is_cancelled 可选，聚类过程中会被周期性检查；取消时返回空列表，
    由调用方按「已取消」处理（不要拿它当「没有重复」）。
    """
    threshold = max(0, int(threshold))
    hashed = [(it, _phash.hex_to_int(it.phash)) for it in items if it.phash]
    if not hashed:
        return []

    # 每段 k 位以内才算候选：4 段合计仍能覆盖总距离 ≤ k*4 的所有情况
    k = min(3, threshold // BANDS)

    reps: list[int] = []            # 每个簇的代表指纹
    members: list[list] = []        # 每个簇的成员
    index: list[dict[int, list[int]]] = [{} for _ in range(BANDS)]

    for n, (it, h) in enumerate(hashed):
        if is_cancelled is not None and (n & 0x3FF) == 0 and is_cancelled():
            return []

        bands = _band_values(h)
        candidates: set[int] = set()
        for bi in range(BANDS):
            bucket = index[bi]
            for v in _close_band_values(bands[bi], k):
                hit = bucket.get(v)
                if hit:
                    candidates.update(hit)

        # 按簇创建顺序取第一个匹配，保持与旧的线性扫描结果一致
        target = None
        for ci in sorted(candidates):
            if bin(h ^ reps[ci]).count("1") <= threshold:
                target = ci
                break

        if target is None:
            ci = len(reps)
            reps.append(h)
            members.append([it])
            for bi in range(BANDS):
                index[bi].setdefault(bands[bi], []).append(ci)
        else:
            members[target].append(it)

    return [m for m in members if len(m) > 1]
