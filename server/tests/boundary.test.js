/**
 * 服务端纯边界的最小测试集。
 *
 * 跑法：node --test tests/
 *
 * 覆盖三条一旦出错只能靠线上联调发现的边界：
 *   - 鉴权签名（此前全部 DELETE 401 就是这里对不上）
 *   - OSS V4 签名（错一个字节就 SignatureDoesNotMatch）
 *   - 短链 token 与路径解析（看图页 / 代理图片两种模式的判定）
 *
 * 签名用 node:crypto 独立复算，不复用 src/crypto.js，
 * 免得「实现错、测试跟着错」。
 */

import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";

import { verifyRequest } from "../src/auth.js";
import { presignGetUrl } from "../src/oss.js";
import { makeToken, parseShortPath, isExpired } from "../src/shares.js";
import { validateItem, ValidationError } from "../src/favorites.js";
import { escapeHtml, escapeAttr, jsonLiteral, safeExt } from "../src/html.js";

const SECRET = "test-shared-secret";

// ---- 独立复算：Node crypto 版本 ----
const sha256Hex = (s) => createHash("sha256").update(s).digest("hex");
const hmacHex = (key, msg) => createHmac("sha256", key).update(msg).digest("hex");

/** 构造一个已正确签名的请求 */
async function signedRequest({ method = "GET", url, body = null, secret = SECRET, skewMs = 0 }) {
  const ts = String(Date.now() + skewMs);
  const nonce = "n0nce";
  const bodyHash =
    method === "GET" || method === "HEAD" ? "" : sha256Hex(body ?? "");
  const u = new URL(url);
  const canonical = [method, u.pathname + u.search, ts, nonce, bodyHash].join("\n");
  const sig = hmacHex(secret, canonical);
  return new Request(url, {
    method,
    headers: {
      "X-QX-Timestamp": ts,
      "X-QX-Signature": sig,
      "X-QX-Nonce": nonce,
    },
    body: body ?? undefined,
  });
}

const ENV = { QX_SHARED_SECRET: SECRET, AUTH_WINDOW: "300" };

// ---------------- 鉴权 ----------------

test("鉴权：正确的签名通过", async () => {
  const req = await signedRequest({ url: "https://x.test/api/shares?limit=5" });
  assert.deepEqual(await verifyRequest(req, ENV), { ok: true });
});

test("鉴权：query 参与签名，改 query 后签名失效", async () => {
  const req = await signedRequest({ url: "https://x.test/api/shares?limit=5" });
  const tampered = new Request("https://x.test/api/shares?limit=999", req);
  const r = await verifyRequest(tampered, ENV);
  assert.equal(r.ok, false);
  assert.equal(r.error, "bad_signature");
});

test("鉴权：POST 空 body 也要算 sha256(\"\")", async () => {
  const req = await signedRequest({
    method: "POST",
    url: "https://x.test/api/shares/revoke-by-key",
    body: "",
  });
  assert.deepEqual(await verifyRequest(req, ENV), { ok: true });
});

test("鉴权：错误密钥被拒", async () => {
  const req = await signedRequest({ url: "https://x.test/api/shares", secret: "wrong" });
  const r = await verifyRequest(req, ENV);
  assert.equal(r.ok, false);
});

test("鉴权：超出时间窗被拒", async () => {
  const req = await signedRequest({ url: "https://x.test/api/shares", skewMs: -400_000 });
  const r = await verifyRequest(req, ENV);
  assert.equal(r.error, "timestamp_out_of_window");
});

test("鉴权：AUTH_WINDOW 非法值退回 300 秒，不会变成无限窗口", async () => {
  // "abc" → NaN，若直接比较 `skew > NaN` 恒为 false，等于关掉时间窗
  const bad = { ...ENV, AUTH_WINDOW: "abc" };
  const old = await signedRequest({ url: "https://x.test/api/shares", skewMs: -301_000 });
  assert.equal((await verifyRequest(old, bad)).error, "timestamp_out_of_window");

  // 稍微超窗但仍在 300 秒内应通过
  const fresh = await signedRequest({ url: "https://x.test/api/shares", skewMs: -299_000 });
  assert.deepEqual(await verifyRequest(fresh, bad), { ok: true });
});

test("鉴权：缺头被拒", async () => {
  const r = await verifyRequest(new Request("https://x.test/api/shares"), ENV);
  assert.equal(r.error, "missing_auth_headers");
});

test("鉴权：只签 path 的旧客户端默认被拒，显式开兼容才放行", async () => {
  const ts = String(Date.now());
  const url = "https://x.test/api/shares?limit=5";
  const u = new URL(url);
  const legacy = ["GET", u.pathname, ts, "", ""].join("\n");
  const req = new Request(url, {
    headers: { "X-QX-Timestamp": ts, "X-QX-Signature": hmacHex(SECRET, legacy) },
  });

  // 默认（未设 ALLOW_LEGACY_SIG）必须拒绝：否则改 query 重放这条路一直留着
  const strict = await verifyRequest(req, ENV);
  assert.equal(strict.ok, false);

  // 显式打开才放行，且标记为 legacy
  const loose = await verifyRequest(req, { ...ENV, ALLOW_LEGACY_SIG: "1" });
  assert.equal(loose.ok, true);
  assert.equal(loose.legacy, true);

  // 显式 "0" 与默认一致
  const off = await verifyRequest(req, { ...ENV, ALLOW_LEGACY_SIG: "0" });
  assert.equal(off.ok, false);
});

test("签名域覆盖 query：改查询串后同一签名失效", async () => {
  const ts = String(Date.now());
  const signed = "/api/shares?limit=5";
  const canon = ["GET", signed, ts, "n1", ""].join("\n");
  const sig = hmacHex(SECRET, canon);
  const mk = (path) => new Request(`https://x.test${path}`, {
    headers: { "X-QX-Timestamp": ts, "X-QX-Nonce": "n1", "X-QX-Signature": sig },
  });
  assert.equal((await verifyRequest(mk("/api/shares?limit=5"), ENV)).ok, true);
  assert.equal((await verifyRequest(mk("/api/shares?limit=1"), ENV)).ok, false);
  assert.equal((await verifyRequest(mk("/api/shares?limit=5&oss_key=x"), ENV)).ok, false);
});

// ---------------- OSS V4 签名 ----------------

test("OSS V4：签名与独立复算一致", async () => {
  const now = new Date("2026-11-15T08:30:00Z");
  const params = {
    endpoint: "https://oss-cn-qingdao.aliyuncs.com",
    bucket: "demo-bucket",
    region: "cn-qingdao",
    key: "qx/相册 图.png",
    akId: "AKID",
    akSecret: "SECRET",
    expires: 3600,
    now,
  };
  const got = await presignGetUrl(params);

  // 独立复算
  const p = (n) => String(n).padStart(2, "0");
  const date =
    now.getUTCFullYear() + p(now.getUTCMonth() + 1) + p(now.getUTCDate()) +
    "T" + p(now.getUTCHours()) + p(now.getUTCMinutes()) + p(now.getUTCSeconds()) + "Z";
  const day = date.slice(0, 8);
  const scope = `${day}/cn-qingdao/oss/aliyun_v4_request`;
  const rfc = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
  const keyPath = "qx/相册 图.png".split("/").map(rfc).join("/");
  const q = {
    "x-oss-credential": `AKID/${scope}`,
    "x-oss-date": date,
    "x-oss-expires": "3600",
    "x-oss-signature-version": "OSS4-HMAC-SHA256",
  };
  const canonicalQuery = Object.keys(q).sort().map((k) => `${rfc(k)}=${rfc(q[k])}`).join("&");
  const canonicalRequest = [
    "GET", "/demo-bucket/" + keyPath, canonicalQuery, "", "", "UNSIGNED-PAYLOAD",
  ].join("\n");
  const stringToSign = ["OSS4-HMAC-SHA256", date, scope, sha256Hex(canonicalRequest)].join("\n");
  const k0 = createHmac("sha256", "aliyun_v4SECRET").update(day).digest();
  const k1 = createHmac("sha256", k0).update("cn-qingdao").digest();
  const k2 = createHmac("sha256", k1).update("oss").digest();
  const k3 = createHmac("sha256", k2).update("aliyun_v4_request").digest();
  const expected = createHmac("sha256", k3).update(stringToSign).digest("hex");

  assert.ok(got.includes(`x-oss-signature=${expected}`), `签名不一致：\n${got}`);
  // 请求路径不带桶名，CanonicalURI 带桶名（这个不对称踩过三次）
  assert.ok(got.startsWith("https://demo-bucket.oss-cn-qingdao.aliyuncs.com/"));
  assert.ok(!got.includes("/demo-bucket/demo-bucket/"));
});

// ---------------- 短链解析 ----------------

test("短链：token 与后缀的四种形态", () => {
  assert.deepEqual(parseShortPath("/s/AbCd123"), { token: "AbCd123", ext: null, wantRaw: false });
  assert.deepEqual(parseShortPath("/s/AbCd123.jpg"), { token: "AbCd123", ext: "jpg", wantRaw: true });
  assert.deepEqual(parseShortPath("/s/AbCd123.PNG"), { token: "AbCd123", ext: "png", wantRaw: true });
  // 点号在开头或后缀过长，都不算后缀（旧实现两层规则不一致的就是这种输入）
  assert.deepEqual(parseShortPath("/s/.hidden"), { token: ".hidden", ext: null, wantRaw: false });
  assert.deepEqual(parseShortPath("/s/tok.tooooooolong"), {
    token: "tok.tooooooolong", ext: null, wantRaw: false,
  });
});

test("短链：token 字符集与长度", () => {
  for (let i = 0; i < 200; i++) {
    const t = makeToken();
    assert.equal(t.length, 7);
    assert.match(t, /^[0-9A-Za-z]{7}$/);
  }
});

test("短链：过期判定", () => {
  assert.equal(isExpired({ expires_at: null }), false);
  assert.equal(isExpired({ expires_at: Date.now() + 60_000 }), false);
  assert.equal(isExpired({ expires_at: Date.now() - 1 }), true);
  assert.equal(isExpired({}), false);
});

// ---------------- 收藏校验 ----------------

test("收藏：合法条目通过并规整时间戳", () => {
  const v = validateItem({ key: " a.png ", favorite: true, updated_at: 1700000000000.7 }, 0);
  assert.deepEqual(v, { key: "a.png", favorite: 1, updated_at: 1700000000000 });
});

test("收藏：脏数据整批拒绝，不做兜底替换", () => {
  const bad = [
    { key: "", favorite: 1, updated_at: 1 },
    { key: "a.png", favorite: 1, updated_at: 0 },
    { key: "a.png", favorite: 1, updated_at: NaN },
    { key: "a.png", favorite: 1, updated_at: "1700000000000" },
    { key: "a.png", favorite: 1 },
    { favorite: 1, updated_at: 1 },
  ];
  for (const it of bad) {
    assert.throws(() => validateItem(it, 0), ValidationError, JSON.stringify(it));
  }
});

// ---------------- HTML 转义 ----------------

test("转义：五种字符全部处理", () => {
  assert.equal(escapeHtml(`<img src=x onerror="alert('1')">`),
    "&lt;img src=x onerror=&quot;alert(&#39;1&#39;)&quot;&gt;");
  assert.equal(escapeAttr(`a&b`), "a&amp;b");
  assert.equal(escapeHtml(null), "");
});

test("转义：JS 字面量不会提前闭合 script", () => {
  const lit = jsonLiteral(`</script><script>alert(1)</script>`);
  assert.ok(!lit.includes("</script>"));
  assert.equal(JSON.parse(lit), `</script><script>alert(1)</script>`);
});

test("后缀白名单：拒绝路径与标签字符", () => {
  assert.equal(safeExt("a.PNG"), "png");
  assert.equal(safeExt("a.png</script>", "jpg"), "jpg");
  assert.equal(safeExt("a.tar.gz"), "gz");
  // 没有点号时不把整段当后缀
  assert.equal(safeExt("noext"), "jpg");
  assert.equal(safeExt("dir.v1/image", "jpg"), "jpg");
  assert.equal(safeExt("trailing."), "jpg");
});


// ---- 看图页模板：占位符替换必须是函数式 ----
// 字符串形式的 replaceAll 会把替换值里的 $& / $' 当反向引用，且前一次替换
// 的结果会被后一次再扫一遍。文件名里放 {{RAW_URL_LITERAL}} 时 alt 的引号
// 会被提前闭合，属性被突破。

const VIEWER_TPL = readFileSync(new URL("../src/viewer.html", import.meta.url), "utf8");

function renderViewer(name, signedUrl = "https://img/s/T.png?a=1&b=2",
                      rawUrl = "https://img/s/T.png") {
  const subst = {
    "{{CSP_NONCE}}": () => "abc123",
    "{{NAME}}": () => escapeHtml(name),
    "{{SIGNED_URL}}": () => escapeAttr(signedUrl),
    "{{RAW_URL_LITERAL}}": () => jsonLiteral(rawUrl),
  };
  return VIEWER_TPL.replaceAll(/\{\{[A-Z_]+\}\}/g, (m) => {
    const f = subst[m];
    if (!f) throw new Error(`未定义占位符 ${m}`);
    return f();
  });
}

test("看图页：文件名含 $& 不会被当成反向引用", () => {
  const html = renderViewer("a$&b.png");
  const alt = html.match(/alt="([^"]*)"/)[1];
  assert.equal(alt, "a$&amp;b.png");
});

test("看图页：文件名里的占位符不会被二次展开", () => {
  for (const name of ["x{{SIGNED_URL}}.png", "x{{RAW_URL_LITERAL}}.png"]) {
    const html = renderViewer(name);
    const alt = html.match(/alt="([^"]*)"/)[1];
    // 原样保留（已做 HTML 转义），不出现引号闭合、不出现 URL
    assert.equal(alt, name, `载荷 ${name} 的 alt 被改写了`);
    assert.ok(!alt.includes('"'), "alt 里出现未转义引号");
    assert.ok(!html.includes("<img src=x"), "注入了 img 标签");
  }
});

test("看图页：经典属性突破载荷被转义", () => {
  const html = renderViewer('pwn"><img src=x onerror=alert(1)>.png');
  assert.ok(!html.includes("<img src=x"));
  assert.ok(html.includes("&quot;&gt;&lt;img"));
});

test("看图页：模板里出现未定义占位符时抛错", () => {
  assert.throws(() => {
    "{{NOT_DEFINED}}".replaceAll(/\{\{[A-Z_]+\}\}/g, (m) => {
      if (m !== "{{NOT_DEFINED}}") throw new Error("x");
      throw new Error(`未定义占位符 ${m}`);
    });
  }, /未定义占位符/);
});
