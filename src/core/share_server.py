# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""分享服务端客户端：Cloudflare Workers 短链 + 收藏同步。

设计要点：
- 鉴权用预共享密钥 + HMAC-SHA256，与服务端 server/src/auth.js 严格对应：
      canonical = METHOD \\n PATH \\n TIMESTAMP \\n NONCE \\n hex(SHA256(body))
      header X-QX-Signature = hex(HMAC-SHA256(secret, canonical))
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

UA = "qx-album/1.0 (+desktop client)"
TIMEOUT = 20


def _sign(secret: str, method: str, path: str, body: bytes, nonce: str) -> dict:
    ts = str(int(time.time() * 1000))
    body_hash = ""
    if method.upper() not in ("GET", "HEAD") and body:
        body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join([method.upper(), path, ts, nonce, body_hash])
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {"X-QX-Timestamp": ts, "X-QX-Signature": sig, "X-QX-Nonce": nonce}


class ShareServer:
    """服务端 API 封装。base 形如 https://img.agentstack.vip"""

    def __init__(self, base: str, secret: str):
        self.base = (base or "").rstrip("/")
        self.secret = secret or ""

    # ---------- 底层 ----------
    def configured(self) -> bool:
        return bool(self.base and self.secret)

    def _request(self, method: str, path: str, payload=None):
        """返回 (ok, data)。

        ok=False 时 data 是错误描述字符串。

        注意：签名只覆盖**路径**，不含 query。服务端用 `url.pathname` 参与
        签名计算（server/src/auth.js），若这里带 ?limit=... 就会 401。"""
        if not self.configured():
            return False, "未配置分享服务端"

        # 拆分 path 与 query：query 只用于实际请求，不进签名
        sign_path, _, query = path.partition("?")
        request_path = path

        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {"User-Agent": UA, "Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"
        headers.update(_sign(self.secret, method, sign_path, body,
                             secrets.token_hex(8)))

        req = urllib.request.Request(
            self.base + request_path, data=body or None, headers=headers,
            method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
    def health(self):
        try:
            req = urllib.request.Request(
                self.base + "/health", headers={"User-Agent": UA}, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, json.loads(resp.read())
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    # ---------- 短链 ----------
    def create_share(self, oss_key: str, note: str = ""):
        """创建短链，返回 (ok, url) 或 (False, 错误)"""
        ok, data = self._request(
            "POST", "/api/shares", {"oss_key": oss_key, "note": note})
        if not ok:
            return False, data
        if isinstance(data, dict) and data.get("url"):
            return True, data["url"]
        return False, "服务端返回格式异常"

    def list_shares(self, oss_key: str = "", limit: int = 200):
        q = f"?limit={int(limit)}"
        if oss_key:
            from urllib.parse import quote
            q += f"&oss_key={quote(oss_key, safe='')}"
        ok, data = self._request("GET", "/api/shares" + q)
        if not ok:
            return False, data
        return True, data.get("items", [])

    def revoke(self, token: str):
        ok, data = self._request("DELETE", f"/api/shares/{token}")
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

    def pull_favorites(self, since: int = 0):
        q = f"?since={int(since)}" if since else ""
        ok, data = self._request("GET", "/api/favorites" + q)
        if not ok:
            return False, data
        return True, data.get("items", [])
