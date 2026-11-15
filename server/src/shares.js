/**
 * 短链相关：创建 / 列出 / 撤销 / 解析。
 *
 * token 用 7 位 base62（62^7 ≈ 3.5 万亿），足够抗猜；
 * 冲突时重试 5 次（实际冲突概率极低）。
 *
 * 过期：expires_at 为空表示长期有效（默认），有值则到点即失效。
 * 客户端不传时行为与旧版一致，不影响既有短链。
 */

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

export const MAX_LIMIT = 200;

/** 访问计数的写入间隔（毫秒）：同一 token 最多一分钟记一次 */
export const HIT_INTERVAL_MS = 60_000;

export function makeToken(len = 7) {
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  let s = "";
  for (let i = 0; i < len; i++) s += ALPHABET[bytes[i] % ALPHABET.length];
  return s;
}

/**
 * 解析短链路径，index.js 与 proxy.js 共用同一套规则。
 *
 * 此前两处各写一份且不等价：路由层用 lastIndexOf(".") 切分，
 * 代理层用 /\.[0-9A-Za-z]{2,5}$/ 匹配。遇到 `a.b` 这种输入，
 * 路由层认为是「token=a、后缀=b」，代理层认为是「整段就是 token」，
 * 于是同一请求在两层得到不同结论。
 *
 * 规则：最后一个点之后是 1~8 位字母数字才算后缀，否则整段都是 token。
 *
 * @returns {{ token: string, ext: string|null, wantRaw: boolean }}
 */
export function parseShortPath(pathname) {
  const seg = String(pathname || "").replace(/^\/s\//, "").split("/")[0] || "";
  const m = /^(.+)\.([0-9A-Za-z]{1,8})$/.exec(seg);
  if (m) {
    return { token: m[1], ext: m[2].toLowerCase(), wantRaw: true };
  }
  return { token: seg, ext: null, wantRaw: false };
}

/** 记录是否已过期（expires_at 为空表示长期有效） */
export function isExpired(rec) {
  return !!(rec && rec.expires_at && rec.expires_at <= Date.now());
}

/** 创建短链。返回 { token, url, expiresAt } */
export async function createShare(env, { ossKey, bucket, note, expiresAt }) {
  const now = Date.now();
  // 过期时间：null 表示长期有效；给了就必须是未来时间
  const exp = Number.isFinite(expiresAt) && expiresAt > now ? Math.trunc(expiresAt) : null;
  for (let attempt = 0; attempt < 5; attempt++) {
    const token = makeToken();
    try {
      await env.DB.prepare(
        `INSERT INTO shares (token, oss_key, bucket, note, created_at, revoked, expires_at)
         VALUES (?, ?, ?, ?, ?, 0, ?)`,
      ).bind(token, ossKey, bucket, note || null, now, exp).run();
      return { token, url: `${env.PUBLIC_BASE}/s/${token}`, expiresAt: exp };
    } catch (e) {
      const msg = String(e);
      // UNIQUE 冲突则换一个 token 重试；其它错误直接抛
      if (!msg.includes("UNIQUE") && !msg.includes("constraint")) throw e;
    }
  }
  throw new Error("token_collision");
}

/**
 * 列出分享记录。
 *
 * 用 created_at 做游标：上一页最后一条的 created_at 作为 before 传回来，
 * 就能继续往下翻。此前前端硬编码 limit=500，超过 500 条的记录
 * 「撤销全部」根本看不到，却显示成「全部已撤销」。
 */
export async function listShares(
  env,
  { ossKey, limit = MAX_LIMIT, includeRevoked = true, before } = {},
) {
  const lim = Math.min(Math.max(Number(limit) || MAX_LIMIT, 1), MAX_LIMIT);
  const cond = [];
  const args = [];

  if (ossKey) {
    cond.push("oss_key = ?");
    args.push(ossKey);
  }
  if (!includeRevoked) cond.push("revoked = 0");
  if (Number.isFinite(before) && before > 0) {
    cond.push("created_at < ?");
    args.push(Math.trunc(before));
  }

  let sql = `SELECT token, oss_key, bucket, note, created_at, revoked, revoked_at,
                    expires_at, hits, first_hit, last_hit
             FROM shares`;
  if (cond.length) sql += " WHERE " + cond.join(" AND ");
  // 多取一条用来判断是否还有下一页
  sql += " ORDER BY created_at DESC LIMIT ?";
  args.push(lim + 1);

  const r = await env.DB.prepare(sql).bind(...args).all();
  const all = r.results || [];
  const hasMore = all.length > lim;
  const page = hasMore ? all.slice(0, lim) : all;
  const rows = page.map((x) => ({
    ...x,
    url: `${env.PUBLIC_BASE}/s/${x.token}`,
    expired: x.expires_at ? x.expires_at <= Date.now() : false,
  }));

  return {
    items: rows,
    nextCursor: hasMore && page.length ? page[page.length - 1].created_at : null,
  };
}

/** 撤销单条。返回是否真的改了（幂等：已撤销再撤返回 false） */
export async function revokeShare(env, token) {
  const now = Date.now();
  const r = await env.DB.prepare(
    `UPDATE shares SET revoked = 1, revoked_at = ?
     WHERE token = ? AND revoked = 0`,
  ).bind(now, token).run();
  return (r.meta?.changes ?? 0) > 0;
}

/** 按图片批量撤销（同一张图的所有有效短链一次作废） */
export async function revokeByKey(env, ossKey) {
  const now = Date.now();
  const r = await env.DB.prepare(
    `UPDATE shares SET revoked = 1, revoked_at = ?
     WHERE oss_key = ? AND revoked = 0`,
  ).bind(now, ossKey).run();
  return r.meta?.changes ?? 0;
}

/** 解析 token → 记录（不做访问计数，调用方需要时再记） */
export async function resolveShare(env, token) {
  const r = await env.DB.prepare(
    `SELECT token, oss_key, bucket, revoked, revoked_at, created_at, expires_at
     FROM shares WHERE token = ? LIMIT 1`,
  ).bind(token).first();
  return r || null;
}

/**
 * 记一次访问。每次请求都要写一行 —— 自用场景量级极小；
 * 若将来量大了应改为采样或异步写。
 */
export async function recordHit(env, token) {
  const now = Date.now();
  // 同一 token 一分钟内只记一次。/s/* 是公开端点且无限流，
  // 链接被转发后每次访客都写一行 D1 —— Free 计划日写配额一旦打满，
  // 会连带把创建短链、撤销、收藏同步一起打挂，表现为「突然全都报错」。
  const since = now - HIT_INTERVAL_MS;
  try {
    await env.DB.prepare(
      `UPDATE shares
         SET hits = hits + 1,
             first_hit = COALESCE(first_hit, ?),
             last_hit = ?
       WHERE token = ?
         AND (last_hit IS NULL OR last_hit < ?)`,
    ).bind(now, now, token, since).run();
  } catch (e) {
    // 计数失败不能影响出图
    console.error("recordHit failed", String(e));
  }
}
