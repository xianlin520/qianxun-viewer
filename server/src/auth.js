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
 * ALLOW_LEGACY_SIG=0 可强制只认新签名；默认 1 以便平滑升级。
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
    return { ok: true };
  }

  // 兼容窗口：旧客户端只签 path。设为 "0" 即关闭，建议下次发版后关掉。
  if (String(env.ALLOW_LEGACY_SIG ?? "1") !== "0") {
    const legacy = [method, url.pathname, ts, nonce, bodyHash].join("\n");
    if (safeEqual(await hmacHex(secret, legacy), given)) {
      return { ok: true, legacy: true };
    }
  }

  return { ok: false, status: 401, error: "bad_signature" };
}
