/**
 * 图片代理：回源 OSS，剥掉强制下载头，改为内联展示。
 *
 * 这是整个服务端存在的核心理由：实测确认 OSS 默认域名会对图片类对象
 * 强制附加 x-oss-force-download: true + Content-Disposition: attachment，
 * 且 response-content-disposition=inline 参数**无法覆盖**。
 * 只有换出口（自定义域名或代理）能解决，本函数就是那个出口。
 *
 * 流程：
 *   1. 查 D1 确认 token 有效（撤销立即生效，不依赖缓存）
 *   2. 用 V4 签名拿 OSS URL
 *   3. 回源；失败则降级 302 到签名 URL（至少能下载）
 *   4. 重写响应头：删 force-download、改 inline、保真 Content-Type
 *   5. 流式回传，不缓冲整个文件（128MB 内存限制）
 */

import { presignGetUrl } from "./oss.js";
import { resolveShare, recordHit } from "./shares.js";

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

function contentTypeFor(key) {
  const ext = key.split(".").pop().toLowerCase();
  return IMAGE_TYPES[ext] || "application/octet-stream";
}

function basename(key) {
  return key.split("/").pop() || "image";
}

/** 410 / 404 / 502 之类的简单 HTML 响应 */
function errorPage(status, title, detail) {
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#202124;color:#e8eaed;font:16px/1.7 -apple-system,"Segoe UI",sans-serif}
  .box{max-width:440px;padding:32px;text-align:center}
  h1{font-size:20px;margin:0 0 12px}
  p{margin:0;color:#8a8f98;font-size:14px}
</style></head>
<body><div class="box"><h1>${title}</h1><p>${detail}</p></div></body></html>`;
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

/**
 * 处理 /s/<token>
 */
export async function handleShortLink(request, env, token) {
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
      expires: 900, // 9 分钟：足够取图，且暴露风险小
    });
  } catch (e) {
    console.error("presign failed", String(e));
    return errorPage(500, "签名失败", "服务端无法生成图片地址，请稍后重试。");
  }

  // 回源取图
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
  await recordHit(env, token);

  // ---- 关键：重写响应头 ----
  const headers = new Headers();
  const ct = upstream.headers.get("Content-Type") || contentTypeFor(rec.oss_key);
  headers.set("Content-Type", ct);
  // 内联展示而非下载
  headers.set(
    "Content-Disposition",
    `inline; filename="${encodeURIComponent(basename(rec.oss_key))}"`,
  );
  // 明确不把 OSS 的强制下载头透传出去
  headers.delete("x-oss-force-download");

  const len = upstream.headers.get("Content-Length");
  if (len) headers.set("Content-Length", len);

  // 缓存策略：图片内容本身可缓存（省 OSS 流量），但撤销判定在缓存之外，
  // 所以即使这里命中缓存，也只会影响“字节”，不会让已撤销链接复活。
  headers.set("Cache-Control", "public, max-age=3600");

  return new Response(upstream.body, {
    status: 200,
    headers,
  });
}
