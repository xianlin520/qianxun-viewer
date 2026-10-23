/**
 * 阿里云 OSS V4 签名（OSS4-HMAC-SHA256），纯 Web Crypto 实现。
 *
 * 为什么需要自己实现：Workers 里不能用 Node 的 crypto，也没有现成的
 * OSS V4 × Workers 包（调研确认）。所需能力只有 HMAC-SHA256 与 SHA256-hex，
 * Web Crypto 全部支持，且密钥派生链可以用上一轮的 ArrayBuffer 作为 keyData。
 *
 * 算法（按阿里云规范）：
 *   CanonicalRequest = VERB \n URI \n QUERY \n HEADERS \n ADDITIONAL \n HASHED_PAYLOAD
 *   StringToSign     = "OSS4-HMAC-SHA256" \n TIMESTAMP \n SCOPE \n HEX(SHA256(CanonicalRequest))
 *   DateKey          = HMAC("aliyun_v4" + SK, Date)
 *   DateRegionKey    = HMAC(DateKey, Region)
 *   DateRegionSvcKey = HMAC(DateRegionKey, "oss")
 *   SigningKey       = HMAC(DateRegionSvcKey, "aliyun_v4_request")
 *   Signature        = HEX(HMAC(SigningKey, StringToSign))
 *
 * 约束：x-oss-expires 1~604800 秒；x-oss-date 与派生密钥的 Date 必须同一天。
 */

const enc = new TextEncoder();

async function sha256Bytes(data) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", data));
}

async function sha256Hex(data) {
  const b = await sha256Bytes(data);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function hmacRaw(keyBytes, msgStr) {
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msgStr)));
}

function hex(b) {
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** RFC 3986 编码，OSS 要求（空格为 %20，斜杠保留由调用方决定） */
function rfc3986(str, keepSlash = false) {
  return encodeURIComponent(str).replace(
    /[!'()*]/g,
    (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase(),
  ).replace(keepSlash ? /%2F/g : /$^/, "/");
}

/** OSS 时间格式：20241203T034420Z */
function ossDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return (
    d.getUTCFullYear() +
    p(d.getUTCMonth() + 1) +
    p(d.getUTCDate()) +
    "T" +
    p(d.getUTCHours()) +
    p(d.getUTCMinutes()) +
    p(d.getUTCSeconds()) +
    "Z"
  );
}

function dayStamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate());
}

/**
 * 生成 OSS 预签名 GET URL。
 *
 * @param {object} o
 * @param {string} o.endpoint  如 https://oss-cn-qingdao.aliyuncs.com
 * @param {string} o.bucket
 * @param {string} o.region    如 cn-qingdao
 * @param {string} o.key       对象 key
 * @param {string} o.akId
 * @param {string} o.akSecret
 * @param {number} [o.expires] 秒，1~604800
 * @param {Record<string,string>} [o.extraQuery] 额外查询参数（会参与签名）
 * @returns {Promise<string>}
 */
export async function presignGetUrl({
  endpoint,
  bucket,
  region,
  key,
  akId,
  akSecret,
  expires = 3600,
  extraQuery = {},
}) {
  const now = new Date();
  const date = ossDate(now);
  const day = dayStamp(now);
  const scope = `${day}/${region}/oss/aliyun_v4_request`;

  const host = `${bucket}.${endpoint.replace(/^https?:\/\//, "").replace(/\/$/, "")}`;
  // CanonicalURI 必须带桶名：OSS 的规范是 /<bucket>/<key>。
  // 注意这与「请求 URL」不同 —— 虚拟主机式访问时请求路径只是 /<key>
  // （桶名在 Host 头里），但参与签名计算的 URI 要带上桶名。
  // 实测对照 OSS 返回的 <CanonicalRequest> 才确认这一点：
  //   [1] '/xianlin-oss/qx/113657748_p0.png'
  const canonicalUri =
    "/" + bucket + "/" + key.split("/").map((s) => rfc3986(s)).join("/");
  // 请求用的路径（不含桶名）
  const requestPath = "/" + key.split("/").map((s) => rfc3986(s)).join("/");

  // 查询参数：OSS 要求按 key 字典序、URL 编码后拼接
  const q = {
    "x-oss-credential": `${akId}/${scope}`,
    "x-oss-date": date,
    "x-oss-expires": String(expires),
    "x-oss-signature-version": "OSS4-HMAC-SHA256",
    ...extraQuery,
  };
  const queryKeys = Object.keys(q).sort();
  const canonicalQuery = queryKeys
    .map((k) => `${rfc3986(k)}=${rfc3986(q[k])}`)
    .join("&");

  // CanonicalHeaders：预签名到 URL 的场景下 OSS 不要求任何签名头
  // （实测 OSS 算出来这一行是空串）。若未来要用 x-oss-additional-headers
  // 锁定 header，才在这里补 "host:..." 之类。
  const canonicalHeaders = "";
  const additionalHeaders = ""; // 未使用 x-oss-additional-headers
  const hashedPayload = "UNSIGNED-PAYLOAD";

  const canonicalRequest = [
    "GET",
    canonicalUri,
    canonicalQuery,
    canonicalHeaders,
    additionalHeaders,
    hashedPayload,
  ].join("\n");

  const stringToSign = [
    "OSS4-HMAC-SHA256",
    date,
    scope,
    await sha256Hex(enc.encode(canonicalRequest)),
  ].join("\n");

  // 密钥派生链（每层输出 ArrayBuffer 直接作为下一层 key）
  const k0 = await hmacRaw(enc.encode("aliyun_v4" + akSecret), day);
  const k1 = await hmacRaw(k0, region);
  const k2 = await hmacRaw(k1, "oss");
  const k3 = await hmacRaw(k2, "aliyun_v4_request");

  const signature = hex(await hmacRaw(k3, stringToSign));

  // 返回的 URL 用 requestPath（不带桶名），签名里已经用了 canonicalUri
  return `https://${host}${requestPath}?${canonicalQuery}&x-oss-signature=${signature}`;
}
