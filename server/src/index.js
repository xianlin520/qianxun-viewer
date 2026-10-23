/**
 * 千寻影集服务端入口。
 *
 * 路由：
 *   GET    /s/<token>                公开：图片代理（内联展示）
 *   GET    /health                   公开：健康检查
 *   POST   /api/shares               创建短链
 *   GET    /api/shares               列出分享记录
 *   DELETE /api/shares/<token>       撤销单条
 *   POST   /api/shares/revoke-by-key 按图片批量撤销
 *   POST   /api/favorites            推送收藏（LWW）
 *   GET    /api/favorites            拉取收藏
 *
 * 鉴权：除 /s/* 与 /health 外，均需 X-QX-Timestamp + X-QX-Signature。
 */

import { verifyRequest } from "./auth.js";
import { handleShortLink } from "./proxy.js";
import {
  createShare,
  listShares,
  revokeShare,
  revokeByKey,
} from "./shares.js";
import { pushFavorites, pullFavorites } from "./favorites.js";

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

function err(status, code, message) {
  return json({ ok: false, error: code, message }, status);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method.toUpperCase();

    // ---- 公开路由 ----
    if (method === "GET" && path.startsWith("/s/")) {
      const token = path.slice(3).split("/")[0];
      return handleShortLink(request, env, token);
    }

    if (method === "GET" && path === "/health") {
      let dbOk = false;
      try {
        await env.DB.prepare("SELECT 1").first();
        dbOk = true;
      } catch (e) {
        console.error("db health failed", String(e));
      }
      // 诊断：只报「有没有」，绝不回显值
      return json({
        ok: dbOk,
        service: "qx-album-server",
        time: new Date().toISOString(),
        db: dbOk ? "up" : "down",
        env: {
          QX_SHARED_SECRET: env.QX_SHARED_SECRET ? "set" : "MISSING",
          OSS_AK_ID: env.OSS_AK_ID ? "set" : "MISSING",
          OSS_AK_SECRET: env.OSS_AK_SECRET ? "set" : "MISSING",
          DB: env.DB ? "bound" : "MISSING",
          PUBLIC_BASE: env.PUBLIC_BASE || "MISSING",
        },
      }, dbOk ? 200 : 503);
    }

    // ---- 以下全部需要鉴权 ----
    const auth = await verifyRequest(request, env);
    if (!auth.ok) {
      return err(auth.status === 500 ? 500 : 401, auth.error, "签名校验未通过");
    }

    // ---- /api/shares ----
    if (path === "/api/shares" && method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return err(400, "bad_json", "请求体不是合法 JSON");
      }
      const ossKey = (body.oss_key || "").trim();
      if (!ossKey) return err(400, "missing_oss_key", "缺少 oss_key");

      const r = await createShare(env, {
        ossKey,
        bucket: body.bucket || env.OSS_BUCKET,
        note: body.note,
      });
      return json({ ok: true, token: r.token, url: r.url }, 201);
    }

    if (path === "/api/shares" && method === "GET") {
      const rows = await listShares(env, {
        ossKey: url.searchParams.get("oss_key") || undefined,
        limit: url.searchParams.get("limit") || 200,
        includeRevoked: url.searchParams.get("include_revoked") !== "0",
      });
      return json({ ok: true, count: rows.length, items: rows });
    }

    if (path.startsWith("/api/shares/") && method === "DELETE") {
      const token = path.slice("/api/shares/".length).split("/")[0];
      if (!token) return err(400, "missing_token", "缺少 token");
      const changed = await revokeShare(env, token);
      if (!changed) {
        return json({ ok: false, error: "not_found_or_already_revoked" }, 404);
      }
      return json({ ok: true, token, revoked: true });
    }

    if (path === "/api/shares/revoke-by-key" && method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return err(400, "bad_json", "请求体不是合法 JSON");
      }
      const ossKey = (body.oss_key || "").trim();
      if (!ossKey) return err(400, "missing_oss_key", "缺少 oss_key");
      const n = await revokeByKey(env, ossKey);
      return json({ ok: true, oss_key: ossKey, revoked: n });
    }

    // ---- /api/favorites ----
    if (path === "/api/favorites" && method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return err(400, "bad_json", "请求体不是合法 JSON");
      }
      const items = Array.isArray(body.items) ? body.items : [];
      if (!items.length) return err(400, "empty_items", "items 不能为空");
      const r = await pushFavorites(env, items);
      return json({ ok: true, ...r });
    }

    if (path === "/api/favorites" && method === "GET") {
      const since = url.searchParams.get("since");
      const items = await pullFavorites(env, { since });
      return json({ ok: true, count: items.length, items });
    }

    return err(404, "not_found", `没有这个接口：${method} ${path}`);
  },
};
