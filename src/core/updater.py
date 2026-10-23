# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""新版本检测：查 Gitee Releases，与本地 VERSION 比较。

设计要点：
- 只用标准库（urllib），不引入新依赖。
- **必须带 User-Agent**：Cloudflare/Gitee 都可能拦默认 Python UA（实测 CF 返回 1010）。
- 版本比较用「分段转 int」，避免字符串比较把 1.10.0 判成小于 1.9.0。
- 预发布（prerelease=True 或 tag 含 -beta/-rc）直接跳过，不提示用户升级。
- 所有异常都吞掉并返回错误描述：检测失败绝不能影响主功能。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import meta

REPO = "qianxun-cloud/qianxun-viewer"
API_LATEST = f"https://gitee.com/api/v5/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://gitee.com/{REPO}/releases/tag/"
UA = "qx-album-updater/1.0 (+desktop client)"
TIMEOUT = 12
_PRE_RE = re.compile(r"-(alpha|beta|rc|pre|dev)", re.I)


@dataclass
class ReleaseInfo:
    version: str          # 规范化后的 "1.6.0"
    tag: str              # 原始 tag "v1.6.0"
    name: str
    notes: str
    page_url: str
    assets: list[dict]

    def is_newer_than(self, current: str) -> bool:
        return parse_version(self.version) > parse_version(current)


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.6.0' → (1, 6, 0)。非数字段按 0 处理。

    不用字符串比较：'1.10.0' < '1.9.0' 会是 True，导致漏提示。"""
    s = (text or "").strip().lstrip("vV")
    parts = []
    for seg in s.split("."):
        m = re.match(r"^\d+", seg)
        parts.append(int(m.group()) if m else 0)
    # 补齐到 3 段，避免 (1,6) 与 (1,6,0) 比较时长度不同导致判断反直觉
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_latest() -> tuple[ReleaseInfo | None, str]:
    """查询最新版本。返回 (info, "") 或 (None, 错误描述)。"""
    req = urllib.request.Request(API_LATEST, headers={"User-Agent": UA,
                                                      "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None, "接口未返回 tag_name"

    # 预发布跳过：不主动提示用户换到测试版
    if data.get("prerelease") or _PRE_RE.search(tag):
        return None, "最新发布为预发布版本，已跳过"

    assets = [
        {"name": a.get("name", ""), "url": a.get("browser_download_url", "")}
        for a in (data.get("assets") or [])
    ]
    info = ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=str(data.get("name") or tag),
        notes=str(data.get("body") or ""),
        page_url=RELEASE_PAGE + tag,
        assets=assets,
    )
    return info, ""


def has_update(current: str | None = None) -> tuple[ReleaseInfo | None, str]:
    """便捷封装：有更新返回 (info, "")，否则 (None, 原因)。"""
    cur = current or meta.VERSION
    info, err = check_latest()
    if info is None:
        return None, err
    if info.is_newer_than(cur):
        return info, ""
    return None, "已是最新版本"
