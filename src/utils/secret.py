# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""Windows DPAPI 机密加解密（绑定当前 Windows 账户，无第三方依赖）。

密文带 "ENC1:" 前缀以便与历史明文值区分；非 Windows 或 API 不可用时
退化为明文（本程序目标平台为 Windows）。"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

PREFIX = "ENC1:"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes | None:
    if not hasattr(ctypes, "windll"):
        return None
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    inp = _DATA_BLOB(len(data), buf)
    out = _DATA_BLOB()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0,
              ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(plain: str) -> str:
    """加密为 ENC1:base64 串；失败时原样返回（调用方仍可正常使用）。"""
    if not plain or plain.startswith(PREFIX):
        return plain
    b = _dpapi(plain.encode("utf-8"), True)
    return PREFIX + base64.b64encode(b).decode() if b is not None else plain


def unprotect(token: str) -> str:
    """解密 ENC1: 串；历史明文原样返回；解密失败返回空串。"""
    if not token:
        return ""
    if not token.startswith(PREFIX):
        return token
    try:
        b = _dpapi(base64.b64decode(token[len(PREFIX):]), False)
    except Exception:
        return ""
    return b.decode("utf-8") if b is not None else ""
