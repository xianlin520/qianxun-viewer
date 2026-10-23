/**
 * 收藏同步（LWW：updated_at 大者胜）。
 *
 * 客户端推送：
 *   POST /api/favorites  body = { items: [{ key, favorite, updated_at }, ...] }
 *   服务端对每条：仅当传入的 updated_at 更新时才覆盖
 *
 * 客户端拉取：
 *   GET /api/favorites?since=<ms>
 *   返回 updated_at > since 的记录（since 省略则全量）
 */

/** 批量 upsert，返回实际写入/跳过的条数 */
export async function pushFavorites(env, items) {
  if (!Array.isArray(items) || items.length === 0) {
    return { written: 0, skipped: 0 };
  }
  // 单次调用内查询数有上限（Free 50），分批处理并限制总条数
  const MAX = 500;
  const batch = items.slice(0, MAX);
  const stmt = env.DB.prepare(
    `INSERT INTO favorites (oss_key, favorite, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(oss_key) DO UPDATE SET
       favorite   = excluded.favorite,
       updated_at = excluded.updated_at
     WHERE excluded.updated_at > favorites.updated_at`,
  );
  const stmts = batch.map((it) =>
    stmt.bind(
      String(it.key),
      it.favorite ? 1 : 0,
      Number(it.updated_at) || Date.now(),
    ),
  );
  const results = await env.DB.batch(stmts);
  let written = 0;
  for (const r of results) written += r.meta?.changes ?? 0;
  return { written, skipped: batch.length - written };
}

/** 拉取收藏；since 为毫秒时间戳，可省略 */
export async function pullFavorites(env, { since } = {}) {
  let sql = `SELECT oss_key, favorite, updated_at FROM favorites`;
  const args = [];
  const s = Number(since);
  if (Number.isFinite(s) && s > 0) {
    sql += " WHERE updated_at > ?";
    args.push(s);
  }
  sql += " ORDER BY updated_at ASC LIMIT 5000";
  const r = await env.DB.prepare(sql).bind(...args).all();
  return (r.results || []).map((x) => ({
    key: x.oss_key,
    favorite: !!x.favorite,
    updated_at: x.updated_at,
  }));
}
