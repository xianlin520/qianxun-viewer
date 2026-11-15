/**
 * 收藏同步（LWW：updated_at 大者胜）。
 *
 * 客户端推送：
 *   POST /api/favorites  body = { items: [{ key, favorite, updated_at }, ...] }
 *   服务端对每条：仅当传入的 updated_at 更新时才覆盖
 *
 * 客户端拉取：
 *   GET /api/favorites?since=<ms>&after=<updated_at>&limit=<n>
 *   返回 updated_at > since 的记录，按 updated_at 升序游标翻页
 *
 * 校验从严：key 必须是非空字符串，updated_at 必须是正数。
 * 此前用 `Number(x) || Date.now()` 兜底，缺字段或时钟错误会被替换成
 * 「当前毫秒」，而 LWW 只接受更大的时间戳——一次错误的推送就能把云端
 * 记录永久盖章成未来时间，真实数据再也覆盖不回来，只能手工改 SQL。
 */

export const MAX_PUSH = 500;
export const MAX_PULL = 1000;

/** 请求体校验失败，由路由层转 400 */
export class ValidationError extends Error {
  constructor(message, index) {
    super(message);
    this.name = "ValidationError";
    this.index = index;
  }
}

/** 校验单条；不合法就抛，不做任何"猜测式"修补 */
export function validateItem(it, index) {
  if (!it || typeof it !== "object") {
    throw new ValidationError("条目必须是对象", index);
  }
  const key = it.key;
  if (typeof key !== "string" || !key.trim()) {
    throw new ValidationError("key 必须是非空字符串", index);
  }
  if (key.length > 1024) {
    throw new ValidationError("key 过长（上限 1024）", index);
  }
  const ts = it.updated_at;
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) {
    throw new ValidationError("updated_at 必须是正数（毫秒时间戳）", index);
  }
  return { key: key.trim(), favorite: it.favorite ? 1 : 0, updated_at: Math.trunc(ts) };
}

/** 批量 upsert，返回实际写入/跳过的条数 */
export async function pushFavorites(env, items) {
  if (!Array.isArray(items) || items.length === 0) {
    return { written: 0, skipped: 0 };
  }
  // 超限直接报错。此前是 slice(0, MAX_PUSH) 悄悄丢弃尾部，
  // 客户端按 200 一批发所以碰不到，但服务端不该把「截断」做成静默行为。
  if (items.length > MAX_PUSH) {
    throw new ValidationError(`单批上限 ${MAX_PUSH} 条，收到 ${items.length} 条`);
  }
  const batch = items.map(validateItem);

  // 单次调用内查询数有上限（Free 50），按 50 一批提交
  const stmt = env.DB.prepare(
    `INSERT INTO favorites (oss_key, favorite, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(oss_key) DO UPDATE SET
       favorite   = excluded.favorite,
       updated_at = excluded.updated_at
     WHERE excluded.updated_at > favorites.updated_at`,
  );

  let written = 0;
  for (let i = 0; i < batch.length; i += 50) {
    const chunk = batch.slice(i, i + 50);
    const results = await env.DB.batch(chunk.map((it) => stmt.bind(it.key, it.favorite, it.updated_at)));
    for (const r of results) written += r.meta?.changes ?? 0;
  }
  return { written, skipped: batch.length - written, accepted: batch.length };
}

/**
 * 拉取收藏。
 * since 为下界（毫秒），after 为游标（上一页最后一条的 updated_at）。
 */
export async function pullFavorites(env, { since, after, limit } = {}) {
  const lim = Math.min(Math.max(Number(limit) || MAX_PULL, 1), MAX_PULL);
  const cond = [];
  const args = [];

  const s = Number(since);
  if (Number.isFinite(s) && s > 0) {
    cond.push("updated_at > ?");
    args.push(Math.trunc(s));
  }
  const a = Number(after);
  if (Number.isFinite(a) && a > 0) {
    cond.push("updated_at > ?");
    args.push(Math.trunc(a));
  }

  let sql = `SELECT oss_key, favorite, updated_at FROM favorites`;
  if (cond.length) sql += " WHERE " + cond.join(" AND ");
  sql += " ORDER BY updated_at ASC LIMIT ?";
  args.push(lim + 1);

  const r = await env.DB.prepare(sql).bind(...args).all();
  const all = r.results || [];
  const hasMore = all.length > lim;
  const page = hasMore ? all.slice(0, lim) : all;

  return {
    items: page.map((x) => ({
      key: x.oss_key,
      favorite: !!x.favorite,
      updated_at: x.updated_at,
    })),
    nextCursor: hasMore && page.length ? page[page.length - 1].updated_at : null,
  };
}
