# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""滚轮输入归一化。

同一块触控板在图片墙和大图页的手感差 3 倍，原因是两处各写了一份换算：
图片墙把 pixelDelta 乘 3、再按 `dy / 120` 折算成行数；大图页直接拿
pixelDelta 与 angleDelta 混用，不乘系数。抽到这里统一成一个量纲。

约定：`wheel_steps()` 返回「滚轮格数」的浮点数。
一格 = 120（Qt 的 1/8 度单位）。正数向上/放大，负数向下/缩小。
"""
from __future__ import annotations

WHEEL_UNIT = 120.0   # Qt angleDelta 的一个标准格
PIXEL_RATIO = 3.0    # 高精度设备的像素量级与角度量级之间的经验折算


def wheel_steps(event) -> float:
    """把一次滚轮事件折算成格数。

    鼠标滚轮给 angleDelta（1/8 度）；触控板/高精度设备只有 pixelDelta，
    angleDelta 为 0。只读 angleDelta 会让触控板完全滚不动。
    """
    angle = event.angleDelta().y()
    if angle:
        return angle / WHEEL_UNIT
    return event.pixelDelta().y() * PIXEL_RATIO / WHEEL_UNIT
