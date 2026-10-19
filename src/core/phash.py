# 千寻影集 QianXun Album
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
    """正交 DCT-II 基矩阵（行 = 频率 k，列 = 空间位置 x）。

    注意 k 必须在行、x 必须在列：若写成 `(2*x+1)` 在行、`k` 在列，
    得到的是正确基的**转置** Cᵀ，而下面的归一化仍按行作用，
    结果 M·Mᵀ 的对角是 0.5156/1.0313/…（非正交）—— 会让纯色图、
    浅色截图、扫描页全部塌缩成同一个哈希（实测 aa55aa55aa55aa55），
    进而被判为重复，在线模式下会误删云端图片。"""
    k = np.arange(n)[:, None]      # 频率，行
    x = np.arange(n)[None, :]      # 空间位置，列
    m = np.cos((2 * x + 1) * k * np.pi / (2 * n))
    m[0, :] *= np.sqrt(1.0 / n)
    m[1:, :] *= np.sqrt(2.0 / n)
    return m


_M = _dct_matrix(_N)


def phash_hex(image: Image.Image) -> str:
    """对 PIL 图像计算 64bit pHash，返回 16 位 hex 字符串。"""
    gray = image.convert("L").resize((_N, _N), Image.Resampling.LANCZOS)
    px = np.asarray(gray, dtype=np.float64)
    dct = _M @ px @ _M.T
    low = dct[:_HASH_SIZE, :_HASH_SIZE].copy()
    # DC 分量（low[0,0]）恒为最大低频项，若参与取中值会让首位恒为 1；
    # 剔除后再取中值，其余 63 位才是真正的纹理信息。
    dc = low[0, 0]
    low[0, 0] = np.median(low[1:, :])
    bits = (low > np.median(low)).flatten()
    n = 0
    for b in bits:
        n = (n << 1) | int(b)
    low[0, 0] = dc
    return format(n, "016x")


def hex_to_int(h: str) -> int:
    return int(h, 16)


def hamming(a: str, b: str) -> int:
    """两个 pHash hex 的汉明距离。"""
    return bin(hex_to_int(a) ^ hex_to_int(b)).count("1")
