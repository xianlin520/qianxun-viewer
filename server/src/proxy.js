/**
 * 图片代理：回源 OSS，剥掉强制下载头，改为内联展示。
 *
 * 为什么需要它：实测确认 OSS 默认域名会对图片类对象强制附加
 * x-oss-force-download: true + Content-Disposition: attachment，
 * 且 response-content-disposition=inline 参数无法覆盖。
 * 只有换出口（自定义域名或代理）能解决，这里就是那个出口。
 *
 * 看图页的 HTML 放在 viewer.html，本文件只做「取值 → 转义 → 替换」。
 * 所有动态值必须经过 html.js 的转义函数，不要手工拼接。
 */

import { presignGetUrl } from "./oss.js";
import { resolveShare, recordHit, isExpired, parseShortPath } from "./shares.js";
import { escapeHtml, escapeAttr, jsonLiteral, safeExt } from "./html.js";
import VIEWER_TEMPLATE from "./viewer.html";

const IMAGE_TYPES = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
  tif: "image/tiff",
  tiff: "image/tiff",
};

/**
 * 只认白名单里的图片类型。
 *
 * 上游响应头不可信：客户端直连 OSS 写桶，任何使用者都能上传一个
 * Content-Type: text/html 的对象并建短链，若原样透传就会在同源渲染
 * 任意 HTML。这里永远不读上游 Content-Type。
 */
function contentTypeFor(key) {
  const ext = safeExt(key, "");
  return IMAGE_TYPES[ext] || "application/octet-stream";
}

function basename(key) {
  return key.split("/").pop() || "image";
}

/** 页面通用安全头。CSP 收紧到「只有本页内联样式与带 nonce 的脚本」 */
function pageHeaders(nonce) {
  return {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": [
      "default-src 'none'",
      "img-src 'self' https: data: blob:",
      "style-src 'unsafe-inline'",
      nonce ? `script-src 'nonce-${nonce}'` : "script-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'none'",
    ].join("; "),
  };
}

/** 410 / 404 / 502 之类的简单 HTML 响应 */
function errorPage(status, title, detail) {
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101112">
<title>${escapeHtml(title)}</title>
<style>
  html,body{margin:0;height:100%}
  body{min-height:100%;display:flex;align-items:center;justify-content:center;
       background:#101112;color:#e8eaed;padding:24px;
       font:16px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
       -webkit-text-size-adjust:100%}
  .box{max-width:440px;text-align:center}
  h1{font-size:19px;margin:0 0 10px;font-weight:600}
  p{margin:0;color:#8a8f98;font-size:14px}
</style></head>
<body><div class="box"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail)}</p></div></body></html>`;
  return new Response(html, {
    status,
    headers: pageHeaders(null),
  });
}

/** 看图页：用 <img> 直接引用 OSS 签名 URL。
 *
 * 关键实测结论（2026-10-23，无头 Chrome 验证）：
 *   OSS 强制加的 `Content-Disposition: attachment` 只影响顶层导航，
 *   对 `<img src>` 这类子资源完全不生效，图片照常渲染。
 *
 * 所以这个页面的图片走 OSS 直连（~95ms），只消耗 1 次 Worker 请求；
 * 流式代理要 2.4~3.4s（Cloudflare 国内绕路）。
 */
function viewerPage(rec, signedUrl, pageUrl, token) {
  const name = basename(rec.oss_key);
  const ext = safeExt(rec.oss_key, "jpg");

  // 「复制代理链接」= /s/<token>.<ext>，走 Worker 代理图片字节
  const rawUrl = (() => {
    try {
      const u = new URL(pageUrl);
      u.pathname = `/s/${token}.${ext}`;
      u.search = "";
      return u.toString();
    } catch {
      return `/s/${token}.${ext}`;
    }
  })();

  const nonce = crypto.randomUUID().replace(/-/g, "");
  // 必须用函数形式：字符串形式下 JS 会把替换值里的 $& / $' 当反向引用，
  // 且前面的替换结果会被后面的 replaceAll 再次展开。实测文件名里带
  // {{RAW_URL_LITERAL}} 时 alt 的引号会被提前闭合，属性被突破。
  const subst = {
    "{{CSP_NONCE}}": () => nonce,
    "{{NAME}}": () => escapeHtml(name),
    "{{SIGNED_URL}}": () => escapeAttr(signedUrl),
    "{{RAW_URL_LITERAL}}": () => jsonLiteral(rawUrl),
  };
  const html = VIEWER_TEMPLATE.replaceAll(/\{\{[A-Z_]+\}\}/g, (m) => {
    const f = subst[m];
    if (!f) throw new Error(`viewer.html 有未定义的占位符：${m}`);
    return f();
  });

  return new Response(html, {
    status: 200,
    headers: pageHeaders(nonce),
  });
}

/**
 * 处理 /s/<token>
 *
 * 两种模式：
 *   默认              → 返回 HTML 看图页，图片走 OSS 直连（快，~95ms）
 *   /s/<token>.<ext>  → 流式代理图片字节（链接像图片，下载文件名 = token.ext）
 */
/** 计一次访问。有 ctx 就交给 waitUntil，别把 D1 写延迟加在首字节上。 */
function scheduleHit(env, token, ctx) {
  const p = recordHit(env, token);
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p);
  return ctx ? null : p;
}

export async function handleShortLink(request, env, token, ctx) {
  if (!token || !/^[0-9A-Za-z]{4,16}$/.test(token)) {
    return errorPage(404, "链接无效", "短链格式不正确。");
  }

  const rec = await resolveShare(env, token);

  if (!rec) {
    return errorPage(404, "链接不存在", "这个短链没有对应的图片，可能从未创建或被彻底删除。");
  }

  // 撤销判定放在最前面，且每次请求都查库（不缓存判定结果），
  // 保证撤销立即生效 —— 这是选 D1 而不是 KV 的根本原因。
  if (rec.revoked) {
    return errorPage(
      410,
      "链接已失效",
      "这张图片的分享链接已被撤销。如果仍需要，请让分享者重新生成。",
    );
  }

  // 过期与撤销同样处理：410 且提示重新生成
  if (isExpired(rec)) {
    return errorPage(
      410,
      "链接已过期",
      "这张图片的分享链接已到期。如果仍需要，请让分享者重新生成。",
    );
  }

  // 判断本次请求是「看图页」还是「代理图片」：
  //   /s/<token>             → 看图页
  //   /s/<token>.<ext>       → 代理图片（链接以图片后缀结尾）
  //   /s/<token>?raw=1       → 兼容旧写法，也走代理
  // 后缀判定与路由层共用 parseShortPath，避免两层规则不等价。
  // 另外保留 ?raw=1 作为兼容写法。
  const wantRaw =
    parseShortPath(new URL(request.url).pathname).wantRaw ||
    new URL(request.url).searchParams.get("raw") === "1";

  // 构造 OSS 签名 URL
  let signedUrl;
  try {
    signedUrl = await presignGetUrl({
      endpoint: env.OSS_ENDPOINT,
      bucket: rec.bucket || env.OSS_BUCKET,
      region: env.OSS_REGION,
      key: rec.oss_key,
      akId: env.OSS_AK_ID,
      akSecret: env.OSS_AK_SECRET,
      // HTML 页模式下签名要覆盖「用户打开页面 + 慢网加载 + 会话内重看」的时间；
      // raw 代理模式只需要覆盖一次回源，短一点更安全。
      expires: wantRaw ? 900 : 3600,
    });
  } catch (e) {
    console.error("presign failed", String(e));
    return errorPage(500, "签名失败", "服务端无法生成图片地址，请稍后重试。");
  }

  // ---- 分派 ----
  if (!wantRaw) {
    return serveViewerPage(rec, signedUrl, request, token, env, ctx);
  }
  return serveRawImage(request, rec, signedUrl, token, env, ctx);
}

/**
 * 看图页：只回一张 HTML，图片由浏览器直连 OSS。
 *
 * 主路径。一次页面请求只消耗 1 次 Worker 请求，撤销判定在这里完成。
 */
async function serveViewerPage(rec, signedUrl, request, token, env, ctx) {
  const pending = scheduleHit(env, token, ctx);
  if (pending) await pending;
  return viewerPage(rec, signedUrl, request.url, token);
}

/**
 * 代理图片字节（?raw=1 或 /s/<token>.<ext>）。
 *
 * 国内经 Cloudflare 绕路 2~4 秒，只用于「想在地址栏直接看到图」的场合。
 * 响应头全部本地重建：Content-Type 走白名单推断，绝不透传上游，
 * 否则一个被改写的对象就能让浏览器当 HTML 执行。
 */
async function serveRawImage(request, rec, signedUrl, token, env, ctx) {
  let upstream;
  try {
    upstream = await fetch(signedUrl, {
      method: "GET",
      headers: { Accept: request.headers.get("Accept") || "*/*" },
    });
  } catch (e) {
    // 网络层失败：降级为 302，至少让用户能下载
    console.error("origin fetch failed", String(e));
    return Response.redirect(signedUrl, 302);
  }

  if (!upstream.ok) {
    if (upstream.status === 404) {
      return errorPage(404, "图片不存在", "云端对象已不存在，可能已被删除。");
    }
    // 其它错误（403/5xx）：降级 302，用户可以自己点下载
    console.error("origin status", upstream.status);
    return Response.redirect(signedUrl, 302);
  }

  // 计一次访问（失败不影响出图）
  const hitPending = scheduleHit(env, token, ctx);
  if (hitPending) await hitPending;

  const headers = new Headers();
  // 只用本地白名单推断，绝不透传上游 Content-Type（见 contentTypeFor 注释）
  headers.set("Content-Type", contentTypeFor(rec.oss_key));
  // 禁止浏览器嗅探：即使对象内容不是图片，也不会被当成 HTML 执行
  headers.set("X-Content-Type-Options", "nosniff");
  // 文件名用「短链名.后缀」，例如 s/Jx2Yf9a.jpg。
  // 这样无论用 download 属性还是右键另存，拿到的都是有意义且格式正确的名字。
  const fileName = `${token}.${safeExt(rec.oss_key, "jpg")}`;
  headers.set(
    "Content-Disposition",
    `inline; filename="${fileName}"; filename*=UTF-8''${encodeURIComponent(fileName)}`,
  );
  // 明确不把 OSS 的强制下载头透传出去
  headers.delete("x-oss-force-download");

  const len = upstream.headers.get("Content-Length");
  if (len) headers.set("Content-Length", len);

  // 缓存策略：图片内容本身可缓存（省 OSS 流量），但撤销判定在缓存之外，
  // 所以即使这里命中缓存，也只会影响「字节」，不会让已撤销链接复活。
  headers.set("Cache-Control", "public, max-age=3600");

  return new Response(upstream.body, { status: 200, headers });
}