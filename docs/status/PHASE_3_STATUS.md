# Phase 3 状态 — 单轮 RAG 面试 MVP

日期：2026-07-16

状态：**Phase 3 — Basic RAG interview MVP: completed**

## 已完成能力

- `RetrievalRepository` 在 PostgreSQL 中验证有效 Grant，并把两类知识合并进同一 pgvector Top-K：
  - `profile`：`project_id IS NULL`，对有效 Recruiter Grant 全局可用；
  - `project`：必须同时位于 Grant 授权和当前请求的有效项目范围。
- 检索只连接当前发布指针、`published` Version、enabled 且无禁用原因的 Chunk，以及身份和
  `content_hash` 均匹配的活动 Embedding。
- 当前结果按 `content_hash` 去重；服务端生成 `evidence_N`，模型不接触数据库 UUID。
- 通用 `ChatProvider` / `OpenAICompatibleChatProvider` 复用 DeepSeek 配置，严格 JSON 输出经过
  Pydantic、状态、Handle 和数据库二次校验。
- `POST /api/v1/interview/ask` 使用 Recruiter Session，返回最小 Citation 和剩余额度。
- `request_count` 使用单条条件 `UPDATE ... RETURNING`，证据不足仍扣一次，并发不超额。
- `/interview` 支持 Grant、额度、项目多选、回答、Profile/Project Citation、拒答、错误、Logout
  和返回 Portfolio；历史仅在页面内存中。
- `/api/v1/admin/users` 和 `/admin/users` 支持管理员列表、新增与删除；禁止自删和删除最后一个
  管理员。
- Project/Profile 文档列表直接显示中文状态和下一步动作；详情页显示“处理 → Chunk 审核 →
  向量索引 → 发布”的当前工作流。
- Docker Compose 包含 PostgreSQL、Redis、Backend、Worker、Frontend，并通过 Nginx 同源代理。

## 主要新增/修改文件

- `app/repositories/retrieval.py`
- `app/services/retrieval.py`
- `app/infrastructure/chat.py`
- `app/rag/prompt.py`
- `app/services/interview.py`
- `app/api/routes/interview.py`
- `app/schemas/interview.py`
- `app/repositories/admin_user.py`
- `app/services/admin_user_management.py`
- `app/api/routes/admin_users.py`
- `app/schemas/admin_user.py`
- `app/main.py`
- `frontend/src/pages/Interview.tsx`
- `frontend/src/pages/AdminUsers.tsx`
- `frontend/src/pages/ProfileDocuments.tsx`
- `frontend/src/pages/ProjectDocuments.tsx`
- `frontend/src/pages/DocumentDetail.tsx`
- `frontend/src/components/DocumentWorkflowStatus.tsx`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `docker-compose.yml`

## 自动化与外部验收结果

| 检查 | 实际结果 |
| --- | --- |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `158 files already formatted` |
| `uv run pytest -q` | `559 passed, 5 skipped in 21.55s` |
| 真实 PostgreSQL/pgvector 测试 | `1 passed in 2.81s` |
| 真实 Provider + 三问集成 | `1 passed in 6.77s` |
| `npm run lint` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run test` | `14` files、`84 passed` |
| Docker production frontend build | Vite build 成功，54 modules transformed |
| `docker compose config --quiet` | exit 0 |
| `docker compose up -d --build` | exit 0；三镜像构建，五服务启动 |
| `docker compose ps` | postgres/redis/backend/frontend healthy；worker running |
| PostgreSQL readiness | accepting connections |
| Redis | `PONG` |
| Backend ready | PostgreSQL/Redis 均 `up` |
| Worker | 两个 ARQ Job 注册并连接 Redis |
| Alembic current/check | `e1b7c9d4a2f6 (head)`；无待生成迁移 |

## 真实浏览器验收

| 场景 | 结果 |
| --- | --- |
| Profile 页面与全局范围说明 | PASS |
| Profile 草稿处理和 3 个 Chunk 审核 | PASS |
| 智谱真实向量索引与发布 | PASS |
| ResumeGraph 已发布 Project 文档状态 | PASS |
| 管理员列表、新增、删除、自删禁用 | PASS |
| Grant 只授权 ResumeGraph | PASS |
| 教育问题 | answered；第一人称；Citation=`候选人 Profile` / 教育背景 |
| Redis 问题 | answered；第一人称；Citation=`resumegraph` / 状态管理/Redis |
| QPS/P99 | insufficient_evidence；固定拒答；无 Citation |
| request_count | `0/10 → 1/10 → 2/10 → 3/10`，页面 remaining `10→9→8→7` |
| Grant 撤销 | PASS；旧 Session 跳转 `/access`；计数仍为 3 |
| 防重复提交 | 三次提交期间输入、项目和按钮均 disabled |
| 浏览器控制台 | 0 条 error/warning |

## 已知边界

- 当前是单轮 RAG；页面可显示多条，但请求不发送历史。
- 没有 LangGraph、多 Agent、多轮、SSE、Query Rewrite、Hybrid Search、Reranker 或自动评估平台。
- 没有管理员 Retrieval Debugger。
- Profile 已正式接入 Phase 3 Retriever，不再是 Phase 4 待迁移项。
- 内容过短可能被质量规则全部禁用；后台会显示失败原因，管理员需补充有信息量的新版本。

## Git 与停止状态

当前分支为 `main`，工作树在任务开始前已包含大量未提交的 Phase 2/Phase 3 和 IDE 修改；均被
保留。未执行 reset、clean、restore、rebase、merge、`git add`、commit、tag 或 push。最终 Git
状态与 diff 统计以本轮结束命令为准。

Phase 3 已完成；等待用户确认后再调整 Phase 4 计划。
