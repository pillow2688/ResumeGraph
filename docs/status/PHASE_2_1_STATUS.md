# ResumeGraph Phase 2.1 状态记录

> 检查点日期：2026-07-14  
> 状态：Phase 2.1 — Project management product slice completed  
> 下一步：停止，等待用户明确确认后才能进入 Phase 2.2

## 1. Phase 2.1 目标

Phase 2.1 的目标是形成一个可运行、可验证的项目管理产品切片：

```text
管理员 Cookie 认证
→ Project CRUD
→ Project 范围内的 Access Grant
→ 一次性 Access Token Exchange
→ Recruiter Cookie 会话
→ 授权项目展示
→ Grant 撤销后 Recruiter Session 立即失效
```

本检查点完成后，Phase 2.1 同时具备后端 API、管理员与面试官前端、真实 Cookie 联调和可追溯验证记录。没有进入 Phase 2.2。

## 2. 后端已完成能力

Phase 2.1 后端延续 Phase 1 的认证和授权边界，并提供以下真实能力：

- 管理员使用独立 HttpOnly Cookie 和 Redis Admin Session 登录、查询当前身份与退出；
- Project 使用 PostgreSQL 持久化，提供创建、列表、详情、部分更新和删除 API；
- Project 删除前检查 `grant_projects` 引用，冲突返回 `409 project_in_use`；
- 管理员可以创建、列表、查看和撤销限定 Project 范围的 Access Grant；
- Access Token 仅在 Grant 创建响应中返回一次，数据库只保存摘要；
- Recruiter 使用 Access Token Exchange 建立独立 HttpOnly Cookie 和 Redis Recruiter Session；
- `GET /api/v1/access/me` 每次通过 PostgreSQL 重新校验 Grant 状态与项目范围；
- Grant 撤销后，旧 Recruiter Session 即使仍有 Redis TTL，也会立即被 PostgreSQL 重校验拒绝；
- 统一错误 envelope 将认证、输入、冲突和依赖错误转换为脱敏的 401、409、422、429 或 503。

本次前端任务没有修改任何 `app/`、`tests/`、`alembic/`、Docker 或后端数据库 Migration 文件。

## 3. 前端新增能力

任务开始时 `frontend/` 已存在 React/Vite/TypeScript 基础和管理员登录、项目管理页面。本次沿用该结构，补齐：

- 统一 Fetch API Client：集中处理 base URL、JSON、`credentials: "include"` 和 `ApiError`；
- `Admin`、`Project`、`AccessGrant`、`RecruiterSession` 及全部请求/响应类型；
- 管理员 Project 创建、编辑、删除、空状态、loading、成功和脱敏错误状态；
- 管理员 Access Grant 列表、项目范围选择、创建、一次性访问码、复制和撤销；
- 面试官 Access Token Exchange 入口和统一无效提示；
- Recruiter 授权信息、过期时间、剩余请求次数和授权项目展示；
- Admin logout 与 Recruiter logout；
- 401 跳转、409 `project_in_use`、422 输入错误和 503 服务不可用的友好提示；
- 一次性访问码只保存在当前 React 弹窗状态中，关闭即清除；
- 运行时代码不包含 mock 数据。测试使用 Vitest mock 隔离前端行为，不冒充真实后端。

前端不会读取 Cookie，不在 React state 保存 Session Token，也不使用 localStorage 或 sessionStorage 保存认证信息。

## 4. 页面列表

| 路径 | 页面 | 当前能力 |
| --- | --- | --- |
| `/admin/login` | 管理员登录 | username/password 登录；成功跳转项目页；失败脱敏 |
| `/admin/projects` | 管理员项目管理 | 列表、创建、编辑、二次确认删除、空/loading/error/success |
| `/admin/access-grants` | Access Grant 管理 | 列表、项目多选、创建、一次性访问码、复制、撤销确认 |
| `/access` | 面试官访问入口 | Access Token Exchange；无效、过期、撤销、超限统一提示 |
| `/portfolio` | Recruiter 授权项目 | Grant 信息、过期时间、剩余次数、授权项目、退出访问 |

管理员页共享导航和退出入口。未知路径回到 `/admin/login`。Recruiter `/portfolio` 收到 401 时回到 `/access`。

## 5. API 联调情况

所有请求统一通过 `frontend/src/api/client.ts`，真实请求均带 `credentials: "include"`。

| API | 前端使用位置 | 验证情况 |
| --- | --- | --- |
| `POST /api/v1/admin/auth/login` | `/admin/login` | 真实浏览器 200，Admin Cookie 后续请求有效 |
| `GET /api/v1/admin/auth/me` | Admin API Client | 类型与真实 Schema 已对齐 |
| `POST /api/v1/admin/auth/logout` | Admin Layout | 真实浏览器 204，回到登录页 |
| `GET /api/v1/admin/projects` | `/admin/projects`、Grant 表单 | 真实浏览器 200 |
| `POST /api/v1/admin/projects` | Project 表单 | 真实浏览器 201 |
| `PATCH /api/v1/admin/projects/{id}` | Project 编辑表单 | 前端行为测试和后端 API 回归通过 |
| `DELETE /api/v1/admin/projects/{id}` | Project 删除确认 | 前端行为测试和后端 API 回归通过；409 文案已映射 |
| `GET /api/v1/admin/access-grants` | Grant 管理页 | 真实浏览器 200 |
| `POST /api/v1/admin/access-grants` | Grant 创建表单 | 真实浏览器 201，一次性访问码弹窗出现 |
| `POST /api/v1/admin/access-grants/{id}/revoke` | Grant 撤销确认 | 真实浏览器 200 |
| `POST /api/v1/access/exchange` | `/access` | 真实浏览器 200，Recruiter Cookie 建立 |
| `GET /api/v1/access/me` | `/portfolio` | 真实浏览器 200；撤销后 401 并跳转 |
| `POST /api/v1/access/logout` | Portfolio | 真实浏览器 204，回到访问入口 |

真实浏览器流程之外，后端 `205` 个测试覆盖 API、Repository、Service、Redis Session、认证隔离、错误状态和冲突路径。

## 6. 用户完整流程

本次使用虚构数据实际走通：

```text
管理员登录
→ 创建 Fictional Atlas Portfolio
→ 创建 Project 范围内的 Fictional Recruiter Verification Grant
→ 页面提示“访问码只显示一次，请立即保存。”
→ 点击复制，一次性访问码进入浏览器会话剪贴板
→ 关闭弹窗后页面不再包含访问码
→ 访问 /access 并输入该访问码
→ 进入 /portfolio
→ 看到 Grant、到期日、剩余请求次数和 Fictional Atlas Portfolio
→ 返回管理员页面撤销 Grant
→ 再次访问 /portfolio
→ 后端 401，前端自动回到 /access
```

另建第二条虚构 Grant 验证 Recruiter logout；退出后回到 `/access`。随后使用仍有效的 Admin Cookie 进入管理员页面并验证 Admin logout 回到 `/admin/login`。

## 7. 新增和修改文件

### 本次新增

- `frontend/src/api/accessGrants.ts`
- `frontend/src/api/recruiterAccess.ts`
- `frontend/src/types/auth.ts`
- `frontend/src/types/accessGrant.ts`
- `frontend/src/components/AccessGrantCard.tsx`
- `frontend/src/components/AccessGrantForm.tsx`
- `frontend/src/components/OneTimeTokenDialog.tsx`
- `frontend/src/components/Layout.test.tsx`
- `frontend/src/pages/AccessGrants.tsx`
- `frontend/src/pages/AccessGrants.test.tsx`
- `frontend/src/pages/RecruiterAccess.tsx`
- `frontend/src/pages/RecruiterAccess.test.tsx`
- `frontend/src/pages/Portfolio.tsx`
- `frontend/src/pages/Portfolio.test.tsx`

### 本次修改

- `frontend/src/api/client.ts`
- `frontend/src/api/auth.ts`
- `frontend/src/api/projects.ts`
- `frontend/src/components/Layout.tsx`
- `frontend/src/components/ConfirmDialog.tsx`
- `frontend/src/pages/AdminLogin.tsx`
- `frontend/src/pages/AdminLogin.test.tsx`
- `frontend/src/pages/Projects.tsx`
- `frontend/src/pages/Projects.test.tsx`
- `frontend/src/router/index.tsx`
- `docs/status/PHASE_2_1_STATUS.md`
- `AGENTS.md`

`frontend/` 当前共有 40 个由 `rg --files frontend` 识别的项目文件；`node_modules/` 和 `dist/` 不计入源文件清单。

## 8. 测试结果

### 前端

最终执行：

```text
npm test
→ 7 test files passed
→ 34 tests passed
→ Duration 5.12s (最终复验)
```

覆盖内容包括：

- API Client JSON、Cookie credentials 和错误 envelope；
- Admin 登录成功、401、422、503 脱敏；
- Project loading、空状态、创建、编辑、删除确认、401、409、422、503；
- Access Grant 创建、一次性访问码、复制、关闭清除、撤销、空项目、401、422、503；
- Recruiter Exchange 成功与各种无效 Grant 的统一提示；
- Portfolio 授权展示、401 跳转、503、logout 成功与失败；
- Admin 导航和 logout 成功与失败。

### 后端

最终执行：

```text
uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 65 files already formatted

uv run pytest -q
→ 205 passed in 11.36s (最终复验)
```

## 9. Build、Typecheck 与 Lint 结果

最终执行：

```text
npm run typecheck
→ tsc -b --pretty false
→ exit 0

npm run lint
→ eslint .
→ exit 0

npm run build
→ tsc -b && vite build
→ 42 modules transformed
→ built in 340ms (最终复验)
```

生产构建产物：

```text
dist/index.html                  0.51 kB
dist/assets/index-B5XHM4XH.css 25.66 kB
dist/assets/index-cDxHjaIp.js 322.75 kB
```

## 10. 真实浏览器联调结果

环境：

- Docker Compose：backend、postgres、redis 均为 Up；PostgreSQL 和 Redis 为 healthy；
- Backend：`127.0.0.1:8000`；
- Vite：`127.0.0.1:5173`，通过 `/api` proxy 访问后端；
- Alembic：`a5b170c969c4 (head)`。

真实浏览器验证结果：

- Admin login、Project list/create、Grant list/create/revoke、Access exchange、Recruiter me、Recruiter logout、Admin logout 全部成功；
- Admin Cookie 与 Recruiter Cookie 作用域独立，同一浏览器会话中可分别工作；
- Grant 撤销后 `/portfolio` 刷新被拒绝并跳转 `/access`；
- 一次性访问码弹窗关闭后 DOM 不再包含该值；
- 浏览器控制台中匹配访问码前缀的日志条数为 0；
- 未读取或检查浏览器 Cookie、local storage 或 session storage。

清理结果：

```text
Redis matched sessions deleted: 1
grant_projects deleted: 2
access_grants deleted: 2
projects deleted: 1
admin_users deleted: 1

remaining_admins=0
remaining_projects=0
remaining_grants=0
```

浏览器剪贴板中的测试访问码已清空；临时 Vite 开发服务器已停止。

## 11. 当前限制和已知非阻断问题

- 当前只展示 Project 基础字段；文档、发布、知识检索和聊天均不属于 Phase 2.1。
- `/portfolio` 展示后端当前授权范围，不展示 Project 描述以外的未来知识内容。
- 真实浏览器联调是本次受控验证记录，仓库尚未加入独立 Playwright E2E 测试套件。
- 当前后端删除保护按任何 `grant_projects` 历史引用判断；撤销 Grant 不会删除该关系。因此曾被授权的 Project 仍可能返回 `project_in_use`。前端按产品要求显示“该项目正在被访问授权使用，请先撤销相关授权。”，但历史关系的最终清理语义需要后续单独确认，不能在本任务修改后端。
- Portfolio 当前以日期显示 Grant 到期时间；精确时刻仍可从 Admin Grant 页面查看。这是非阻断展示限制。
- 当前 Git 仓库 `main` 尚无 Commit；Phase 0、Phase 1、Phase 2.1 后端及本次前端共同处于既有未提交工作区。

## 12. 尚未实现

Phase 2.1 明确没有实现：

- 文档上传与文档版本；
- Chunk；
- Embedding；
- pgvector 检索；
- RAG；
- LangGraph；
- Chat；
- SSE；
- PDF；
- OCR；
- Worker；
- Recruiter 写操作或管理员权限；
- Phase 2.2 及以后内容。

## 13. 关键设计和安全决定

- 认证由后端 HttpOnly Cookie 和 Redis Session 完成，前端不重新实现认证；
- 所有 API 请求都使用 `credentials: "include"`；
- Session Token 不进入 React state、URL、storage 或 console；
- Access Token 只在创建 Grant 后的当前弹窗状态和显式复制流程中短暂存在；
- Access Token 关闭后无法从前端重新获取；
- 页面只展示预定义友好错误，不展示后端原始 message、SQL、Traceback、Redis 详情、Cookie 或 DSN；
- Runtime 不使用 mock 数据，真实联调没有伪装为已完成接口；
- 未加入 Phase 2.2 页面、空壳或依赖。

## 14. Git 状态与停止条件

记录时：

```text
branch: main
HEAD: NO_COMMITS
relevant status:
AM AGENTS.md
?? docs/status/
?? frontend/
```

工作区同时保留此前已存在的 Phase 0、Phase 1 和 Phase 2.1 后端未提交文件；本任务没有覆盖、回滚或提交它们。由于仓库没有基线 Commit，`git diff --stat` 不包含所有未跟踪文件，不能作为完整 Phase Diff。

本检查点没有创建 Commit、Tag、Push、Merge。Phase 2.1 到此停止，等待用户确认；不得自动进入 Phase 2.2。
