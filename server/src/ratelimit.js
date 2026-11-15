/**
 * 公开路由的限流。
 *
 * 两层，从便宜到贵：
 *
 * 1. Workers Rate Limiting 绑定（`env.RATE_LIMITER`）。计数在 Cloudflare 边缘
 *    本地完成，零成本。**但不能只靠它**：本机实测（2026-11-15）把阈值设成
 *    5 次/60 秒、连打 12 次，`limit()` 仍一路返回 `{success:true}`，
 *    绑定在控制台里显示为 bound，实际没拦。所以它只作为第一道，命中即拒；
 *    不命中不等于放行。
 * 2. Cache API 固定窗口计数。用 `caches.default` 存「桶+IP+窗口序号 → 次数」，
 *    不落 D1、不耗数据库写入量，且能在线上用真实请求验证。
 *    代价：计数按边缘节点各算一份，不是全局精确值。用于抑制滥用足够，
 *    不能当计费依据。
 *
 * 绑定与缓存都不可用时放行。限流是防护手段，不该反过来把看图页全停掉。
 */

/** 公共默认值：每个 IP 每分钟 120 次，够正常浏览，压得住脚本刷。 */
export const DEFAULT_LIMIT = 120;
export const DEFAULT_PERIOD_SEC = 60;

/** 计数用的合成 URL 前缀。走 caches.default，不会真的发请求。 */
const COUNTER_ORIGIN = "https://ratelimit.invalid";

function clientKey(request) {
  // CF-Connecting-IP 由 Cloudflare 注入，客户端改不了；缺失时归到同一桶
  return request.headers.get("CF-Connecting-IP") || "unknown";
}

/**
 * 判定本次请求是否应被限流。
 * @returns {Promise<boolean>} true 表示超限，调用方负责回 429。
 */
export async function tooManyRequests(request, env, bucket,
                                      limit = DEFAULT_LIMIT,
                                      periodSec = DEFAULT_PERIOD_SEC) {
  const ip = clientKey(request);

  // ---- 第一层：边缘绑定 ----
  const rl = env && env.RATE_LIMITER;
  if (rl && typeof rl.limit === "function") {
    try {
      const { success } = await rl.limit({ key: `${bucket}:${ip}` });
      if (success === false) return true;
    } catch (e) {
      console.error("rateLimit binding failed", String(e));
    }
  }

  // ---- 第二层：Cache API 固定窗口 ----
  return counterExceeded(`${bucket}:${ip}`, limit, periodSec);
}

/** 固定窗口计数。窗口对齐到 periodSec 的整数倍，避免滑动窗口的额外状态。 */
async function counterExceeded(name, limit, periodSec) {
  if (typeof caches === "undefined" || !caches.default) return false;
  const now = Math.floor(Date.now() / 1000);
  const windowId = Math.floor(now / periodSec);
  const ttl = periodSec - (now % periodSec) + 1;   // 多留 1 秒，避免边界漏计
  const url = `${COUNTER_ORIGIN}/${encodeURIComponent(name)}/${windowId}`;
  const key = new Request(url, { method: "GET" });

  try {
    const hit = await caches.default.match(key);
    const prev = hit ? Number(await hit.text()) : 0;
    const next = (Number.isFinite(prev) ? prev : 0) + 1;
    if (next > limit) {
      // 已超限也要把计数写回，否则后续请求还能看到旧值重复判定
      await caches.default.put(key, new Response(String(next), {
        headers: { "Cache-Control": `max-age=${ttl}` },
      }));
      return true;
    }
    await caches.default.put(key, new Response(String(next), {
      headers: { "Cache-Control": `max-age=${ttl}` },
    }));
    return false;
  } catch (e) {
    // 缓存不可用（例如无 zone 的 workers.dev 路由）时放行
    console.error("rateLimit counter failed", String(e));
    return false;
  }
}

/** 诊断用：把两层的当前读数带回去，便于线上核对。 */
export async function probe(env, request, bucket = "probe") {
  const out = { key: clientKey(request) };
  const rl = env && env.RATE_LIMITER;
  if (rl && typeof rl.limit === "function") {
    try {
      out.binding = await rl.limit({ key: `${bucket}:${out.key}` });
    } catch (e) {
      out.binding = { error: String(e) };
    }
  } else {
    out.binding = "missing";
  }
  out.cacheSupported = typeof caches !== "undefined" && !!caches.default;
  return out;
}
