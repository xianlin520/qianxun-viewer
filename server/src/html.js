/**
 * HTML 输出转义。
 *
 * 服务端所有拼进 HTML 的动态值都必须经过这里。此前 viewerPage 直接把
 * oss_key 的 basename 拼进模板，`x.png" onerror="alert(1)` 这样的对象名
 * 就能在分享域名上执行脚本。
 *
 * 三种上下文分开处理，不要混用：
 *   escapeHtml  文本节点（<title> 内文、<span> 内文）
 *   escapeAttr  标签属性值（src / href / alt）
 *   jsonLiteral 内联 <script> 里的 JS 字符串字面量（带引号）
 */

const HTML_ENTITIES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** 文本节点与属性值都可用；属性场景下引号也一并转义 */
export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => HTML_ENTITIES[c]);
}

/** 属性值专用，语义上强调"值会被放进引号里" */
export function escapeAttr(value) {
  return escapeHtml(value);
}

/**
 * 生成可直接嵌入 <script> 的 JS 字符串字面量（含首尾双引号）。
 *
 * JSON.stringify 不处理 `</script>`，内联脚本里出现它会提前闭合标签。
 * 这里把 < > & 转成 Unicode 转义，脚本解析结果不变，但 HTML 词法上安全。
 */
export function jsonLiteral(value) {
  return JSON.stringify(String(value ?? ""))
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

/**
 * 图片后缀白名单。
 *
 * 后缀会进入 URL 路径和 JS 字符串，必须严格限定字符集，
 * 否则 `a.png</script>...` 这类对象名会污染代理链接。
 *
 * 没有点号就直接用兜底值：此前把整段 `noext` 当成后缀返回，
 * 虽然只是进了 Content-Type 兜底分支，但语义上是错的。
 */
export function safeExt(ossKey, fallback = "jpg") {
  const s = String(ossKey || "");
  const dot = s.lastIndexOf(".");
  if (dot < 0) return fallback;
  const ext = s.slice(dot + 1).toLowerCase();
  if (!ext) return fallback;
  return /^[a-z0-9]{1,8}$/.test(ext) ? ext : fallback;
}
