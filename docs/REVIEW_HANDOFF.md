# 审查交接说明

给接手全量审查的智能体看。读完这份再动代码，能省掉大量重复排查。

最后更新：2026-11-15　对应版本 v1.6.4（commit `ab9cde1`）

---

## 一、项目速览

| 项 | 值 |
|---|---|
| 名称 | 千寻影集 QianXun Album |
| 类型 | Windows 桌面图片查看器 |
| 客户端 | Python 3.12 + PySide6 6.11.2 |
| 服务端 | Cloudflare Workers + D1（JavaScript，可选部署） |
| 版本 | v1.6.4 |
| 提交数 | 47 |
| 标签数 | 15（v1.4.0 至 v1.6.4） |
| Python 代码 | 35 个文件，5980 行 |
| 服务端代码 | 6 个文件，1194 行 |
| 测试 | **仓库内没有测试套件** |

---

## 二、本地位置

```
E:\QoderWork\qianxun-viewer
```

虚拟环境：

```
E:\QoderWork\qianxun-viewer\.venv\Scripts\python.exe
```

已装 PySide6 6.11.2、Pillow 12.3.0、numpy 2.5.2、oss2 2.19.1。直接用这个解释器，不要新建环境。

根目录结构：

```
main.py                 入口（单实例保护）
requirements.txt        运行与打包依赖
QianXunViewer.spec      PyInstaller 配置
build.bat               onefile 打包
build-onedir.bat        onedir 打包
assets/                 logo.png / icon.ico
docs/                   用户指南 / 架构 / 变更日志 / 截图 / 本文档
server/                 Cloudflare Workers 服务端
src/                    客户端源码
```

---

## 三、仓库与访问

### 3.1 仓库信息

```
https://gitee.com/qianxun-cloud/qianxun-viewer
```

组织「千寻云」（`qianxun-cloud`），所有者 `xianlin-i`，公开仓库，默认分支 `main`。

### 3.2 注意：本地 origin 是旧地址

```
origin  https://gitee.com/xianlin-i/qianxun-viewer.git
```

仓库迁到组织后旧地址仍在重定向，`git ls-remote origin` 能正常返回。但推送和 API 调用一律用新地址 `qianxun-cloud/qianxun-viewer`，不要依赖重定向。

### 3.3 三种调用方式

**方式一：MCP 工具（推荐，已授权）**

本会话已挂载 Gitee MCP，工具前缀 `mcp__gitee__*`。审查用这几个就够：

```
mcp__gitee__list_releases          列发布版本
mcp__gitee__get_repo_issue_detail  看 issue
mcp__gitee__list_repo_pulls        看 PR
mcp__gitee__get_file_content       读仓库里的文件
mcp__gitee__compare_branches_tags  对比版本
```

调用时 `owner` 填 `qianxun-cloud`，`repo` 填 `qianxun-viewer`。

**方式二：git 命令行**

只读操作（`git log`、`git diff`、`git show`）不需要凭据，直接用。

需要推送时，token 在 `.secrets/gitee_token.txt`。**审查阶段用不到，不要读它，更不要打印。**

**方式三：REST API**

```
GET https://gitee.com/api/v5/repos/qianxun-cloud/qianxun-viewer/releases
```

公开仓库的读接口不需要鉴权。写接口要 `Authorization: token <token>`，同样只在发布流程用。

### 3.4 当前状态

```
ab9cde1  feat: 看图页加作者/手机适配/代理链接带后缀 v1.6.4
```

提交历史与远端 `main` 一致。工作区只有一个未跟踪文件，就是本文档，不在审查范围内。

四处的版本号一致，可直接当基线：`src/meta.py`、`docs/CHANGELOG.md` 顶部、`README.md` 徽标、最新标签 `v1.6.4`。

---

## 四、审查范围

### 4.1 客户端 `src/`（主要工作量）

按文件大小排优先级，大文件问题密度通常更高：

| 文件 | 行数 | 内容 |
|---|---|---|
| `src/controllers.py` | 1216 | 加载/排序/分页/筛选/缩略图调度/操作分发 |
| `src/ui/main_window.py` | 838 | 主窗体、工具栏、菜单、快捷键 |
| `src/ui/wall_view.py` | 373 | 图片墙自绘与 justified 布局 |
| `src/workers/workers.py` | 370 | 五类工作线程 |
| `src/core/oss_service.py` | 294 | OSS 上传/列举/签名 |
| `src/ui/grid_view.py` | 272 | 分页视图与 Delegate |
| `src/ui/shares_dialog.py` | 269 | 分享记录对话框 |
| `src/core/settings.py` | 239 | 配置与 DPAPI |
| `src/ui/viewer.py` | 226 | 大图浏览器 |
| `src/ui/duplicates_dialog.py` | 219 | 重复检测面板 |
| `src/core/share_server.py` | 158 | 服务端 API 封装 |

### 4.2 服务端 `server/src/`

| 文件 | 行数 | 内容 |
|---|---|---|
| `server/src/proxy.js` | 599 | 看图页 HTML 与图片代理 |
| `server/src/index.js` | 163 | 路由分发 |
| `server/src/oss.js` | 160 | V4 签名 |
| `server/src/shares.js` | 110 | 短链增删查 |
| `server/src/auth.js` | 104 | HMAC 鉴权 |
| `server/src/favorites.js` | 58 | 收藏同步 |

### 4.3 建议覆盖的维度

- 代码级缺陷：空指针、越界、竞态、资源泄漏、异常吞没
- 安全：路径穿越、凭据泄漏、越权、注入、弱随机
- 线程安全：跨线程访问 UI、worker 生命周期、取消时序
- 性能：大目录扫描、缩略图调度、内存峰值、UI 卡顿
- 用户体验：错误提示、空态、可逆性
- 文档与实现一致性：版本号、功能描述、命令是否可执行

---

## 五、必须遵守的约束

**1. 只读审查，不改代码**

这一轮只出报告。发现问题记录下来，不要直接改。上一轮（v1.5.0 到 v1.6.4）就是这样先审后改，节奏是对的。

**2. 绝对不要部署服务端**

`server/` 对应线上实例，正在对外提供分享服务。`wrangler deploy` 会立刻改变线上行为。审查不需要部署，也不要执行 `wrangler secret put`。

**3. 不要动 `.secrets/`**

目录里有四份真实凭据：

```
.secrets/gitee_token.txt              Gitee 推送令牌
.secrets/oss_credentials.local.md     阿里云 OSS 凭据
.secrets/ram_proxy_key.local.json     服务端只读 RAM 密钥
.secrets/server_shared_secret.local.json  客户端与服务端共享密钥
```

已被 `.gitignore` 排除。审查时不要读取内容、不要写入输出、不要复制。判断凭据处理是否安全，看代码逻辑就够，不需要真值。

**4. 跳过这几个目录**

```
.venv/                 785 MB
dist/                  389 MB
server/node_modules/   178 MB
build/                 27 MB
```

总共约 1.4 GB，和审查无关。`dist/` 里是历史安装包。

**5. 没有测试套件，需要自己写临时脚本**

仓库里没有 `tests/`，历史上所有验证都是一次性脚本，跑完就删（`.gitignore` 里 `_*.py` 就是给它们留的）。

要验证行为，参照这个模式：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe _你的脚本.py
```

文件名以 `_` 开头，跑完删掉，不要提交。

**6. 平台限制**

代码里有多处 Windows 专有实现：`os.path.isjunction`、`CreateMutexW`、DPAPI 加密、junction 判定。在 Linux 或容器里跑不通，也不要在非 Windows 环境判定它们是「不支持跨平台」的缺陷。

**7. 回复用中文**

---

## 六、这些已经修过，不要当成新问题上报

前几轮审查修掉的问题，如果重新扫到，请确认修复是否仍然有效，而不是当作新发现：

| 问题 | 修复位置 |
|---|---|
| `.qx_removed.json` 路径穿越 | `file_ops.safe_join()` 越界返回 None |
| pHash 的 DCT 矩阵转置，导致纯色图哈希全同 | `core/phash.py` 索引修正 |
| 单实例保护 `QLockFile` 不可靠（4 进程 2 个拿到锁） | 改用 `CreateMutexW` |
| 扫描跟随 junction 无限递归（实测 60 层仍在继续） | `_is_link_dir()` 显式判定，判断不了宁跳过 |
| 缩略图整图解码，108MP 峰值约 1.3 GB | `convert()` 前加 `draft()`，提速 9.8 倍 |
| 在线库虚拟根 `resolve()` 依赖当前工作目录 | 虚拟根不做 resolve |
| 云端对象键冲突互相覆盖 | 库外文件跳过并计数 |
| 扫描不存在目录静默显示 0 张 | 抛 `FileNotFoundError` |
| 收藏推送阻塞 UI | 入队 + 300ms 合并 + 后台线程 |
| 分享记录对话框点撤销卡死（11 条阻塞 3~11 秒） | 全部网络请求进后台线程池 |
| DELETE 请求全部 401（空 body 未算哈希） | 两端对齐 body hash |
| 看图页无手机适配 | 响应式 header + 双指缩放 |

另外这些是设计决定，不是缺陷：

- 短链访问不鉴权，拿到链接即可看图（分享的语义如此）
- 短链一个 token 一张图，不支持相册
- 客户端的 OSS 访问与列举全部直连，服务端不代理
- 已撤销链接可能仍在边缘缓存里保留字节，但链接本身每次查库，不会复活

---

## 七、验证手段

**语法检查**

```powershell
.\.venv\Scripts\python.exe -m compileall -q main.py src
```

服务端：

```powershell
cd server
node --check src/proxy.js
node --check src/index.js
```

**离屏冒烟**

无窗口启动主窗体，验证不崩、能加载目录、能退出：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,r'E:\QoderWork\qianxun-viewer');from PySide6.QtWidgets import QApplication;app=QApplication([]);app.setApplicationName('QianXunViewer');app.setOrganizationName('QianXun');from src.ui.main_window import MainWindow;w=MainWindow();w.show();app.processEvents();print('OK');w.close()"
```

**版本一致性**

```powershell
Select-String -Path src\meta.py -Pattern VERSION
```

`src/meta.py` 的 `VERSION` 要与 `docs/CHANGELOG.md` 顶部、README 徽标、Gitee 最新标签四处一致。

**打包验证**（可选，耗时长）

```powershell
$env:QX_ONEFILE='1'; .\.venv\Scripts\python.exe -m PyInstaller --noconfirm QianXunViewer.spec
$env:QX_ONEFILE='0'; .\.venv\Scripts\python.exe -m PyInstaller --noconfirm QianXunViewer.spec
```

`QX_ONEFILE` 控制单文件还是目录版，不设这个变量规格文件行为不确定。

---

## 八、交付要求

报告里每条问题要有：位置（文件与行）、现象、影响、修复建议。

按严重程度分档：

- **P0 严重**：数据丢失、崩溃、安全问题、无限循环
- **P1 重要**：功能错误、明显卡顿、资源泄漏
- **P2 一般**：可维护性、提示文案、边界情况
- **P3 建议**：优化项

如果某个问题前人已经记录在 `docs/CHANGELOG.md` 里但没修，标注一下，避免重复讨论。

---

## 九、参考材料

仓库内：

```
README.md                功能总览、上手、打包
docs/ARCHITECTURE.md     分层、线程模型、缓存策略、内存红线
docs/ONLINE_DESIGN.md    OSS 方案选型与分期
docs/OSS_DEV_MANUAL.md   接口、权限、实测速率、报错对照
docs/USER_GUIDE.md       用户操作说明
docs/CHANGELOG.md        逐版本变更与实测数据
server/README.md         服务端部署、鉴权、运维、踩坑
```

飞书（给人读的版本，内容同源）：

```
项目说明  https://feishu.cn/wiki/VYP3wFfxai5gESkpoF7c5J1Jnxd
技术说明  https://feishu.cn/wiki/UEVwwnbYDik3ZbkyeVPcnpYonAb
```
