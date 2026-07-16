# Phase 4.5 状态 — Public Demo Experience

日期：2026-07-17

状态：**Phase 4.5 — Public Demo Experience: completed in the development workspace**

Phase 5：**未开始**

## 目标与实际完成内容

Phase 4.5 将默认根路径从管理员入口改为公开的 AI Interview 产品首页，同时保留 `/admin`
管理员入口。公开访问不要求面试官输入姓名或持有原始 Access Token；服务器读取单例
`PublicDemoConfig`，复用现有 Access Grant 校验和 Recruiter Session 创建能力，再通过 HttpOnly
Cookie 进入原有 `/interview` 页面。

本阶段没有修改 RAG、Retrieval、LangGraph、Agent、Evidence、额度扣减或知识发布逻辑。

## 数据库与 Migration

新增 Migration：`c7d9e2f4a6b8_phase_4_5_public_demo.py`，上游 Revision 为
`b4f8a1c2d3e5`。

新增表 `public_demo_config`：

- `id`：`SmallInteger` 主键，数据库 Check Constraint 强制 `id = 1`；
- `candidate_name`：公开候选人名称；
- `default_access_grant_id`：关联现有 `access_grants.id` 的外键；
- `enabled`：公开入口开关；
- `created_at`、`updated_at`：带时区时间戳。

固定主键与 Check Constraint 使数据库最多只能保存一条配置。Migration 不写入虚构 Grant，
不修改 Access Grant 表，也不触碰已有数据；downgrade 只删除新表。

## Public Demo 垂直切片

新增独立的 `PublicDemoRepository`、`PublicDemoService` 和 API 路由：

```text
PublicDemoConfig
  → PublicDemoService
  → AccessGrantService.create_session_from_grant(grant_id)
  → Recruiter Session + HttpOnly Cookie
  → /interview
  → 原有 RAG + LangGraph Agent
```

Repository 只负责单例配置的读取和 upsert。Service 检查配置存在、Enabled，以及所绑定 Grant
是否存在、已撤销、过期、额度用尽或没有项目。Grant 规则仍由 `AccessGrantService` 统一执行，
Public Demo 不复制或绕过权限逻辑。

`AccessGrantService` 新增通用内部能力：

- `validate_grant_for_session(grant_id)`；
- `create_session_from_grant(grant_id)`。

方法名和实现不感知 Public Demo。创建 Session 本身不消耗请求额度；额度仍在有效 Interview
请求进入既有流程后原子扣减。

## 新增 API

公开 API：

- `GET /api/v1/public/demo`：只返回可用状态和候选人名称，关闭时返回固定友好提示；
- `POST /api/v1/public/demo/session`：创建 Recruiter Session、设置现有 Recruiter HttpOnly
  Cookie，只返回 `{"redirect_url": "/interview"}`。

管理员 API：

- `GET /api/v1/admin/public-demo`；
- `PUT /api/v1/admin/public-demo`。

管理员接口继续使用现有 Admin Cookie/Depends。公开接口不返回 Grant ID、Token、项目范围、
Cookie 内容或管理信息。不可用配置返回 `AI Interview 尚未开放`；依赖故障使用脱敏 `503`。

## 前端页面与组件

- `/`：新的 `LandingPage`，包含 ResumeGraph 品牌、候选人介绍、可提问方向、技术标签和
  `Start Interview`；按钮通过 POST 创建 Session 后进入 `/interview`；
- `/admin`：仍跳转到 `/admin/login`；
- `/admin/public-demo`：`PublicDemoSetting` 可修改候选人、绑定现有 Grant、启用/关闭 Demo，
  并以 Card 展示 Grant 状态、剩余额度和公开范围；
- `/interview`：复用原页面和 SSE/API，仅重组展示层。

新增指定组件：`LandingPage`、`ChatWindow`、`MessageBubble`、`CitationCard`、
`PublicDemoSetting`、`AdminCard`。

## Interview 滚动与 UI 修复

Interview 根容器使用 `100vh/100dvh` 和 `overflow-hidden`；Header 与 Composer 设置为
`shrink-0`，中间 Message Area 使用 `min-h-0`、`flex-1`、`overflow-y-auto`，因此输入框不再
覆盖历史消息。新消息和 SSE 状态更新时保持平滑跟随底部，用户上滚后显示“回到底部”。

消息采用 AI 左侧白色 Card、用户右侧浅灰气泡。引用从紧凑标签升级为 `CitationCard`，明确展示
`Source` 和 `Chunk`，点击仍打开原有安全引用抽屉。原有 Loading/Agent progress、停止生成、
重试、安全 Markdown、空状态和 SSE 进度体验均保留。

公开页、共享 Admin Shell、Project/Access Grant Card 和 Interview 采用白色、浅灰、深灰、
大留白、16–24px 圆角和轻阴影；状态提示保留必要的低饱和语义色。未引入 UI 框架。

## 自动化验证结果

本检查点的新鲜结果：

| 检查 | 实际结果 |
| --- | --- |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `204 files already formatted` |
| `uv run pytest -q` | `660 passed, 6 skipped in 73.97s` |
| Public Demo / Access Grant 定向测试 | `56 passed in 2.09s` |
| 前端 `npm run lint` | exit 0 |
| 前端 `npm run typecheck` | exit 0 |
| 前端 `npm test` | `18` files，`100 passed` |
| 前端 `npm run build` | exit 0；`322 modules transformed` |
| `uv run alembic heads` | `c7d9e2f4a6b8 (head)` |
| Alembic 最近历史 | `b4f8a1c2d3e5 -> c7d9e2f4a6b8 (head)` |

新增测试覆盖：无配置、Disabled、Revoked、Expired、Quota exhausted、正常 Session、公开 API
响应最小化、HttpOnly Cookie、管理员认证和更新、Landing 启动流程，以及 11 轮聊天的独立滚动、
自动跟随和固定 Composer。

## 已知限制

- Migration 不自动创建配置，因为仓库无法安全推断应绑定哪个现有 Grant；管理员需在
  `/admin/public-demo` 首次选择 Grant 并启用，默认候选人输入值为“马腾飞”；
- 本轮没有连接持久化开发数据库执行 upgrade/downgrade，只通过 Migration 结构测试、模型测试
  和 Alembic Revision 图验证；
- 本轮未执行真实 LLM 或浏览器端到端访问，前端交互由 Vitest 覆盖，后端外部边界使用确定性 fake；
- 现有 SSE 提供公开 Agent 进度和最终回答，不提供后端尚未实现的逐 Token 输出；
- Vite 成功构建，但保留主 JS `569.67 kB` 的非阻断 code-splitting 提示；
- 未实现 Phase 5、永久聊天历史、Web Search、Hybrid Search、Reranker 或评估 Dashboard。

## Git 与停止状态

当前分支为 `main`。用户在实现验收后另行明确授权将 Phase 4.5 创建 Commit 并 Push 到
`origin/main`，本状态记录随该 Git 检查点上传。未执行 Merge、Reset、Clean、Restore、Rebase、
ECS 部署或生产配置修改；`docker-compose.prod.yml` 未修改。

Phase 4.5 在此停止，等待人工审核。
