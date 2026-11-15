/**
 * 千寻影集服务端入口。
 *
 * 路由：
 *   GET    /s/<token>                公开：看图页（带后缀则代理图片字节）
 *   GET    /health                   公开：健康检查
 *   POST   /api/shares               创建短链
 *   GET    /api/shares               列出分享记录（游标翻页）
 *   DELETE /api/shares/<token>       撤销单条
 *   POST   /api/shares/revoke-by-key 按图片批量撤销
 *   POST   /api/favorites            推送收藏（LWW）
 *   GET    /api/favorites            拉取收藏（游标翻页）
 *
 * 鉴权：除 /s/* 与 /health 外，均需 X-QX-Timestamp + X-QX-Signature。
 *
 * 路由表驱动：新增接口只需在 ROUTES 里加一项，不用在三个地方各改一遍。
 */

import { verifyRequest } from "./auth.js";
import { handleShortLink } from "./proxy.js";
import { tooManyRequests, probe as rlProbe } from "./ratelimit.js";
import {
  createShare,
  listShares,
  revokeShare,
  revokeByKey,
  parseShortPath,
} from "./shares.js";
import { pushFavorites, pullFavorites, ValidationError } from "./favorites.js";

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
  });
}

function err(status, code, message) {
  return json({ ok: false, error: code, message }, status);
}

/** 统一读 JSON 体；解析失败直接给出 400 响应 */
async function readJson(request) {
  try {
    return { ok: true, body: await request.json() };
  } catch {
    return { ok: false, response: err(400, "bad_json", "请求体不是合法 JSON") };
  }
}

function requireOssKey(body) {
  const ossKey = String(body?.oss_key || "").trim();
  if (!ossKey) return { ok: false, response: err(400, "missing_oss_key", "缺少 oss_key") };
  return { ok: true, ossKey };
}

/** 条数上限夹取，避免 ?limit=999999 直接打到 D1 */
function clampLimit(raw, fallback, max) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.min(Math.trunc(n), max);
}

// ---- 各接口实现 ----

async function postShare(request, env) {
  const r = await readJson(request);
  if (!r.ok) return r.response;
  const k = requireOssKey(r.body);
  if (!k.ok) return k.response;

  const created = await createShare(env, {
    ossKey: k.ossKey,
    bucket: r.body.bucket || env.OSS_BUCKET,
    note: r.body.note,
    expiresAt: Number(r.body.expires_at),
  });
  return json(
    { ok: true, token: created.token, url: created.url, expires_at: created.expiresAt },
    201,
  );
}

async function getShares(request, env, url) {
  const r = await listShares(env, {
    ossKey: url.searchParams.get("oss_key") || undefined,
    limit: clampLimit(url.searchParams.get("limit"), 200, 200),
    includeRevoked: url.searchParams.get("include_revoked") !== "0",
    before: Number(url.searchParams.get("before")),
  });
  return json({
    ok: true,
    count: r.items.length,
    items: r.items,
    next_cursor: r.nextCursor,
  });
}

async function deleteShare(request, env, url) {
  const token = url.pathname.slice("/api/shares/".length).split("/")[0];
  if (!token) return err(400, "missing_token", "缺少 token");
  const changed = await revokeShare(env, token);
  if (!changed) {
    return json({ ok: false, error: "not_found_or_already_revoked" }, 404);
  }
  return json({ ok: true, token, revoked: true });
}

async function postRevokeByKey(request, env) {
  const r = await readJson(request);
  if (!r.ok) return r.response;
  const k = requireOssKey(r.body);
  if (!k.ok) return k.response;
  const n = await revokeByKey(env, k.ossKey);
  return json({ ok: true, oss_key: k.ossKey, revoked: n });
}

async function postFavorites(request, env) {
  const r = await readJson(request);
  if (!r.ok) return r.response;
  const items = Array.isArray(r.body?.items) ? r.body.items : [];
  if (!items.length) return err(400, "empty_items", "items 不能为空");

  try {
    const result = await pushFavorites(env, items);
    return json({ ok: true, ...result });
  } catch (e) {
    if (e instanceof ValidationError) {
      // 整批拒绝，不做部分写入：脏数据一旦落库，LWW 会让它永久胜出
      return err(400, "invalid_item", `第 ${e.index + 1} 条不合法：${e.message}`);
    }
    throw e;
  }
}

async function getFavorites(request, env, url) {
  const r = await pullFavorites(env, {
    since: url.searchParams.get("since"),
    after: url.searchParams.get("after"),
    afterKey: url.searchParams.get("after_key"),
    limit: clampLimit(url.searchParams.get("limit"), 1000, 1000),
  });
  return json({
    ok: true,
    count: r.items.length,
    items: r.items,
    // 两个游标必须成对出现：updated_at 不唯一，单给时间会漏掉同毫秒的边界记录。
    // 此前这里只序列化 next_cursor，而客户端读的是驼峰 nextCursor，
    // 两边字段名从未对上，游标恒为 null，翻页从来没真正发生过。
    next_cursor: r.nextCursor,
    next_key: r.nextKey,
  });
}

/** 路由表：exact 优先于 prefix，同 method 内按数组顺序匹配 */
const ROUTES = [
  { method: "POST", exact: "/api/shares", handler: postShare },
  { method: "GET", exact: "/api/shares", handler: getShares },
  { method: "POST", exact: "/api/shares/revoke-by-key", handler: postRevokeByKey },
  { method: "DELETE", prefix: "/api/shares/", handler: deleteShare },
  { method: "POST", exact: "/api/favorites", handler: postFavorites },
  { method: "GET", exact: "/api/favorites", handler: getFavorites },
];

function matchRoute(method, path) {
  let prefixHit = null;
  for (const r of ROUTES) {
    if (r.method !== method) continue;
    if (r.exact && r.exact === path) return r;
    if (r.prefix && !prefixHit && path.startsWith(r.prefix)) prefixHit = r;
  }
  return prefixHit;
}

function health(env, url) {
  return env.DB.prepare("SELECT 1")
    .first()
    .then(() => true)
    .catch((e) => {
      console.error("db health failed", String(e));
      return false;
    })
    .then((dbOk) =>
      json(
        {
          ok: dbOk,
          service: "qx-album-server",
          time: new Date().toISOString(),
          db: dbOk ? "up" : "down",
          // 诊断：只报「有没有」和生效值，绝不回显密钥本身
          env: {
            QX_SHARED_SECRET: env.QX_SHARED_SECRET ? "set" : "MISSING",
            OSS_AK_ID: env.OSS_AK_ID ? "set" : "MISSING",
            OSS_AK_SECRET: env.OSS_AK_SECRET ? "set" : "MISSING",
            DB: env.DB ? "bound" : "MISSING",
            PUBLIC_BASE: env.PUBLIC_BASE || "MISSING",
            AUTH_WINDOW: effectiveWindow(env),
            ALLOW_LEGACY_SIG: String(env.ALLOW_LEGACY_SIG ?? "0") === "1",
            RATE_LIMITER: (env.RATE_LIMITER && typeof env.RATE_LIMITER.limit === "function")
              ? "bound" : "MISSING",
          },
        },
        dbOk ? 200 : 503,
      ),
    );
}

/** 公开路由的每秒每 IP 上限。非法值退回默认 120，上限 6000（100 次/秒）。 */
function limitPerMin(env) {
  const raw = Number(env.RATE_LIMIT_PER_MIN);
  if (!Number.isFinite(raw) || raw <= 0) return undefined;
  return Math.min(Math.trunc(raw), 6000);
}

/** 与 auth.js 同一个口径：非法值退回 300，上限 3600 */
function effectiveWindow(env) {
  const raw = Number(env.AUTH_WINDOW);
  if (!Number.isFinite(raw) || raw <= 0) return 300;
  return Math.min(raw, 3600);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method.toUpperCase();

    // ---- 公开路由 ----
    // /s/<token> 与 /s/<token>.<ext> 都走同一入口，后缀由 parseShortPath 判定
    if (method === "GET" && path.startsWith("/s/")) {
      if (await tooManyRequests(request, env, "s", limitPerMin(env))) {
        return err(429, "rate_limited", "请求过于频繁，请稍后再试。");
      }
      const { token } = parseShortPath(path);
      return handleShortLink(request, env, token, ctx);
    }

    // 诊断：?rl=1 返回限流两层的当前读数，便于线上核对是否真的在拦
    if (method === "GET" && path === "/health" && url.searchParams.get("rl") === "1") {
      return json(await rlProbe(env, request));
    }

    if (method === "GET" && path === "/health") {
      if (await tooManyRequests(request, env, "h", limitPerMin(env))) {
        return err(429, "rate_limited", "请求过于频繁，请稍后再试。");
      }
      return health(env, url);
    }

    // ---- 以下全部需要鉴权 ----
    const auth = await verifyRequest(request, env);
    if (!auth.ok) {
      return err(auth.status === 500 ? 500 : 401, auth.error, "签名校验未通过");
    }

    const route = matchRoute(method, path);
    if (!route) {
      return err(404, "not_found", `没有这个接口：${method} ${path}`);
    }
    return route.handler(request, env, url);
  },
};
