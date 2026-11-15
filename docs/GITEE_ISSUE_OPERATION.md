# Gitee Issue 操作手册

记录本仓库（`qianxun-cloud/qianxun-viewer`）批量操作 issue 时验证过的做法，
以及踩过的坑。写这份的原因是同一件事试错了两次。

## 结论先说

**用 `mcp__gitee__update_issue`，不要手写 REST。**

REST 的 `PATCH` 对本仓库（group 命名空间下的仓库）返回的错误信息会把人带偏，
而 MCP server 走的是另一条端点，参数补齐即可成功。

## MCP 用法

```
mcp__gitee__update_issue
  owner:  qianxun-cloud
  repo:   qianxun-viewer
  number: IKVEVN            # issue 编号字符串，不是内部 id
  title:  <原标题，必填>     # 只改状态也必须带
  state:  closed            # 或 open
```

三个必填项缺一不可：`title` 必填、`number` 用编号字符串、`state` 支持双向
（`closed` / `open` 都验证过）。

## REST 为什么不行

同一条 issue，REST 的 `PATCH /v5/repos/{owner}/{repo}/issues/{number}` 试过这些组合，全部失败：

| 传参 | 结果 |
|---|---|
| 只 `state`（表单） | `404 project or enterprise` |
| `state` + `title`（JSON） | `404 project or enterprise` |
| `state` + `title` + `repo`（JSON） | `404 Not Found Project` |
| `state` + `title` + `owner`+`repo`（表单） | `404 Not Found Project` |
| 只 `labels` | `404 project or enterprise` |
| `PUT` 任一组合 | `405 Not Allowed` |

换过两个 token（普通权限、全权限不过期）结果一致，所以不是 scope 问题。
`GET` issue、`POST` 评论在同一个 token 下都正常，只有 `PATCH` 不通过。

`404 Not Found Project` 这条说明：一旦 body 里出现 `repo`，Gitee 会去按
「项目」找同名对象；而这个仓库的 issue 是 `issue_template_source: project`，
但没有绑定具体 project（`project_id` 为 `null`），于是必然找不到。

**别在这条路上继续试。** 直接用 MCP。

## 评论与状态的两个顺序问题

1. **关闭后不能再评论**：`POST /issues/{number}/comments` 返回
   `401 {"error":"当前issue已关闭评论功能"}`。要补说明就先把 issue 重开
   （`state: open`），发完评论再关。
2. **评论接口本身对有 `projects` 权限的旧 token 可用**，`201` 即成功；
   不依赖 MCP。

## 批量关闭的顺序

推荐顺序：**先发修复说明 → 再关闭**。反过来的话，说明发不进去，只能重开。

## 权限与凭据

- 凭据放在 `.secrets/`（已被 `.gitignore` 覆盖），不要写进代码或文档。
- 本机 `gitee` MCP server 已用 `xianlin-i` 身份认证，调 MCP 工具不需要再传 token。
- 仓库归属：group `qianxun-cloud`（显示名「千寻云」），owner `xianlin-i`，
  与个人仓库的接口行为不完全一致 —— 遇到莫名 404 先怀疑这一点。

## 验证闭环

关闭后确认状态：

```
GET /v5/repos/{owner}/{repo}/issues?state=open&per_page=100
```

返回空数组即全部处理完。批量操作建议最后跑一次，别只看单条返回。
