# 在线图片查看设计（阿里云 OSS 方案）

千寻图片查看器 v1.3.0+ · 版权所有 © 羡林i (Y_XianLin)

## 1. 选型结论

**阿里云 OSS · 标准存储（Standard）· 私有读写 Bucket · IMG 图片处理 · 签名 URL ·（可选）CDN**

- 标准存储：原图随时按需取用；低频/归档有取回费与解冻延迟，不适合"常浏览、偶尔原图"。
- 私有 + 签名 URL：私密集合；限时签名 = 天然"限时外链"，无需公网 IP/映射。
- IMG URL 参数缩略图：`?x-oss-process=image/resize,w_512/format,webp`，浏览流量降约 99%，不存第二份。
- 成本量级（60GB）：存储 ≈ 7.2 元/月；缩略图流量 ≈ 几元/月；原图按量 0.5 元/GB（CDN 后 ≈0.24）；合计约 10~30 元/月，不看不花钱。

## 2. 架构

```
千寻查看器 ──oss2──▶ OSS 私有 Bucket(标准, IMG)
  │ P1 上传:  批量/增量(resumable, sha1 索引跳过已传)
  │ P2 浏览:  在线库模式 = 列对象 + image/info 取宽高
  │           缩略图 = 签名URL(process resize) 下载到本地 .qx_cache → 复用图片墙/分页/大图
  │           原图   = 签名URL 按需下载到本地临时 → 复用 DecodeWorker
  │ P3 分享:  右键"复制外链" = ≤7天签名URL；"复制永久链接" = 单对象公共读直链（可撤回）
  └ 索引: %LOCALAPPDATA%/QianXunViewer/oss_index.json (relpath→key/size/mtime)
安全: AK/SK 仅存本机 QSettings(INI, 用户目录)；签名过期≤7天；可选 RAM 子账号最小权限
```

## 3. 关键决策

1. **在线项建模**：`ImageItem.remote_key` 非空即为在线项；`path` 用 key 的伪路径，本地缓存命名沿用 `sha1(path|size|mtime)`，UI 层零改动。
2. **在线库列举**：整个 Bucket 递归列举（任意文件夹下的图片均纳入，跳过目录占位与非图片对象）；上传仍用 `qx/` 前缀与用户自有目录区分。
3. **缩略图策略**：在线缩略图不本地生成，直接下载 OSS IMG 处理结果（256/512 两档 resize+format,jpg），落入同一 `.qx_cache`，幂等缓存复用。
4. **宽高获取**：列对象后并发（8 线程）请求 `x-oss-process=image/info` 取宽高，保证图片墙 justified 布局质量。
5. **模式切换**：「在线库」为互斥模式；切回即恢复本地 main_root 扫描。在线模式下上传/移出等本地操作禁用，仅浏览/分享/收藏内存态。
6. **增量上传**：索引以 `sha1(绝对路径|大小|mtime)` 为键；命中即跳过；索引缺失时 head_object 兑底。

## 4. 分期

- **P1 上传管道**：工具栏「上传到云」对话框（配置/测试连接/批量增量上传/进度）。
- **P2 在线库**：工具栏「在线库」开关；列表/缩略图/大图全链路走签名 URL。
- **P3 分享**：双模式——「复制外链」限时签名（本地项未上传则提示先上传；在线项直接签名 ≤7 天）；「复制永久链接」仅将该对象设公共读（桶保持私有）得永久直链，另提供「撤回永久公开」恢复私有。

## 5. 依赖与配置

- 新增运行依赖 `oss2`。
- 设置项：`oss_endpoint / oss_bucket / oss_ak_id / oss_ak_secret`（存用户目录 INI，仅本机）。

## 6. 验证策略

- 无凭据阶段：本地 Fake OSS（内存/临时目录后端）跑通 upload/list/sign/download 与控制器链路。✅ 已完成（冒烟 11/11）。
- 有凭据阶段：真实 Bucket 端到端（上传 10 张→在线浏览→外链打开）。✅ 2026-09-03 联调 10/10 通过（连接/上传/列表+image_info/IMG缩略图URL/原图外链/在线库浏览/缩略图缓存/大图解码/分享链接/清理）。

## 7. 状态

- v1.3.0 为测试版：P1/P2/P3 代码完成并 Fake 验证；仅本地提交，不推送 Gitee、不发发行版。
- API 用法对齐官方文档：`sign_url(params=x-oss-process)`、`get_object_to_file(process=…)`、`resumable_upload`、`image/info` 取宽高。
