/**
 * 鉴权：预共享密钥 + HMAC-SHA256。
 *
 * 请求头：
 *   X-QX-Timestamp : 毫秒时间戳
 *   X-QX-Signature : hex(HMAC-SHA256(secret, canonical))
 *   X-QX-Nonce     : 可选，随机串。参与签名，但服务端不存储比对，
 *                    因此它不防重放 —— 重放窗口等于 AUTH_WINDOW（默认 300 秒）。
 *                    要真正防重放需要把 nonce 落库去重，本期未做。
 *
 * canonical = METHOD \n PATH?QUERY \n TIMESTAMP \n NONCE \n hex(SHA256(body))
 *
 * 现在 query 也参与签名。此前只签 pathname，被截获的请求可以改 query
 * 重放（例如把 limit 放大）。旧客户端仍按 path 签名，用
 * ALLOW_LEGACY_SIG 默认关闭：客户端 v1.6.5 起已全部签 PATH?QUERY，
 * 兼容分支只留给尚未升级的旧版本，需要时显式设 "1" 打开。
 */

import { sha256Hex, hmacHex, safeEqual } from "./crypto.js";

const DEFAULT_WINDOW_SEC = 300;
const MAX_WINDOW_SEC = 3600;

/**
 * 解析时间窗配置。
 *
 * AUTH_WINDOW 是字符串形式的 vars，写成 "abc" 会得到 NaN，
 * 而 `skew > NaN` 恒为 false，等于把时间窗彻底关掉。这里显式校验，
 * 非法值退回默认 300 秒，并夹取上限避免误配成超大窗口。
 */
function authWindowSec(env) {
  const raw = Number(env.AUTH_WINDOW);
  if (!Number.isFinite(raw) || raw <= 0) return DEFAULT_WINDOW_SEC;
  return Math.min(raw, MAX_WINDOW_SEC);
}

/**
 * 校验请求签名。
 * @returns {Promise<{ok: true, legacy?: true} | {ok: false, status: number, error: string}>}
 */
/**
 * 记录已用过的 nonce；同一 nonce 第二次出现判定为重放。
 *
 * 此前 nonce 只参与签名、不落库，时间窗内抓到一条请求就能原样重放。
 * 用 INSERT ... ON CONFLICT DO NOTHING 的 changes 数判断，一次往返完成。
 * 没有绑定 DB（单测环境）时跳过，保持纯函数可测。
 */
async function claimNonce(env, nonce, ts, ok) {
  if (!env || !env.DB || !nonce) return ok;
  try {
    const r = await env.DB
      .prepare("INSERT INTO nonce_seen (nonce, ts) VALUES (?, ?) ON CONFLICT(nonce) DO NOTHING")
      .bind(nonce, Number(ts) || Date.now())
      .run();
    if ((r.meta?.changes ?? 0) === 0) {
      return { ok: false, status: 401, error: "nonce_replayed" };
    }
  } catch (e) {
    // 表不存在或写入失败时放行：鉴权不能因为清理任务把正常请求全挡掉
    console.error("claimNonce failed", String(e));
  }
  return ok;
}

/** 抽样清理过期 nonce，避免表无限增长。调用方用 waitUntil 挂上。 */
export async function pruneNonces(env, windowSec) {
  if (!env || !env.DB) return 0;
  const cutoff = Date.now() - (windowSec + 60) * 1000;
  try {
    const r = await env.DB.prepare("DELETE FROM nonce_seen WHERE ts < ?").bind(cutoff).run();
    return r.meta?.changes ?? 0;
  } catch (e) {
    console.error("pruneNonces failed", String(e));
    return 0;
  }
}

export async function verifyRequest(request, env) {
  const secret = env.QX_SHARED_SECRET;
  if (!secret) {
    return { ok: false, status: 500, error: "server_misconfigured" };
  }

  const ts = request.headers.get("X-QX-Timestamp");
  const sig = request.headers.get("X-QX-Signature");
  const nonce = request.headers.get("X-QX-Nonce") || "";

  if (!ts || !sig) {
    return { ok: false, status: 401, error: "missing_auth_headers" };
  }

  const tsNum = Number(ts);
  if (!Number.isFinite(tsNum)) {
    return { ok: false, status: 401, error: "bad_timestamp" };
  }

  const windowSec = authWindowSec(env);
  const skew = Math.abs(Date.now() - tsNum) / 1000;
  if (skew > windowSec) {
    return { ok: false, status: 401, error: "timestamp_out_of_window" };
  }

  // 读取 body 用于签名（调用方需保证 body 未被消费）
  let bodyHash = "";
  if (request.method !== "GET" && request.method !== "HEAD") {
    const raw = await request.clone().arrayBuffer();
    bodyHash = await sha256Hex(raw);
  }

  const url = new URL(request.url);
  const method = request.method.toUpperCase();
  const given = sig.toLowerCase();

  // 当前协议：path + query 一起签名
  const canonical = [
    method,
    url.pathname + url.search,
    ts,
    nonce,
    bodyHash,
  ].join("\n");
  if (safeEqual(await hmacHex(secret, canonical), given)) {
    return await claimNonce(env, nonce, ts, { ok: true });
  }

  // 兼容窗口：旧客户端只签 path。设为 "0" 即关闭，建议下次发版后关掉。
  if (String(env.ALLOW_LEGACY_SIG ?? "0") === "1") {
    const legacy = [method, url.pathname, ts, nonce, bodyHash].join("\n");
    if (safeEqual(await hmacHex(secret, legacy), given)) {
      return await claimNonce(env, nonce, ts, { ok: true, legacy: true });
    }
  }

  return { ok: false, status: 401, error: "bad_signature" };
}
