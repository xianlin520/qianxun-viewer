# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""自实现 pHash（numpy 32×32 灰度 + 二维 DCT），替代 imagehash 以精简依赖与包体。

输出与比较均自洽：64bit（8×8 低频 DCT 与中值比较）→ 16 位 hex 字符串。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

_N = 32          # DCT 域尺寸
_HASH_SIZE = 8   # 低频取 8×8 = 64bit


def _dct_matrix(n: int) -> np.ndarray:
    m = np.cos((2 * np.arange(n)[:, None] + 1) * np.arange(n)[None, :]
               * np.pi / (2 * n))
    m[0, :] *= np.sqrt(1.0 / n)
    m[1:, :] *= np.sqrt(2.0 / n)
    return m


_M = _dct_matrix(_N)


def phash_hex(image: Image.Image) -> str:
    """对 PIL 图像计算 64bit pHash，返回 16 位 hex 字符串。"""
    gray = image.convert("L").resize((_N, _N), Image.Resampling.LANCZOS)
    px = np.asarray(gray, dtype=np.float64)
    dct = _M @ px @ _M.T
    low = dct[:_HASH_SIZE, :_HASH_SIZE]
    bits = (low > np.median(low)).flatten()
    n = 0
    for b in bits:
        n = (n << 1) | int(b)
    return format(n, "016x")


def hex_to_int(h: str) -> int:
    return int(h, 16)


def hamming(a: str, b: str) -> int:
    """两个 pHash hex 的汉明距离。"""
    return bin(hex_to_int(a) ^ hex_to_int(b)).count("1")
