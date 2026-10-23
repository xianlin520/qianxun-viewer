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

/** 看图页：用 <img> 直接引用 OSS 签名 URL。
 *
 * 关键实测结论（2026-10-23，无头 Chrome 验证）：
 *   OSS 强制加的 `Content-Disposition: attachment` **只影响顶层导航**，
 *   对 `<img src>` 这类子资源完全不生效 —— 图片照常渲染（LOADED 512x362）。
 *
 * 所以这个页面让图片走 OSS 直连（~95ms），只消耗 1 次 Worker 请求；
 * 而流式代理要 2.4~3.4s（Cloudflare 国内绕路 MRS/SIN）。
 */
function viewerPage(rec, signedUrl, pageUrl) {
  const name = basename(rec.oss_key);
  // 「复制代理链接」要复制的地址：本页加 ?raw=1，
  // 打开后由 Worker 代理图片字节并重写响应头为 inline。
  const rawUrl = (() => {
    try {
      const u = new URL(pageUrl);
      u.search = "raw=1";
      return u.toString();
    } catch {
      return pageUrl + "?raw=1";
    }
  })();
  // 用 JSON.stringify 安全嵌入，避免文件名里的引号破坏 JS
  const jsName = JSON.stringify(name);
  const jsUrl = JSON.stringify(signedUrl);
  const jsRaw = JSON.stringify(rawUrl);
  const html = `<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${name}</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    background: #101112; color: #e8eaed; display: flex; flex-direction: column;
    font: 14px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  }
  header {
    display: flex; align-items: center; gap: 10px; padding: 9px 16px;
    background: rgba(0,0,0,.55); backdrop-filter: blur(6px);
    border-bottom: 1px solid #2a2b2e; flex: 0 0 auto; z-index: 2;
    position: relative;
  }
  .name { flex: 0 1 auto; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c7cbd4; }
  /* 居中标题：绝对定位保证真正居中，不受左右内容宽度影响 */
  .brand {
    position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
    font-size: 14px; font-weight: 600; letter-spacing: .06em;
    color: #e8eaed; white-space: nowrap; pointer-events: none;
  }
  .brand span { color: #8ab4f8; }
  a.btn, button.btn {
    appearance: none; border: 1px solid #3a3b3e; background: #26272b; color: #c7cbd4;
    padding: 5px 12px; border-radius: 6px; font-size: 13px; cursor: pointer;
    text-decoration: none; white-space: nowrap; font-family: inherit;
  }
  a.btn:hover, button.btn:hover { background: #313236; color: #e8eaed; }
  /* 舞台：永不出现滚动条，平移靠 transform */
  #stage {
    flex: 1; position: relative; overflow: hidden;
    cursor: grab; touch-action: none; user-select: none;
  }
  #stage.dragging { cursor: grabbing; }
  /* 图片用 transform 定位缩放，origin 在左上角便于锚点计算 */
  #pic {
    position: absolute; top: 0; left: 0; transform-origin: 0 0;
    will-change: transform; -webkit-user-drag: none;
    image-rendering: auto;
  }
  .hint {
    position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
    background: rgba(0,0,0,.62); padding: 5px 14px; border-radius: 12px;
    font-size: 12px; color: #8a8f98; pointer-events: none; z-index: 3;
    transition: opacity .4s; white-space: nowrap;
  }
</style></head>
<body>
<header>
  <span class="name">${name}</span>
  <div class="brand">千寻<span>影集</span></div>
  <a class="btn" href="${signedUrl}" download="${name}">下载原图</a>
  <button class="btn" id="copy">复制代理链接</button>
  <button class="btn" id="zoom">实际大小</button>
</header>
<div id="stage"><img id="pic" src="${signedUrl}" alt="${name}"></div>
<div class="hint" id="hint">加载中…</div>
<script>
(function () {
  var stage = document.getElementById('stage');
  var img = document.getElementById('pic');
  var zoomBtn = document.getElementById('zoom');
  var hint = document.getElementById('hint');
  var copyBtn = document.getElementById('copy');

  var MAX_ZOOM = 8;          // 最大放大倍数（相对原图）
  var scale = 1;             // 当前缩放
  var fitScale = 1;          // 适合窗口的缩放
  var tx = 0, ty = 0;        // 平移
  var nw = 0, nh = 0;        // 原图尺寸
  var mode = 'fit';          // 'fit' | 'actual' | 'custom'

  function stageRect() {
    return { w: stage.clientWidth, h: stage.clientHeight };
  }

  function computeFit() {
    if (!nw || !nh) return 1;
    var r = stageRect();
    return Math.min(r.w / nw, r.h / nh);
  }

  /** 把图片限制在舞台可视范围内；比舞台小时居中 */
  function clampPan() {
    var r = stageRect();
    var iw = nw * scale, ih = nh * scale;
    if (iw <= r.w) {
      tx = (r.w - iw) / 2;
    } else {
      tx = Math.min(0, Math.max(r.w - iw, tx));
    }
    if (ih <= r.h) {
      ty = (r.h - ih) / 2;
    } else {
      ty = Math.min(0, Math.max(r.h - ih, ty));
    }
  }

  function render() {
    img.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
    var pct = Math.round(scale * 100);
    zoomBtn.textContent = (mode === 'fit') ? '实际大小' : '适合窗口';
    hud(pct);
  }

  var hudTimer = null;
  function hud(extra) {
    if (!nw) return;
    var txt = nw + ' × ' + nh + '　' + extra + '%';
    if (mode === 'fit') txt += '（适合窗口）';
    hint.textContent = txt;
    hint.style.opacity = '1';
    if (hudTimer) clearTimeout(hudTimer);
    hudTimer = setTimeout(function () { hint.style.opacity = '0.4'; }, 2200);
  }

  function goFit() {
    fitScale = computeFit();
    scale = fitScale;
    mode = 'fit';
    clampPan();
    render();
  }

  /** 以舞台坐标 (mx,my) 为锚点缩放到 targetScale */
  function zoomAt(mx, my, targetScale) {
    var r = stageRect();
    var lo = Math.min(fitScale * 0.5, 0.02);
    var hi = MAX_ZOOM;
    var ns = Math.max(lo, Math.min(hi, targetScale));
    if (Math.abs(ns - scale) < 1e-6) return;
    var k = ns / scale;
    // 锚点保持不动：newT = m - (m - t) * k
    tx = mx - (mx - tx) * k;
    ty = my - (my - ty) * k;
    scale = ns;
    mode = (Math.abs(scale - fitScale) < 1e-4) ? 'fit' : 'custom';
    clampPan();
    render();
  }

  /** 双击：适合窗口 ⇄ 实际大小（1:1），并定位到点击处 */
  function toggleAt(mx, my) {
    if (mode === 'fit') {
      mode = 'actual';
      zoomAt(mx, my, 1);
      if (Math.abs(scale - 1) > 1e-6) { scale = 1; clampPan(); render(); }
    } else {
      goFit();
    }
  }

  img.addEventListener('load', function () {
    nw = img.naturalWidth;
    nh = img.naturalHeight;
    // 图片按原始尺寸布局，缩放全部交给 transform，避免 max-width 与 transform 打架
    img.style.width = nw + 'px';
    img.style.height = nh + 'px';
    goFit();
  });

  img.addEventListener('error', function () {
    hint.textContent = '图片加载失败：签名可能已过期，请让分享者重新生成链接';
    hint.style.opacity = '1';
  });

  // ---- 双击切换 ----
  stage.addEventListener('dblclick', function (e) {
    var r = stage.getBoundingClientRect();
    toggleAt(e.clientX - r.left, e.clientY - r.top);
  });

  zoomBtn.addEventListener('click', function () {
    var r = stageRect();
    toggleAt(r.w / 2, r.h / 2);
  });

  // ---- 滚轮：精细缩放（锚定鼠标），不滚动页面 ----
  stage.addEventListener('wheel', function (e) {
    e.preventDefault();
    if (!nw) return;
    var r = stage.getBoundingClientRect();
    // 触控板给 pixelDelta 较小的值，鼠标给 angleDelta；
    // 统一取绝对值大的那个，再折算成缩放因子
    var d = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    // 每 100 单位约 10% 缩放，手感细腻且不会一跳一大截
    var factor = Math.exp(-d * 0.0012);
    zoomAt(e.clientX - r.left, e.clientY - r.top, scale * factor);
  }, { passive: false });

  // ---- 拖拽平移 ----
  var drag = null;
  stage.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, tx: tx, ty: ty, moved: false };
    stage.classList.add('dragging');
    stage.setPointerCapture(e.pointerId);
  });

  stage.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x;
    var dy = e.clientY - drag.y;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) drag.moved = true;
    tx = drag.tx + dx;
    ty = drag.ty + dy;
    clampPan();
    render();
  });

  function endDrag(e) {
    if (!drag) return;
    stage.classList.remove('dragging');
    try { stage.releasePointerCapture(e.pointerId); } catch (err) {}
    drag = null;
  }
  stage.addEventListener('pointerup', endDrag);
  stage.addEventListener('pointercancel', endDrag);

  // ---- 复制代理链接 ----
  copyBtn.addEventListener('click', function () {
    var url = ${jsRaw};
    function done() {
      var old = copyBtn.textContent;
      copyBtn.textContent = '已复制';
      setTimeout(function () { copyBtn.textContent = old; }, 1400);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(fallback);
    } else {
      fallback();
    }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (err) {
        hint.textContent = '复制失败，请手动复制：' + url;
        hint.style.opacity = '1';
      }
      document.body.removeChild(ta);
    }
  });

  // ---- 窗口变化：适合窗口模式下重新适配 ----
  window.addEventListener('resize', function () {
    var prevFit = fitScale;
    fitScale = computeFit();
    if (mode === 'fit') {
      goFit();
    } else if (Math.abs(scale - prevFit) < 1e-4) {
      // 原本就是适配状态，跟着重算
      goFit();
    } else {
      clampPan();
      render();
    }
  });

  // 防止双击选中文字
  document.addEventListener('selectstart', function (e) { e.preventDefault(); });
})();
</script>
</body></html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      // 页面本身不缓存：撤销必须立即生效；图片字节由 OSS 自己的缓存策略管
      "Cache-Control": "no-store",
    },
  });
}

/**
 * 处理 /s/<token>
 *
 * 两种模式：
 *   默认        → 返回 HTML 看图页，图片走 OSS 直连（快，~95ms）
 *   ?raw=1      → 流式代理图片字节，重写响应头为 inline（慢，但地址栏直接是图片）
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

  const wantRaw = new URL(request.url).searchParams.get("raw") === "1";

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

  // ---- 默认路径：返回 HTML 看图页，图片走 OSS 直连 ----
  // 这是主要路径：访客拿到页面，浏览器用 <img> 拉 OSS（约 95ms），
  // 页面只消耗 1 次 Worker 请求，撤销判定也在这里完成。
  if (!wantRaw) {
    await recordHit(env, token);
    return viewerPage(rec, signedUrl, request.url);
  }

  // ---- 可选路径（?raw=1）：流式代理图片字节 ----
  // 仅用于「希望在地址栏直接看到图片」的场景。国内经 CF 绕路较慢（2~4s）。
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
