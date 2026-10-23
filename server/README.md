# 千寻影集 · 分享服务端（Cloudflare Workers）

配合桌面客户端的轻量服务端，只做三件事：

1. **可撤销的分享短链**——`https://img.agentstack.vip/s/<token>`
2. **图片内联代理**——剥掉 OSS 的强制下载头，让链接在浏览器里直接看图
3. **收藏列表同步**——跨机一致（LWW）

**不做什么**：不管 OSS 凭据（客户端仍直连）、不做在线库列举代理、不做上传代理。

---

## 1. 为什么需要它

### 1.1 OSS 默认域名强制下载（实测确认）

2025 年之后新建的 Bucket，用 **OSS 默认域名**访问图片类对象时，OSS 会强制附加：

```
x-oss-force-download: true
Content-Disposition: attachment
```

触发的 `Content-Type` 包括 `image/jpeg`、`image/png`、`image/webp`、`image/gif`、
`image/svg+xml` 等 13 种。**这是域名级安全策略，与上传时设置什么无关。**

**实测结论（2026-10-23，桶 `xianlin-oss` / `cn-qingdao`）**：

| 方式 | `x-oss-force-download` | `Content-Disposition` | 浏览器行为 |
|---|---|---|---|
| 默认签名 URL | `true` | `attachment` | 下载 |
| 签名 + `response-content-disposition=inline` | `true` | `attachment` | **仍下载** |
| 签名 + `inline; filename=...` | `true` | `attachment` | **仍下载** |
| **经本服务端代理** | **无** | **`inline; filename=...`** | **内联显示** |

> 关键结论：`response-content-disposition` 参数**无法覆盖**强制下载策略。
> 官方给出的解法是「换自定义域名」或「换出口」——本服务端就是那个出口。

### 1.2 现有签名外链不可撤销

`docs/OSS_DEV_MANUAL.md` 早就写明：限时签名链接**无法提前作废**，只能等到期、
删改对象或轮换 AK。本服务端补上了这个缺口：短链本身可随时撤销，撤销后返回 410。

---

## 2. 架构

```
客户端 ──HMAC 签名──▶ img.agentstack.vip (Worker)
                        │
                        ├─ GET  /s/<token>          公开：代理 OSS，重写为 inline
                        ├─ GET  /health             公开：健康检查
                        ├─ POST /api/shares         创建短链
                        ├─ GET  /api/shares         列出分享记录
                        ├─ DELETE /api/shares/<t>   撤销单条
                        ├─ POST /api/shares/revoke-by-key  按图片批量撤销
                        ├─ POST /api/favorites      推送收藏（LWW）
                        └─ GET  /api/favorites      拉取收藏
                        │
                        ├──▶ D1 (shares + favorites)
                        └──▶ OSS (只读 GetObject)
```

---

## 3. 部署

### 3.1 前置条件

- Cloudflare 账号，`agentstack.vip` 已接入且 NS 生效
- `img` 主机名下**没有**既有 CNAME（有就先删）
- 阿里云 OSS 只读 RAM 用户（见 §3.3）

### 3.2 首次部署

```bash
cd server
npm install

# 1) 建 D1 库（若已有可跳过）
npx wrangler d1 create qx-album
#   把返回的 database_id 填进 wrangler.toml

# 2) 建表
npx wrangler d1 execute qx-album --remote --file=./schema.sql

# 3) 写三个 Secret（顺序很重要，见 §5.1）
echo -n "<只读 AK ID>"     | npx wrangler secret put OSS_AK_ID
echo -n "<只读 AK Secret>" | npx wrangler secret put OSS_AK_SECRET
echo -n "<共享密钥>"        | npx wrangler secret put QX_SHARED_SECRET

# 4) 部署（必须在所有 secret 写完之后）
npx wrangler deploy
```

### 3.3 阿里云只读 RAM 用户

服务端只需要 **`oss:GetObject`**，不要给写/删权限。

创建方式（推荐自定义策略精确到单桶）：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject"],
      "Resource": ["acs:oss:*:*:<你的桶名>/*"]
    }
  ]
}
```

也可以挂系统策略 `AliyunOSSReadOnlyAccess`（含 `ListObjects`，能列举全桶文件名）。
本机实际使用后者，因为账号下只有一个桶，风险面差异很小。

**实测该 AK 的权限边界**（2026-10-23）：

| 操作 | 结果 |
|---|---|
| `GetObject` | ✅ 成功 |
| `ListObjects` | ✅ 成功（只读策略含此权限） |
| `PutObject` | ❌ `AccessDenied` |
| `DeleteObject` | ❌ `AccessDenied` |

### 3.4 共享密钥

客户端与服务端共用一把 HMAC 密钥，建议 32 字节随机（base64 后 44 字符）：

```bash
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

- 服务端：`wrangler secret put QX_SHARED_SECRET`
- 客户端：设置对话框「服务端密钥」，用 Windows DPAPI 加密存本机
  （与 OSS Secret 同一套机制，INI 里是 `ENC1:` 开头密文）

---

## 4. 鉴权

除 `/s/*` 与 `/health` 外，所有接口都要签名。

**请求头**：

```
X-QX-Timestamp: 1729584000000        # 毫秒时间戳
X-QX-Signature: <hex>
X-QX-Nonce:     <可选随机串>
```

**签名算法**：

```
canonical = METHOD \n PATH \n TIMESTAMP \n NONCE \n hex(SHA256(body))
signature = hex(HMAC-SHA256(secret, canonical))
```

要点：
- `PATH` **只含路径，不含 query**（`/api/shares`，不是 `/api/shares?limit=5`）
- `body` 为原始字节；GET/HEAD 请求时 body hash 为空串
- 时间窗默认 **300 秒**，超出返回 401（`AUTH_WINDOW` 可调）
- `nonce` 参与签名但不做持久化去重（时间窗已足够防重放；要更强可加 D1 存 nonce）

---

## 5. 运维

### 5.1 ⚠️ Secret 与部署的顺序陷阱

**`wrangler secret put` 会创建新部署，把代码回滚到旧版本。**

实际踩过的坑：先 `deploy` 再 `secret put`，结果运行时读到 `QX_SHARED_SECRET: MISSING`，
接口全部 500 `server_misconfigured`。更隐蔽的是——某次 `secret put` 之后代码变成旧版本，
表现是**短链重新出现强制下载头**（因为旧代码没有响应头重写逻辑）。

**正确做法**：所有 secret 改完后，**最后一次操作必须是 `wrangler deploy`**。

验证方式：

```bash
curl -H 'User-Agent: qx-album/1.0' https://img.agentstack.vip/health
# 期望 env 三项都是 "set"
```

### 5.2 `workers_dev` 必须设为 false

`wrangler.toml` 里 `workers_dev = true` 时，部署最后一步会要求注册 workers.dev 子域，
非交互模式下失败退出——**但脚本其实已经上传了**，造成「报错但半成功」的假象。
绑了自定义域后应设为 `false`。

### 5.3 Cloudflare 会拦没有 UA 的请求

Python `urllib` 默认 UA 会被 Bot Fight 拦成 `error code: 1010`（HTTP 403），
**这不是 Worker 返回的**。客户端与服务端互调时必须带正常 `User-Agent`。

### 5.4 免费额度

| 项 | Free |
|---|---|
| 请求数 | 100,000/日 |
| CPU | 10 ms/请求 |
| D1 行读 | 5,000,000/日 |
| D1 行写 | 100,000/日 |
| D1 存储 | 5 GB（单库 500 MB） |

图片代理**每张图算 1 次请求**。自用场景绰绰有余；若对外分享量大，需要上 Paid（$5/月）。

访问计数每次请求写 1 行——10 万行/日 的上限约等于每天 10 万次图片访问。

### 5.5 轮换密钥

```bash
# 换共享密钥（客户端需同步更新设置）
echo -n "<新密钥>" | npx wrangler secret put QX_SHARED_SECRET
npx wrangler deploy          # ← 必须再 deploy 一次

# 换 OSS 只读 AK（阿里云侧删除旧 AK 后）
echo -n "<新 AK ID>"     | npx wrangler secret put OSS_AK_ID
echo -n "<新 AK Secret>" | npx wrangler secret put OSS_AK_SECRET
npx wrangler deploy
```

---

## 6. 接口示例

### 创建短链

```bash
curl -X POST https://img.agentstack.vip/api/shares \
  -H "Content-Type: application/json" \
  -H "User-Agent: qx-album/1.0" \
  -H "X-QX-Timestamp: <ms>" \
  -H "X-QX-Signature: <hex>" \
  -d '{"oss_key":"qx/xxx.png","note":"备注"}'
```

响应：

```json
{ "ok": true, "token": "wXXLwR2", "url": "https://img.agentstack.vip/s/wXXLwR2" }
```

### 撤销

```bash
curl -X DELETE https://img.agentstack.vip/api/shares/wXXLwR2 \
  -H "User-Agent: qx-album/1.0" -H "X-QX-Timestamp: ..." -H "X-QX-Signature: ..."
```

撤销后访问短链返回 **410**（页面显示「链接已失效」）。

### 隐私说明

短链 `/s/<token>` **不需要鉴权**——拿到链接的人都能看图，这正是分享的含义。
但 token 是 7 位 base62（62^7 ≈ 3.5 万亿），不可枚举。

---

## 7. 数据表

### `shares`

| 字段 | 说明 |
|---|---|
| `token` | 7 位 base62 主键 |
| `oss_key` | 完整对象 key |
| `bucket` | 所属桶 |
| `revoked` | 0 有效 / 1 已撤销 |
| `hits` | 累计访问次数 |
| `first_hit` / `last_hit` | 首次 / 最后访问时间 |

### `favorites`

| 字段 | 说明 |
|---|---|
| `oss_key` | 图片相对路径（跨机标识） |
| `favorite` | 0/1 |
| `updated_at` | LWW 时间戳，大者胜 |

---

## 8. 本地开发

```bash
cd server
npm install
npx wrangler dev        # 本地跑在 http://localhost:8787

# Secret 从 .dev.vars 读（已 gitignore）
cat > .dev.vars <<'EOF'
OSS_AK_ID=...
OSS_AK_SECRET=...
QX_SHARED_SECRET=...
EOF
```

注意本地开发时 `PUBLIC_BASE` 仍是线上地址——若要测完整链路，
把 `wrangler.toml` 的 `PUBLIC_BASE` 临时改成 `http://localhost:8787`。

---

## 9. 已知限制

- **代理每张图 1 次 Worker 请求**：Free 10 万/日，对外分享量大需升级
- **短链不支持相册/多图**：一个 token 一张图
- **撤销不影响已缓存字节**：撤销判定在缓存之外（每次请求都查 D1），
  所以已撤销链接不会复活；但图片字节本身可能仍在 Cloudflare 缓存中——
  这对「撤销分享」无影响（链接已 410），只影响「彻底删除图片」的场景
- **不支持自定义过期时间**：短链长期有效直到手动撤销
