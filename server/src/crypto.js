/**
 * Web Crypto 封装。服务端所有哈希与 HMAC 都从这里取。
 *
 * 原先 auth.js 与 oss.js 各有一份 sha256Hex，hex 转换散在四处，
 * 签名路径「改一处必须改两处」，漏改的表现不是报错而是某条路径
 * 签名永远对不上。统一到这里后只有一套实现。
 */

const enc = new TextEncoder();

/** 字节数组 → 小写 hex */
export function hex(bytes) {
  return [...new Uint8Array(bytes)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** 字符串或字节 → SHA-256 原始字节 */
export async function sha256Bytes(data) {
  const buf = typeof data === "string" ? enc.encode(data) : data;
  return new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
}

/** 字符串或字节 → SHA-256 的 hex */
export async function sha256Hex(data) {
  return hex(await sha256Bytes(data));
}

/** HMAC-SHA256，密钥是原始字节，结果留作字节（OSS 密钥派生链要用） */
export async function hmacRaw(keyBytes, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
}

/** HMAC-SHA256，密钥是字符串，结果转 hex（鉴权用） */
export async function hmacHex(secret, message) {
  return hex(await hmacRaw(enc.encode(secret), message));
}

/**
 * 常量时间比较，避免通过响应时间推断签名。
 * 长度不同直接返回 false（长度本身不敏感）。
 */
export function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
