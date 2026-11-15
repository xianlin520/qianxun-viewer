# Brooks-Lint 复审 — 千寻影集 v1.6.5（针对 v1.6.4 审查的核验）

**Mode:** Health Dashboard（复审）
**Scope:** 全项目，基线 `ab9cde1`（v1.6.4）→ 当前 `a9ab154`（v1.6.5 系列，5 个提交）
**Composite Score:** 86/100（基线 72 → +14）
**Date:** 2026-11-15
**对照报告:** [REVIEW_BROOKS_2026-11-15.md](REVIEW_BROOKS_2026-11-15.md)（29 条发现）

| Dimension | Score | 变化 | Top Finding（仍是问题的那一条） |
|-----------|-------|------|--------------------------------|
| Code Quality | — | — | 跳过（无 diff 形态的 PR 审；本轮改动已按文件核验） |
| Architecture | 90 | 75 → 90 | 门面建好了，但 `controllers.current_tier/fast_pixmap` 仍绕过它自拼缓存路径 |
| Tech Debt | 85 | 65 → 85 | 看图页模板的 `replaceAll` 不是函数式替换，文件名可突破 `alt` 属性 |
| Test Quality | 80 | 75 → 80 | 服务端已有 17 条真测试；**客户端 5868 行仍然零测试** |

加权（PR 跳过，权重 0.40 / 0.33 / 0.27）：90×0.40 + 85×0.33 + 80×0.27 = **86**。

---

## 一、我是怎么核的（不是读 diff 猜的）

| 手段 | 结果 |
|---|---|
| `python -m compileall src main.py` | 通过，无语法错误 |
| `python scripts/check_version.py` | 4 处版本号一致（1.6.5） |
| **offscreen 真跑主窗体**（项目 venv + `QT_QPA_PLATFORM=offscreen` + 临时 QSettings/LOCALAPPDATA 隔离） | MainWindow 构造/显示/关闭、五种排序、三档缩略图、收藏切换、查重、移出全部通过 |
| **端到端功能测试**（7 张真实图片 + 一对重复图） | 扫描入库 7 张、磁盘生成 7 个缩略图、查重正确识别 `{dupA, dupB}`、`move_many(3)` **refresh_view 只调用 1 次** |
| **新旧算法对拍**（1200 张 × 4 种阈值 × 2 种重复率） | 分段索引分组结果与旧 O(n²) **完全一致** |
| **性能实测** | `find_groups`：3000 张 2.722s → **0.145s（18.8×）**；20000 张 1.513s |
| **内存实测** `tracemalloc` | `_close_band_values` 缓存在 threshold=12 时涨到 **218.3 MB**（见新问题 N2） |
| **逐项计时** | `FavoritesStore.contains` 首次 **2.91 ms/张**（千张库 2.9 秒）；`cache_root_for` 2000 次仅 6.4 ms |
| **样式模板渲染** | `theme.render_qss` 17 个占位符全部替换，残留 0；`QWidget` 全局块已无 `background` |
| **node 探针**（真实 `html.js` + 真实 `viewer.html`） | 经典载荷 `x" onerror="…` 被正确转义；但 `{{RAW_URL_LITERAL}}` 文件名可突破 `alt`（见 N1） |
| **服务端测试** | `cd server && npm test` → 17 passed / 0 failed，退出码 0（独立复算了 OSS V4 签名链） |

> 一处说明：负责 UI 侧核查的子代理报告"本机没有 PySide6，只能静态推演"。那是它用了系统 Python。我用项目 venv `.venv\Scripts\python.exe` 把应用真跑起来了，所以本轮结论中凡是标"实测"的都来自真实运行，不是代数推演。

---

## 二、29 条发现逐条判定

✅ 已修复 **21**　⚠️ 部分修复 **8**　❌ 未修复 **0**　🆕 新问题 **5**（另有若干已并入对应条目）

| # | Issue | 判定 | 关键证据 |
|---|---|---|---|
| IKVEVN | 看图页 XSS | ✅ | `html.js:24` 转义 `& < > " '` 五字符；`proxy.js:115-119` 全部输出点只走 4 个占位符；探针证明经典载荷无法突破属性 |
| IKVEVO | 透传 Content-Type | ✅ | `proxy.js:230` 只用 `contentTypeFor` 白名单、未命中降 octet-stream；`:233` `nosniff`；`pageHeaders()` 带 nonce CSP |
| IKVEVP | 收藏 LWW 污染 | ✅ | `favorites.js:31-47` `validateItem` 六种脏数据全 reject，写前校验、整批 400；`Number(x) \|\| Date.now()` 已消失 |
| IKVEVQ | list_keys 降级空集合 | ✅ | `oss_service.list_keys` 改为直接抛；`controllers.py:986-989` 捕获后 `status.emit("云端清单获取失败，已中止上传")` 并中止 |
| IKVEVR | 启动查更新阻塞 | ✅ | `main_window.py:434` 走 `AsyncCaller`；`updater` 不再在 UI 线程 |
| IKVEVS | 测试连接阻塞 | ✅ | `settings_dialog.py:108-148`、`oss_dialogs.py:62-82` 全走后台 + 按钮置灰；`oss2` 传 `connect_timeout=5`；`ShareServer` 分级超时 |
| IKVEVT | 批量 N 次刷新 | ✅ | 新增 `move_many` + `_move_pending` 收敛；**实测 3 张移出 refresh_view 仅 1 次** |
| IKVEVU | 每张图两次 resolve | ⚠️ | 根目录已缓存，但**每张图仍做一次 `p.resolve()`：实测 2.91 ms/张，千张库 2.9 秒**。`_item_folder` 的 abspath 方案没被采纳 |
| IKVEVV | cache_root 重算 | ✅ | `lru_cache` + `clear_cache_root_memo`；实测 2000 次 6.4 ms（未缓存时应约 3.8 s） |
| IKVEVW | 查重 O(n²) | ✅ | 四段 16bit 索引 + 鸽巢剪枝；对拍一致、3000 张提速 18.8×。**内存副作用见 N2** |
| IKVEVY | 撤销全部只 500 条 | ✅ | `share_server.list_all_shares` 按 `next_cursor` 翻页（上限 50×200）；`shares_dialog.reload` 改调它 |
| IKVEVZ | 可见范围回落整库 | ✅ | `grid_view.py:258-276` 改用 `page_capacity()` 封顶；视口为 0 时压到 `(0,0)`。下游仍缺防御天花板（并入 IKVEWI 备注） |
| IKVEW0 | 改配置不生效 | ✅ | `_share_srv_key` 存 (base, secret)，变了即重建（`controllers.py:1089-1093`） |
| IKVEW1 | 签名域不含 query | ⚠️ | query 已进签名且两端同步、测试锁住；但 **nonce 仍不落库**（schema 无 `nonce_seen`），且 `ALLOW_LEGACY_SIG` **默认 = 1**，旧签名仍可过，等于 query 篡改那条路留着 |
| IKVEW2 | AUTH_WINDOW fail-open | ✅ | `auth.js:30-34` 非有限值退回 300 而非 NaN；`/health` 报生效值；测试覆盖非法值 |
| IKVEW3 | 短链永不过期 | ⚠️ | `expires_at` 列/迁移/410 全齐，**但唯一调用点 `controllers.py:1107` 不传值**，新短链仍永久；`recordHit` 仍 `await`、`ctx` 已从 `fetch` 签名删除（`index.js:213`），waitUntil 更远了；限流与 /health 缓存一条没做 |
| IKVEW4 | 收藏拉取无游标 | ⚠️ | 服务端已给 `next_cursor`（`favorites.js:79-113`），**客户端 `share_server.pull_favorites` 把游标丢了**，`workers.py:317` 无参调用 → 窗口从 5000 缩到 1000，仍静默丢尾 |
| IKVEW5 | 零测试 + dist 入库 | ✅ | `npm test` 17 passed；`git ls-files server/dist` 为 0 行 |
| IKVEW6 | 加密原语/解析重复 | ✅ | `crypto.js` 收口 6 个原语、两处 import；`parseShortPath` 统一；`signForClient` 已删 |
| IKVEW7 | 长函数 | ✅ | `readJson` 抽出、`ROUTES` 表驱动、`fetch` 只剩 29 行、`viewerPage` 缩到 28 行。残留 `handleShortLink` 约 124 行（并入备注） |
| IKVEWA | 缓存协议四处重复 | ⚠️ | 门面 + `ScaleMode` 枚举 + 三个视图全部收口 ✅；但 `controllers.current_tier`（432）与 `fast_pixmap`（833-842）仍是第 5 份实现，`TIER_LARGE` 与 `THUMB_SIZES` 又是并列常量 |
| IKVEWB | grid resize 无防抖 | ✅ | `grid_view.py:231-239` 50ms 防抖，`geometry_changed.emit` 只剩防抖 timeout 一处 |
| IKVEWC | viewer pixmap / 双击 | ⚠️ | `hideEvent` 已释放 ✅；**小图双击仍无反应**（`_double_click_target` 把 fit 夹到 1.0，两个状态塌成一个，代数可证）；解码取消令牌仍未做，旧图整图解码照跑 |
| IKVEWD | 查重面板置灰/特效 | ✅ | `_mark_processed` 置灰 + 状态文案；`_LazyOpacity` 常态不挂；`_collect_active/_confirm_online` 共用 |
| IKVEWE | 主题两套来源 | ⚠️ | `@KEY@` 模板 + `render_qss` 唯一入口 + 容器化底色全部落实（实测渲染 0 残留）；**`duplicates_dialog.py:94` 仍写死 `#26272b`** |
| IKVEWF | 文档漂移 5 处 | ✅ | 逐条对上实现：favorites v2、24 个 QSettings 键、utils 含 secret、缓存失败改为如实描述、core 可单测范围收窄 |
| IKVEWG | 死代码/重复常量 | ✅ | `formats.py` 统一 `IMAGE_EXTS`、`rel_from_key` 取代字面量切片、`phash.hamming`/`has_cache`/`is_public`/`SHARE_EXPIRES` 全删 |
| IKVEWH | 依赖未锁定 | ✅ | `requirements.lock` 28 行；`package.json` 补 `name/private/scripts`，`wrangler` 改 `~` |
| IKVEWI | 8 处小项 | ⚠️ | 7/8 已完成（`card_size`、`ROLE_INFO`、PagerBar 夹取、cache_dialog `_refresh(extra)`、逐条 try 计数、`ui/input.py` 滚轮量纲、update_dialog 改 `setHtml`）；**`settings.py` 24 组 getter/setter 一字未动**（该文件不在本轮 diff 里，CHANGELOG 也自认） |

---

## 三、本轮修复带进来的 5 个新问题

### N1（P2）占位符替换不是函数式，文件名可突破 `alt` 属性
Symptom `proxy.js:115-119` 用 `replaceAll(串, 字符串)`：JS 会把替换值里的 `$&`/`$'` 当引用，且 `{{NAME}}` 先于 `{{RAW_URL_LITERAL}}` 替换，导致名字里的占位符被二次展开。用真实模板实测三个结果：
- `a$&b.png` → `alt="a{{NAME}}amp;b.png"`（页面上残留字面量 `{{NAME}}`）
- `x{{SIGNED_URL}}.png` → 签名 URL 被塞进可见的 alt 文本
- `x{{RAW_URL_LITERAL}}.png` → `alt="x"https://img…/s/T.png".png"` —— **引号提前闭合，属性被突破**
Source A Philosophy of Software Design — Information Leakage（模板与替换值是两条不共享转义约定的通道）
Consequence 攻击者需要能在共享桶里造出这种对象名并对它建短链，实测注入内容受限于模板静态文本与短链 URL，**没找到执行脚本的路径**，所以不推翻 IKVEVN 的"已修复"；但页面结构被破坏，且这正是原报告 Remedy 里明确要求"用函数式 replace"而未落实的那一步。
Remedy 改成 `.replaceAll("{{NAME}}", () => escapeHtml(name))`，四个占位符全部用函数形式（一行改动）。

### N2（P2）分段索引的邻域缓存可涨到 218 MB
Symptom `duplicates.py` 的 `_close_band_values` 带 `lru_cache(maxsize=8192)`。k 由 `min(3, threshold//4)` 决定：阈值 4（默认）时 k=1，单条 17 个值、可忽略；**阈值调到 12 时 k=3，单条 697 个值**。
Source Release It! — 缓存必须有容量语义；A Philosophy of Software Design — 性能预算
Consequence `tracemalloc` 实测：填满 8192 条后占用 **218.3 MB**，且是全局常驻、无失效时机。客户端刚在 v1.6.4 记录过 108MP 图 1.3GB 峰值的内存红线，这一处会重新把峰值推上去。
Remedy 三种任一：把 `min(3, …)` 的 k 上限与阈值一起夹到 12 以内并给 `maxsize` 降到 512；邻域懒生成（`yield` 而非返回 list）；只缓存 k=1（默认路径）的 17 个值。

### N3（P2，回归）OSS「测试连接」失败提示从人话退回原始异常
Symptom `oss_dialogs.py:74` 有 `from ..core.oss_service import friendly_error  # noqa: F401  (保持文案一致)`，但失败路径 `:80-82` 收的是 `async_call.py:49` 拼的 `f"{type(exc).__name__}: {exc}"`，`friendly_error` 从未被调用。基线是 `f"连接失败：{friendly_error(exc)}"`。
Consequence 用户填错 Endpoint 时看到 `ConnectionError: …` 而不是原来那句"Endpoint 与 Bucket 地域不匹配"。后台化是对的，但顺手丢掉了把 SDK 报错翻成人话的能力；那个死 import 还会让人以为已处理。
Remedy 在 `on_fail` 里对 `job()` 抛出的异常保留原对象（把 `_Signals.failed` 改为传 `object` 而非 str），或让 `job` 自己 try/except 并把 `friendly_error` 结果作为字符串返回。

### N4（P3）AsyncCaller 默认与缩略图/解码共用同一个全局 4 线程池
Symptom `async_call.py:75` 无 `max_threads` 时用 `QThreadPool.globalInstance()`；`controllers.py:100-101` 把同一个 global instance `setMaxThreadCount(4)` 用于 ThumbWorker/DecodeWorker。
Consequence 设置页「测试连接」挂住时（OSS `read_timeout=20`）会占掉 4 个线程里的 1 个，滚动缩略图吞吐下降。`shares_dialog` 用了 `max_threads=1` 私有池所以没事，其他调用点没跟上。
Remedy 让 `AsyncCaller` 默认给 1~2 线程的私有池（网络 I/O 本来不需要并发）。

### N5（P2，文档）`server/README.md` 描述的协议与实现相反，且被兼容开关掩盖
Symptom `README.md:156-161` 仍写 `canonical = METHOD \n PATH \n …` 并强调"`PATH` **只含路径，不含 query**"，与 `auth.js:77-83` 的新协议相反；`:312` 仍写"不支持自定义过期时间：短链长期有效"。
Consequence 照 README 实现的新客户端会签错，却因为 `ALLOW_LEGACY_SIG` 默认 1 而能跑通 —— 直到有人关掉兼容那天集体 401。这是"文档错 + 兼容分支兜底"叠加出的定时炸弹。
Remedy 先改 README，再把 `ALLOW_LEGACY_SIG` 默认改 `"0"`（客户端已全部升级到新协议，测试里也有新签名用例）。

---

## 四、还剩什么（按杠杆排序）

1. **关掉 `ALLOW_LEGACY_SIG` 并同步 README**（N5 + IKVEW1）。这是本轮唯一"看起来修了、实际上留了后门"的地方，改动 2 行。
2. **把 `pull_favorites` 改成游标循环**（IKVEW4）。服务端 `next_cursor` 已经给了，客户端只差十行；不改的话本轮把丢尾窗口从 5000 缩到了 1000，等于把问题变得更隐蔽。
3. **让 `create_share` 真的带默认 `expires_at`**（IKVEW3）。schema、migration、410 都齐了，只差 `controllers.py:1107` 传一个值；不传的话"短链永不过期"这条 P2 事实上没修。
4. **`FavoritesStore._rel` 换成 abspath + 前缀比较**（IKVEVU）。根因（每张图一次 realpath，实测 2.91 ms）还在，千张库仍要 2.9 秒；`_item_folder` 里已经有一模一样的正确写法可以照抄。
5. **给客户端建第一个测试文件**。服务端从 0 到 17 条用例这一步是真的，客户端 5868 行仍是 0。最小可测切口就是本轮新建的 `thumb_cache`/`async_call`/`input`/`duplicates` 这四个纯模块 —— 它们恰好都不依赖 QWidget。

## 五、总体判断

**这一轮的修复是真实的，不是把字面量换个位置。** 三条最硬的证据：① 两条可被真实利用的 XSS 在代码层面确实关了，我用真实模板跑过攻击载荷；② 查重索引与旧算法对拍 1200×8 组结果完全一致，3000 张提速 18.8 倍；③ `move_many` 的批量收敛在真跑的应用里实测 refresh_view 从 N 次降到 1 次。

**剩下的问题集中在"改了一半就收工"**：签名域加了 query 但没关兼容、过期机制做了但没人传值、收藏游标服务端做了但客户端丢了、缓存门面建了但控制器还在自己拼路径、主题模板做了但还剩一处裸色值。这五处都属于"机制已就位、最后一根线没接上"，成本很低、收益立刻可见（尤其前三条是安全性/正确性的实质缺口）。

从 72 到 86 的跃迁主要来自三件横向共享件的落地（`async_call`、`thumb_cache`、`input` + qss 模板），它们同时消掉了原报告里 R2/R3 的大半条目 —— 这也验证了原报告"最高杠杆不是继续修 bug，而是抽共享件"的判断。
