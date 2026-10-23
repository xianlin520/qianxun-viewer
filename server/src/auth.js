/**
 * 鉴权：预共享密钥 + HMAC-SHA256。
 *
 * 请求头：
 *   X-QX-Timestamp : 毫秒时间戳
 *   X-QX-Signature : hex(HMAC-SHA256(secret, canonical))
 *   X-QX-Nonce     : 可选，随机串（参与签名，配合时间窗降低重放面）
 *
 * canonical = METHOD \n PATH \n TIMESTAMP \n NONCE \n hex(SHA256(body))
 *
 * 设计要点：
 * - 用 Web Crypto（Workers 官方推荐路径，比纯 JS 快得多）
 * - 时间窗默认 300s，超出直接 401（防重放）
 * - 计时安全比较：用 crypto.subtle.timingSafeEqual（Workers 非标准扩展），
 *   不可用时退化为常量时间字符串比较
 */

const enc = new TextEncoder();

async function sha256Hex(data) {
  const buf = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** 常量时间比较，避免通过响应时间猜签名 */
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * 校验请求签名。
 * @returns {Promise<{ok: true} | {ok: false, status: number, error: string}>}
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

  const windowSec = Number(env.AUTH_WINDOW || 300);
  const skew = Math.abs(Date.now() - tsNum) / 1000;
  if (skew > windowSec) {
    return { ok: false, status: 401, error: "timestamp_out_of_window" };
  }

  // 读取 body 用于签名（注意：调用方需保证 body 未被消费）
  let bodyHash = "";
  if (request.method !== "GET" && request.method !== "HEAD") {
    const raw = await request.clone().arrayBuffer();
    bodyHash = await sha256Hex(raw);
  }

  const url = new URL(request.url);
  const canonical = [
    request.method.toUpperCase(),
    url.pathname,
    ts,
    nonce,
    bodyHash,
  ].join("\n");

  const expected = await hmacHex(secret, canonical);
  if (!safeEqual(expected, sig.toLowerCase())) {
    return { ok: false, status: 401, error: "bad_signature" };
  }

  return { ok: true };
}

/** 供客户端实现参考的签名辅助（README 里同步给出 Python 版本） */
export async function signForClient(secret, method, path, ts, nonce, bodyBytes) {
  const bodyHash = bodyBytes ? await sha256Hex(bodyBytes) : "";
  const canonical = [method.toUpperCase(), path, ts, nonce, bodyHash].join("\n");
  return hmacHex(secret, canonical);
}
