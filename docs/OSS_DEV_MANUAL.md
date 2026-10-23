# 千寻影集 · OSS 开发手册

> 阿里云 OSS 在本项目中的接入方式、接口用法、上传/下载链路、分享链接与链接失效机制。
> 适用于二次开发、运维排查与功能扩展。版本 v1.6.0 · 版权所有 © 羡林i (Y_XianLin)

## 目录

0. [凭据与配置位置](#0-凭据与配置位置)
1. [客户端构造与签名版本](#1-客户端构造与签名版本)
2. [对象命名与桶内布局](#2-对象命名与桶内布局)
3. [接口清单](#3-接口清单)
4. [上传（上行）](#4-上传上行)
5. [下载与缩略图（下行）](#5-下载与缩略图下行)
6. [分享链接](#6-分享链接)
7. [链接失效机制](#7-链接失效机制)
8. [权限（RAM 策略）](#8-权限ram-策略)
9. [性能实测与调优](#9-性能实测与调优)
10. [常见报错对照](#10-常见报错对照)
11. [代码索引](#11-代码索引)
12. [验证清单](#12-验证清单)

---

## 0. 凭据与配置位置

本机凭据（含 AccessKey Secret）在 **`.secrets/oss_credentials.local.md`**（该目录已被 `.gitignore` 排除，不入库）。
本手册及 `docs/` 下所有文档**只出现不需要保密的字段**（地域、Endpoint、Bucket、AK ID），Secret 一律以文件指引代替——`docs/` 会随代码推送到公开仓库，Secret 一旦推送无法撤回。

| 项 | 值 |
|---|---|
| 地域 ID | `cn-qingdao`（华北1 · 青岛） |
| Endpoint（外网） | `https://oss-cn-qingdao.aliyuncs.com` |
| Bucket | `xianlin-oss` |
| AccessKey ID | `LTAI5tAorMuAiWN7dc1qCAcM` |
| AccessKey Secret | 见 `.secrets/oss_credentials.local.md` |
| 桶 ACL / 阻止公共访问 | `private` / **开启**（永久直链不可用，限时签名外链可用） |

**程序侧的配置落点**（与 SDK 无关，纯桌面端约定）：

| 内容 | 路径 | 说明 |
|---|---|---|
| 程序设置 | `%APPDATA%\QianXun\QianXunViewer.ini` | `oss_endpoint / oss_bucket / oss_ak_id / oss_ak_secret`；**Secret 为 `ENC1:` 开头的 DPAPI 密文**（绑定当前 Windows 账户） |
| 上传索引 | `%LOCALAPPDATA%\QianXunViewer\oss_index_<bucket>.json` | 键 = `sha1(路径|大小|mtime)`，值 = `{key,size,mtime,at}`；**按桶分文件**，换桶自动隔离 |
| 缩略图缓存 | `%LOCALAPPDATA%\QianXunViewer\cache\<root哈希>\<256/512>\<sha1>.jpg` | 在线库按 `oss@<bucket>` 建根 |
| 原图临时目录 | `%LOCALAPPDATA%\QianXunViewer\originals\` | 大图查看时按需下载 |

读写设置统一走 `src/core/settings.py` 的 `AppSettings`（构造即自动迁移历史明文 Secret 为密文）：

```python
from src.core.settings import AppSettings
st = AppSettings()
st.oss_endpoint = "https://oss-cn-qingdao.aliyuncs.com"
st.oss_bucket = "xianlin-oss"
st.oss_ak_id = "LTAI5tAorMuAiWN7dc1qCAcM"
st.oss_ak_secret = "<见 .secrets/oss_credentials.local.md>"   # 写入即 DPAPI 加密
st.sync()
```

## 1. 客户端构造与签名版本

**结论：新桶必须 V4 签名。** 阿里云自 2025-09-01 起新建的 Bucket 不再接受 V1 签名（旧桶 V1/V4 均可）。本项目按 Endpoint 自动推导地域并使用 V4；推导不出（自定义域名/加速域名）才退回 V1。

```python
import oss2

def oss_region(endpoint: str) -> str:          # 本项目实现，见 src/core/oss_service.py
    """oss-cn-qingdao.aliyuncs.com -> cn-qingdao；推导不出返回空串"""
    host = endpoint.strip().split("//")[-1].split("/")[0].lower()
    if not host.endswith("aliyuncs.com"):
        return ""
    seg = host.split(".")[0]
    if not seg.startswith("oss-"):
        return ""
    region = seg[len("oss-"):]
    for suffix in ("-internal", "-vpc", "-intranet"):
        if region.endswith(suffix):
            region = region[: -len(suffix)]
    return "" if region.startswith("accelerate") else region

region = oss_region("https://oss-cn-qingdao.aliyuncs.com")   # -> cn-qingdao
auth = oss2.AuthV4("AK_ID", "AK_SECRET")                      # V4（推荐）
bucket = oss2.Bucket(auth, "https://oss-cn-qingdao.aliyuncs.com", "xianlin-oss", region=region)
```

要点：
- `region` 参数**只有 V4 需要**，且不可为 `None`（否则 `ClientError: The region should not be None in signature version 4.`）。
- 依赖下限 `oss2>=2.18.4`（Python SDK 的 V4 支持下限）。
- 传输加速域名 `oss-accelerate.aliyuncs.com` 推导不出地域 → 本项目退回 V1，**因此新桶不要用加速域名**（除非自行传入 region）。
- 内网访问用 `oss-cn-qingdao-internal.aliyuncs.com`（同地域 ECS 才可用，不计外网流量费）。

## 2. 对象命名与桶内布局

- 所有上传对象统一走前缀 **`qx/`** + 相对本库根目录的路径：`qx/子目录/文件名.jpg`（`OssIndex.make_key(rel)` = `"qx/" + Path(rel).as_posix()`）。
- 与用户手工放进桶里的其它文件天然隔离；在线库列举时会递归整个桶（不做前缀过滤）。
- 文件名含特殊字符（空格、`$`、`%`、`{}`、`(1)` 等）无需处理：SDK 会自动编码，签名 URL 用 `slash_safe=True` 保留路径分隔符。
- 列举时会跳过目录占位对象（`key.endswith("/")`）与非 `IMAGE_EXTS` 后缀。

## 3. 接口清单

`src/core/oss_service.py::OssLibrary`（全部走同一个 `self.bucket`）：

| 方法 | OSS 动作 | 用途 | 备注 |
|---|---|---|---|
| `test()` | `GetBucketInfo` | 「测试连接」返回桶名 | 需 `oss:GetBucketInfo` |
| `head(key)` | `HeadObject` | 判断对象是否存在 | 异常吞掉返回 False |
| `list_keys()` | `ListObjects`（迭代） | 上传前去重 | 异常吞掉返回空集（降级） |
| `list_images(max_workers)` | `ListObjects` + 并发 `image/info` | 在线库列举（key/size/mtime/宽/高） | 宽高失败置 0 |
| `sign(key, expires, thumb)` | 客户端签名 | 限时外链 / 缩略图外链 | 不产生请求 |
| `public_url(key)` | 纯拼接 | 对象公共读后的永久直链 | 需先 `make_public` |
| `make_public(key)` | `PutObjectAcl` | 单对象设公共读 | 需关闭「阻止公共访问」 |
| `revoke_public(key)` | `PutObjectAcl` | 撤回公共读（恢复继承桶权限） | 永久链接立即失效 |
| `is_public(key)` | `GetObjectAcl` | 查询对象是否公共读 | |
| `delete_object(key)` | `DeleteObject` | 云端删除（在线去重/移出） | 不可逆 |
| `download_to(key, dest, thumb)` | `GetObject[ToFile]` | 下载原图或 IMG 处理结果 | `process` 参数 |
| `upload(local, key, cb)` | `MultipartUpload` | 分片上传（8MB × 2 线程） | 大文件自动分片 |

## 4. 上传（上行）

**单文件（本项目实现）** —— `resumable_upload`，分片 8MB、每文件 2 线程：

```python
oss2.resumable_upload(bucket, "qx/sub/pic.jpg", r"D:\pics\sub\pic.jpg",
                      part_size=8 * 1024 * 1024, num_threads=2,
                      progress_callback=cb)
```

**批量（本项目实现）** —— `UploadWorker` 用线程池跑多文件，并发数 = 设置项「上传并发线程」（`upload_threads`，1–8，默认 4）；每个 worker 内部再 2 线程分片，故峰值连接数 ≈ `upload_threads × 2`。

**三层跳过（增量上传）**，命中任一即跳过：
1. 本地索引命中：`OssIndex.get(sha1(路径|大小|mtime))`；
2. 云端已存在：启动时一次 `list_keys()`，比对 `qx/<相对路径>`；
3. 批内同内容：`size + pHash` 相同（设置项「同内容跳过」开启时）。

上传成功后立即 `index.put(ck, key, size, mtime); index.save()`，因此中断续传不会重传已完成项。

**简单上传**（小文件、脚本场景）：`bucket.put_object(key, file_obj)` —— 注意 **oss2 不接受 `Path` 对象**，要传 `open(path,"rb")` 的文件句柄或 bytes。

## 5. 下载与缩略图（下行）

**原图**：`bucket.get_object_to_file(key, dest)`（大图查看时按需下载到 `originals/`）。

**缩略图**：不落第二份原图，直接让 OSS 服务器端处理，下载结果入本地缓存：

```python
# 本项目封装：thumb=256 / 512
bucket.get_object_to_file(key, dest,
                          process="image/resize,m_lfit,w_256,h_256/format,jpg")
```

- 处理串常量：`image/resize,m_lfit,w_{N},h_{N}/format,jpg`（等比缩放到 N 内 + 转 JPEG）。
- 宽高获取：`bucket.get_object(key, params={"x-oss-process": "image/info"})` 读 `ImageWidth/ImageHeight`。
- 并发：在线库预热最多 **8** 个并发下载（`controller._pump_warm`，可见区高优先插队）。
- 缓存键：`sha1(path|size|mtime)`，同图同档只下一次；离线也能浏览已缓存部分。

**签名 URL 形式的缩略图**（给外部用）：`lib.sign(key, expires, thumb=256)`，URL 形如
`https://xianlin-oss.oss-cn-qingdao.aliyuncs.com/qx/a.jpg?x-oss-process=image%2Fresize...&x-oss-date=20261014T030000Z&x-oss-expires=3600&x-oss-signature=...`。

## 6. 分享链接

两种模式（程序右键菜单：「复制外链（限时签名）」「复制永久链接（对象公共读）」「撤回永久公开」）。

### 6.1 临时链接（限时签名）

```python
url = lib.sign("qx/a.jpg", expires=settings.share_days * 24 * 3600)   # 1~7 天
url_thumb = lib.sign("qx/a.jpg", 3600, thumb=256)                     # 带 IMG 处理
```

- 客户端本地计算签名，**不产生服务端状态**；`expires` 秒后自然失效。
- 程序侧上限 7 天（`SHARE_EXPIRES = 7*24*3600`），由设置项「外链有效期」控制。
- 任何人（含匿名）在有效期内持有 URL 即可访问，**桶保持私有**。
- 分享本地未上传的图：`resolve_cloud_key` 三级解析（`remote_key → 本地索引 → 云端清单匹配并补登索引`），确实没有则弹窗询问「是否立即上传」。

### 6.2 长期链接（永久直链）

思路：桶保持私有，只把**单个对象**设为公共读，得到不过期的直链。

```python
lib.make_public("qx/a.jpg")        # PutObjectAcl -> public-read
url = lib.public_url("qx/a.jpg")   # https://xianlin-oss.oss-cn-qingdao.aliyuncs.com/qx/a.jpg
lib.revoke_public("qx/a.jpg")      # 恢复继承桶权限 -> 匿名访问立即 403
```

**前提（重点）**：Bucket 必须关闭「阻止公共访问」（OSS 全局 + Bucket 两处都要关），否则报
`AccessDenied: Put public object acl is not allowed` —— 新建桶默认开启该开关。程序识别此错误后会弹窗说明并询问是否改用限时签名外链。

其它可选方案：
- **桶级公共读**：整桶直接可匿名访问（`bucket.put_bucket_acl(oss2.BUCKET_ACL_PUBLIC_READ)`），改动面大，一般不建议；
- **CDN + 自定义域名**：回源私有 + URL 鉴权，成本低、可统计、支持刷新缓存（要备案域名）；
- **STS 临时凭证**：给第三方短期读写权限（分钟~小时级），细粒度、可收回。

### 6.3 两种链接对比

| | 限时签名外链 | 永久直链（对象公共读） |
|---|---|---|
| 有效期 | ≤7 天（可设 1–7） | 不过期 |
| 桶状态 | 私有 | 私有（仅该对象公共读） |
| 匿名可访问 | 是（携带签名） | 是 |
| 可撤回 | 否（无服务端状态，靠到期） | **是**（`revoke_public` 立即失效） |
| 前提 | 无 | 关闭「阻止公共访问」 |
| 泄露风险 | 到期自愈 | 必须手动撤回 |

## 7. 链接失效机制

四种可用手段，按影响面从小到大：

| 手段 | 做法 | 生效范围 | 是否可逆 |
|---|---|---|---|
| ① 到期自动失效 | 签名时给 `expires`（本项目 1–7 天） | 单条签名链接 | — |
| ② 撤回对象公共读 | `lib.revoke_public(key)`（程序内「撤回永久公开」） | 该对象的永久直链 | 可再 `make_public` 恢复 |
| ③ 删除/替换对象 | `lib.delete_object(key)` 或改名后重传（源对象删除） | 所有指向该 key 的链接（含签名与永久）→ 404 | 不可逆 |
| ④ 轮换 AccessKey | 控制台禁用旧 AK 并新建 | **该账号所有签名链接**立即失效（永久直链不受影响，它是匿名的） | 需重配程序与其它调用方 |

**关键限制（务必知道）**：OSS 的签名 URL 是**无状态**的，没有「吊销单条签名链接」的服务端接口。要精确作废某一条限时链接，只能：
1. 把有效期设短（本项目的默认思路），到期自愈；或
2. 删除/改名该对象（③，会影响所有持有者）；或
3. 轮换 AK（④，影响面最大）；或
4. 换用带状态的方案：**自建短链跳转服务（已实现，见 §7.1）**、CDN URL 鉴权 + 刷新、STS 凭证。

**程序内现状**：
- 永久链接有「撤回永久公开」（②）；
- 限时签名链接靠到期（①）；
- **可撤销短链已实现**：见 §7.1 与 [server/README.md](../server/README.md)。

### 7.1 可撤销分享短链（已实现）

原计划的「`share_log` + 本地作废」方案已被更彻底的服务端方案取代。

**架构**：Cloudflare Workers 服务端（`server/`），承担两件事——剥掉 OSS 强制下载头
让图片内联展示，以及让分享链接可随时撤销。

**分享链路**：

```
客户端右键「复制分享短链」
  → POST /api/shares {oss_key}
  → 返回 https://img.agentstack.vip/s/<token>
  → 访问：Worker 查 D1 确认未撤销 → 签名取 OSS → 重写响应头为 inline → 流式返回
  → 撤销后：返回 410 已失效
```

**为什么必须服务端而不是本地记日志**：

1. **强制下载无法用参数绕过**：实测 `response-content-disposition=inline` 对
   OSS 默认域名**完全无效**（响应仍是 `attachment` + `x-oss-force-download: true`），
   只能换出口；代理是不需要 ICP 备案的那条路。
2. **撤销必须即时生效**：签名 URL 无状态，一旦发出就自带有效期，本地删日志
   作废不了已发出的链接；只有服务端掌握判定入口才能真正撤销。

**技术要点**：
- 撤销判定放 **D1 而非 KV**：KV 跨地域最多 60 秒可见（删除同样），
  `cacheTtl` 最小 30 秒，无法满足「撤销立即生效」；D1 不开 read replication
  时所有读写走单一主库，读己之写成立。
- 代理每张图消耗 1 次 Worker 请求（Free 10 万/日）。
- OSS 只需只读 AK（实测 `GetObject`/`ListObjects` 通过，`PutObject`/`DeleteObject` 均 403）。

详见 [server/README.md](../server/README.md)。

**可选扩展**：客户端「分享记录」对话框列出历史短链与访问次数，支持单条/按图批量撤销。
接口已具备（`GET /api/shares`、`DELETE /api/shares/<t>`、`POST /api/shares/revoke-by-key`），
UI 尚未接入。

## 8. 权限（RAM 策略）

实测最小集（自定义策略，资源名按桶替换）：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "oss:ListObjects", "oss:GetBucketInfo", "oss:GetBucketAcl",
        "oss:GetObject", "oss:GetObjectAcl", "oss:PutObject",
        "oss:PutObjectAcl", "oss:DeleteObject", "oss:AbortMultipartUpload"
      ],
      "Resource": ["acs:oss:*:*:xianlin-oss", "acs:oss:*:*:xianlin-oss/*"]
    }
  ]
}
```

省事可挂系统策略 `AliyunOSSFullAccess`（当前 RAM 用户即此）。
若还要让程序能开关「阻止公共访问」，另需 `oss:GetBucketPublicAccessBlock` / `oss:PutBucketPublicAccessBlock`。

## 9. 性能实测与调优

实测（2026-10-14，cn-qingdao，与另一路上传并行，数值偏保守）：

| 场景 | 实测 |
|---|---|
| 上传 · 单次整传 16 MB | 2.96 MB/s（≈24.8 Mbps） |
| 上传 · resumable 8MB 分片 × 2 线程 | 3.93 MB/s（≈32.9 Mbps） |
| 上传 · 4 文件并发 | 3.78 MB/s（≈31.7 Mbps，无增益） |
| 下载 · 原图 19 MB | 7.74 MB/s（≈64.9 Mbps） |
| 缩略图 IMG 256 · 首次 / 命中 | ≈0.55 s / ≈0.03 s |
| 缩略图 · 8 并发 24 张 | 2.03 s ≈ 11.8 张/秒 |

结论与调优：
- 瓶颈是**本地宽带上行**（≈32 Mbps ≈ 4 MB/s）：调大 `upload_threads` 收益很小；20 MB/张 ≈ 5 秒/张。
- 官方文档只给**账号/地域级上限**（外网带宽、QPS）：如 `OSS使用限制及性能指标` —— 账号总 QPS 10000、顺序读写 2000、单文件上传下载 QPS ≤2000 且峰值带宽 ≤10 Gbps；超限流控，响应头 `x-oss-qos-delay-time`。**没有单客户端速率承诺**。
- 需要限速保护其它应用时，请求带 `x-oss-traffic-limit`（819200–838860800 bit/s）。
- 跨地域/远距离可换传输加速域名（但本项目新桶需 V4，加速域名推导不出 region，需自行传参）。
- 大量文件避免顺序前缀命名造成分区热点（本项目用库内相对路径，天然较分散）。

## 10. 常见报错对照

| 报错 | 含义 | 处置 |
|---|---|---|
| `V1 signature is forbidden` | 桶不接受 V1 签名（2025-09-01 后新建） | 用 V4：`AuthV4` + `region=` |
| `The region should not be None in signature version 4.` | V4 未传 region | `Bucket(..., region="cn-qingdao")` |
| `AccessDenied: The bucket you access does not belong to you.` | 地域不匹配，或缺 `ListObjects`/`GetBucketInfo` | 核对 Endpoint 地域；补齐 RAM 权限 |
| `AccessDenied: You have no right to access this object because of bucket acl.` | 对象级 action 缺失（如 `DeleteObject`） | 补 RAM 权限 |
| `AccessDenied: Put public object acl is not allowed` | 桶开启了「阻止公共访问」 | 关闭全局 + Bucket 两处开关，或改用签名外链 |
| `NoSuchBucket` | 桶名不存在/拼错 | 核对桶名与地域 |
| `SignatureDoesNotMatch` / `InvalidAccessKeyId` | SK 错误 / AK 不存在或被禁用 | 核对凭据 |
| `BadRequest: Input image file may be corrupted.` / `This image format is not supported.` | 对非图片对象用了 `x-oss-process` | 仅对真实图片加 IMG 处理参数 |
| `PermissionError: [WinError 5] ... dist\QianXunViewer.exe` | 重新打包时旧实例仍占用（onefile 有父子两个进程） | `Get-Process QianXunViewer \| Stop-Process -Force` 后再打包 |

## 11. 代码索引

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `src/core/oss_service.py` | OSS 封装、索引、错误翻译 | `OssLibrary` / `OssIndex` / `oss_region` / `friendly_error` / `is_block_public_error` |
| `src/core/settings.py` | 配置持久化（DPAPI） | `AppSettings.oss_*` / `share_days` / `upload_threads` |
| `src/controllers.py` | 业务编排 | `oss_configured` `build_oss` `_sync_oss_index` `set_online` `create_upload_worker` `resolve_cloud_key` `share_link` `revoke_share` `upload_one` `remove_online_items` |
| `src/workers/workers.py` | 后台线程 | `ListWorker` `UploadWorker` `OnlineDeleteWorker` `HashWorker`（在线补 pHash） |
| `src/ui/oss_dialogs.py` | 配置/上传对话框 | `OssConfigDialog._test` / `UploadDialog._start` |
| `src/ui/main_window.py` | 菜单与交互 | `_copy_share_link`（含阻止公共访问降级）/ `_revoke_share` |

## 12. 验证清单

改完 OSS 相关代码后按此跑一遍（真实桶，注意只操作自己创建的 key）：

```python
lib = OssLibrary(EP, BUCKET, AK_ID, AK_SECRET)
lib.test()                                   # 1 连接（应回桶名）
lib.list_images()                            # 2 列举 + image/info 取宽高
lib.upload(Path("test.jpg"), "qx/_probe.jpg")# 3 分片上传
lib.head("qx/_probe.jpg")                    # 4 存在性
requests.get(lib.sign("qx/_probe.jpg", 300)).status_code          # 5 签名外链 -> 200
requests.get(lib.sign("qx/_probe.jpg", 300, thumb=256)).status_code  # 6 缩略图签名 -> 200
lib.make_public("qx/_probe.jpg"); lib.is_public("qx/_probe.jpg")  # 7 公共读（需关闭阻止公共访问）
lib.revoke_public("qx/_probe.jpg")           # 8 撤回 -> 匿名 403
lib.delete_object("qx/_probe.jpg")           # 9 删除（**只删自建 key**）
```

> 清理铁律：**只删自己创建时记录下的 key**。不要用「枚举整桶再删除」的写法清理测试数据（本项目曾因此误删 161 个真实对象，OSS 删除不可逆）。
