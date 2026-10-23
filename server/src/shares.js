/**
 * 短链相关：创建 / 列出 / 撤销 / 解析。
 *
 * token 用 7 位 base62（62^7 ≈ 3.5 万亿），足够抗猜；
 * 冲突时重试 5 次（实际冲突概率极低）。
 */

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

export function makeToken(len = 7) {
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  let s = "";
  for (let i = 0; i < len; i++) s += ALPHABET[bytes[i] % ALPHABET.length];
  return s;
}

/** 创建短链。返回 { token, url } */
export async function createShare(env, { ossKey, bucket, note }) {
  const now = Date.now();
  for (let attempt = 0; attempt < 5; attempt++) {
    const token = makeToken();
    try {
      await env.DB.prepare(
        `INSERT INTO shares (token, oss_key, bucket, note, created_at, revoked)
         VALUES (?, ?, ?, ?, ?, 0)`,
      ).bind(token, ossKey, bucket, note || null, now).run();
      return { token, url: `${env.PUBLIC_BASE}/s/${token}` };
    } catch (e) {
      const msg = String(e);
      // UNIQUE 冲突则换一个 token 重试；其它错误直接抛
      if (!msg.includes("UNIQUE") && !msg.includes("constraint")) throw e;
    }
  }
  throw new Error("token_collision");
}

/** 列出分享记录（默认全部，可按 oss_key 过滤） */
export async function listShares(env, { ossKey, limit = 200, includeRevoked = true }) {
  const lim = Math.min(Math.max(Number(limit) || 200, 1), 500);
  let sql = `SELECT token, oss_key, bucket, note, created_at, revoked, revoked_at,
                    hits, first_hit, last_hit
             FROM shares`;
  const cond = [];
  const args = [];
  if (ossKey) {
    cond.push("oss_key = ?");
    args.push(ossKey);
  }
  if (!includeRevoked) cond.push("revoked = 0");
  if (cond.length) sql += " WHERE " + cond.join(" AND ");
  sql += " ORDER BY created_at DESC LIMIT ?";
  args.push(lim);

  const r = await env.DB.prepare(sql).bind(...args).all();
  const rows = (r.results || []).map((x) => ({
    ...x,
    url: `${env.PUBLIC_BASE}/s/${x.token}`,
  }));
  return rows;
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
    `SELECT token, oss_key, bucket, revoked, revoked_at, created_at
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
  try {
    await env.DB.prepare(
      `UPDATE shares
         SET hits = hits + 1,
             first_hit = COALESCE(first_hit, ?),
             last_hit = ?
       WHERE token = ?`,
    ).bind(now, now, token).run();
  } catch (e) {
    // 计数失败不能影响出图
    console.error("recordHit failed", String(e));
  }
}
