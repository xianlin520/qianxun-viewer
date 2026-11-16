# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""分享服务端客户端：Cloudflare Workers 短链 + 收藏同步。

设计要点：
- 鉴权用预共享密钥 + HMAC-SHA256，与服务端 server/src/auth.js 严格对应：
      canonical = METHOD \\n PATH?QUERY \\n TIMESTAMP \\n NONCE \\n hex(SHA256(body))
      header X-QX-Signature = hex(HMAC-SHA256(secret, canonical))
  query 现在也参与签名。此前只签 pathname，被截获的请求可以改 query 重放。
  服务端为旧客户端保留了只签 path 的兼容分支（ALLOW_LEGACY_SIG），新版一律签全量。
- 只用标准库（urllib + hmac + hashlib），不引入新依赖。
- **必须带 User-Agent**：Cloudflare 的 Bot Fight 会把 Python 默认 UA 拦成
  `error code: 1010`（实测）。
- 所有网络失败都返回 (False, 错误描述)，不抛异常到 UI 线程。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import quote

UA = "qx-album/1.0 (+desktop client)"
# 普通接口 10 秒；健康检查与单条撤销这类轻请求 5 秒。
# 之前统一 20 秒且都在 UI 线程跑，地址填错时窗口会假死半分钟。
TIMEOUT = 10
TIMEOUT_LIGHT = 5


def _sign(secret: str, method: str, target: str, body: bytes, nonce: str) -> dict:
    """生成签名头。

    与服务端 auth.js 严格对齐：
      - target 是「路径 + 查询串」，例如 /api/shares?limit=5
      - GET/HEAD 不参与 body hash（服务端直接跳过）
      - **其它方法（POST/DELETE/…）一律计算 hash，空 body 也要算**
        —— 服务端对空 body 调 arrayBuffer() 得到 0 字节，
        sha256("") = e3b0c442...，不是空串。这里曾漏算，
        导致所有 DELETE（撤销）请求 401。
    """
    ts = str(int(time.time() * 1000))
    m = method.upper()
    if m in ("GET", "HEAD"):
        body_hash = ""
    else:
        body_hash = hashlib.sha256(body or b"").hexdigest()
    canonical = "\n".join([m, target, ts, nonce, body_hash])
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {"X-QX-Timestamp": ts, "X-QX-Signature": sig, "X-QX-Nonce": nonce}


class ShareServer:
    """服务端 API 封装。base 形如 https://img.agentstack.vip"""

    def __init__(self, base: str, secret: str):
        self.base = (base or "").rstrip("/")
        self.secret = secret or ""

    def __repr__(self) -> str:  # 便于调试，不暴露密钥
        return f"<ShareServer base={self.base} secret={'set' if self.secret else 'EMPTY'}>"

    # ---------- 底层 ----------
    def configured(self) -> bool:
        return bool(self.base and self.secret)

    def _request(self, method: str, target: str, payload=None, timeout: float = TIMEOUT):
        """返回 (ok, data)。

        ok=False 时 data 是错误描述字符串。

        target 含查询串，例如 "/api/shares?limit=200"。签名覆盖完整 target，
        与请求实际发出的 URL 完全一致（服务端用 pathname + search 复算）。"""
        if not self.configured():
            return False, "未配置分享服务端"

        # 出网闸门：本地模式直接拦下，请求不出机器
        from . import netguard
        try:
            netguard.require("server", self.base)
        except netguard.OfflineError as exc:
            return False, str(exc)

        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {"User-Agent": UA, "Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"
        headers.update(_sign(self.secret, method, target, body,
                             secrets.token_hex(8)))

        req = urllib.request.Request(
            self.base + target, data=body or None, headers=headers,
            method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                try:
                    return True, json.loads(raw)
                except Exception:
                    return True, {"raw": raw[:500]}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                data = json.loads(raw)
                msg = data.get("message") or data.get("error") or str(data)
            except Exception:
                msg = raw[:200].decode("utf-8", "replace") or str(exc.code)
            return False, f"HTTP {exc.code}: {msg}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    # ---------- 健康检查 ----------
    def health(self, timeout: float = TIMEOUT_LIGHT):
        # 这里也要过闸门：/health 虽然是公开只读接口，但它同样是一个出网请求，
        # 「测试服务端连接」会直接走到这里。
        from . import netguard
        try:
            netguard.require("server", self.base)
        except netguard.OfflineError as exc:
            return False, str(exc)
        try:
            req = urllib.request.Request(
                self.base + "/health", headers={"User-Agent": UA}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, json.loads(resp.read())
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    # ---------- 短链 ----------
    def create_share(self, oss_key: str, note: str = "", expires_at: int | None = None):
        """创建短链，返回 (ok, url) 或 (False, 错误)

        expires_at 为毫秒时间戳，None 表示长期有效（与旧版一致）。"""
        payload = {"oss_key": oss_key, "note": note}
        if expires_at:
            payload["expires_at"] = int(expires_at)
        ok, data = self._request("POST", "/api/shares", payload)
        if not ok:
            return False, data
        if isinstance(data, dict) and data.get("url"):
            return True, data["url"]
        return False, "服务端返回格式异常"

    def list_shares(self, oss_key: str = "", limit: int = 200, before: int | None = None):
        """返回 (ok, (items, next_cursor))。"""

        parts = [f"limit={int(limit)}"]
        if oss_key:
            parts.append(f"oss_key={quote(oss_key, safe='')}")
        if before:
            parts.append(f"before={int(before)}")
        ok, data = self._request("GET", "/api/shares?" + "&".join(parts))
        if not ok:
            return False, data
        return True, (data.get("items", []), data.get("next_cursor"))

    def list_all_shares(self, oss_key: str = "", page: int = 200, max_pages: int = 50):
        """翻页取全量。用于「撤销全部」这类必须看全的场合。

        此前前端硬编码 limit=500，超过 500 条的记录根本列不出来，
        确认文案却写「全部」——用户以为撤干净了，实际没有。
        返回 (ok, items) 或 (ok=False, 错误描述)。"""
        out = []
        cursor = None
        for _ in range(max_pages):
            ok, res = self.list_shares(oss_key=oss_key, limit=page, before=cursor)
            if not ok:
                return False, res
            items, cursor = res
            out.extend(items)
            if not cursor or not items:
                break
        return True, out

    def revoke(self, token: str):
        ok, data = self._request("DELETE", f"/api/shares/{token}", timeout=TIMEOUT_LIGHT)
        return ok, (data if not ok else True)

    def revoke_by_key(self, oss_key: str):
        ok, data = self._request(
            "POST", "/api/shares/revoke-by-key", {"oss_key": oss_key})
        if not ok:
            return False, data
        return True, data.get("revoked", 0)

    # ---------- 收藏同步 ----------
    def push_favorites(self, items):
        """items: [{key, favorite, updated_at}]"""
        return self._request("POST", "/api/favorites", {"items": items})

    def pull_favorites(self, since: int = 0, after: int | None = None,
                       after_key: str | None = None):
        """拉一页收藏，返回 (ok, (items, next_cursor))。

        服务端单页上限 1000，超出的靠 next_cursor 翻页。此前这里把
        next_cursor 丢了，调用方又无参调用，于是第 1001 条起永远拉不到，
        客户端还认为同步已完成。
        """
        parts = []
        if since:
            parts.append(f"since={int(since)}")
        if after:
            parts.append(f"after={int(after)}")
        if after_key:
            # 游标必须带 key：updated_at 不唯一，只给时间会跳过同毫秒的边界记录
            parts.append("after_key=" + quote(str(after_key), safe=""))
        q = ("?" + "&".join(parts)) if parts else ""
        ok, data = self._request("GET", "/api/favorites" + q)
        if not ok:
            return False, data
        if not isinstance(data, dict):
            return False, "服务端返回格式异常"
        # 字段名以服务端 JSON 为准（snake_case）。此前这里读的是驼峰
        # nextCursor/nextKey，而路由返回 next_cursor/next_key，两边从未对上，
        # 游标恒为 None，于是「翻页到底」从来没发生过。
        return True, (data.get("items", []), data.get("next_cursor"),
                      data.get("next_key"))

    def pull_all_favorites(self, since: int = 0, max_pages: int = 100):
        """翻页拉全，返回 (ok, items)。用于「同步后覆盖本地」这类必须看全的场合。"""
        out: list = []
        cursor = key = None
        for _ in range(max_pages):
            ok, res = self.pull_favorites(since=since, after=cursor, after_key=key)
            if not ok:
                return False, res
            items, cursor, key = res
            out.extend(items)
            if not cursor or not items:
                return True, out
        return True, out
