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
from itertools import combinations

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


@lru_cache(maxsize=4)
def _flip_masks(k: int) -> tuple[int, ...]:
    """把「汉明距离 ≤ k 的邻居」表示成 64bit 内的异或掩码序列。

    掩码只与 k 有关，与数据无关，所以整个进程里最多 4 份（k=0..3），
    合计 1+16+120+560 个整数。缓存的必须是掩码而不是邻居集合本身：
    后者随指纹变化，k=3 时单条 697 个值，8192 条实测涨到 218MB。
    """
    out = [0]
    for d in range(1, k + 1):
        for combo in combinations(range(BAND_BITS), d):
            m = 0
            for i in combo:
                m |= 1 << i
            out.append(m)
    return tuple(out)


def _close_band_values(v: int, k: int):
    """依次产出与 v 的汉明距离 ≤ k 的全部 16bit 值。"""
    for m in _flip_masks(k):
        yield v ^ m


def find_groups(items, threshold: int = DEFAULT_THRESHOLD, is_cancelled=None) -> list[list]:
    """items: 含 phash 的 ImageItem 列表；返回若干重复组（每组 >1 项）。

    is_cancelled 可选，聚类过程中会被周期性检查；取消时返回空列表，
    由调用方按「已取消」处理（不要拿它当「没有重复」）。
    """
    threshold = max(0, int(threshold))
    hashed = [(it, _phash.hex_to_int(it.phash)) for it in items if it.phash]
    if not hashed:
        return []

    # 鸽巢原理：总距离 ≤ t 时必有一段距离 ≤ t/4，所以每段只需探 k = t//4 位以内。
    # k 一旦被截断（t > 12），该保证就失效，会漏组。设置界面上限是 12，
    # 超过的只可能来自手改配置文件，这里夹回 12 而不是静默漏检。
    k = threshold // BANDS
    if k > 3:
        k = 3
        threshold = BANDS * k

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
