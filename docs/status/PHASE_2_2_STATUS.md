# ResumeGraph Phase 2.2 状态记录

> 检查点日期：2026-07-15  
> 状态：Phase 2.2 — Knowledge documents and version management completed  
> 下一步：停止，等待用户明确确认后才能进入 Phase 2.3

## 1. Phase 2.2 目标

Phase 2.2 形成了一个可运行、可验证的知识文档与版本管理产品切片：

```text
管理员登录
→ 打开 Project 的知识文档页
→ 粘贴 Markdown 或上传 UTF-8 .md
→ 创建逻辑文档和 draft v1
→ 查看文档列表、详情和版本历史
→ 粘贴或上传新 draft 版本
→ 安全预览某个版本的原始 Markdown
```

本小节只接收、验证和持久化 Markdown，没有进入异步处理、Chunk、发布或检索阶段。

## 2. 实际数据库模型

### `knowledge_documents`

- `id`：应用侧生成 UUID，主键；
- `project_id`：非空外键，指向 `projects.id`，并建立查询索引；
- `title`：`VARCHAR(200)`，非空；
- `created_at`、`updated_at`：`TIMESTAMPTZ`，数据库默认 `now()`；
- Project 与 Knowledge Document 为一对多关系；外键没有 `ON DELETE CASCADE`。

### `document_versions`

- `id`：应用侧生成 UUID，主键；
- `document_id`：非空外键，指向 `knowledge_documents.id`，并建立查询索引；
- `version_number`：正整数；
- `source_type`：`pasted_markdown` 或 `markdown_file`；
- `original_filename`：上传时保存安全 basename，粘贴时为 `NULL`；
- `raw_content`：原始 Markdown 文本；
- `content_hash`：64 字符 SHA-256 十六进制摘要；
- `status`：本阶段由数据库约束固定为 `draft`；
- `created_at`：`TIMESTAMPTZ`，数据库默认 `now()`；
- 唯一约束：`(document_id, version_number)` 和 `(document_id, content_hash)`；
- Check 约束：版本号大于 0、来源合法、状态为 `draft`；
- 外键没有 `ON DELETE CASCADE`，版本内容创建后没有修改接口。

没有加入 `normalized_content`、发布状态、当前发布版本、Chunk 或向量字段。

## 3. Migration 内容

新增真实 Alembic Migration：

```text
revision: d7f6a2b4c8e1
down_revision: a5b170c969c4
file: alembic/versions/d7f6a2b4c8e1_create_phase_2_2_document_models.py
```

`upgrade()` 按依赖顺序创建 `knowledge_documents`、`document_versions`、外键、Check、唯一约束和索引；`downgrade()` 先删除版本表，再删除文档表。Migration 没有启用 pgvector。

真实开发数据库只执行了向上迁移，没有执行破坏性 downgrade。Migration 往返验证使用一次性数据库 `resumegraph_phase22_migration_check`：创建数据库、升级到 `d7f6a2b4c8e1`、确认两张表存在、降级到 `a5b170c969c4`、确认两张表均被移除，最后删除一次性数据库并确认不存在。

## 4. 后端 API

以下九个接口全部使用现有 `Depends(get_current_admin)`；未登录、失效 Admin Cookie 和 Recruiter Cookie 均不能访问：

| Method | Path | 成功状态 | 请求 | 安全响应 |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/projects/{project_id}/documents` | `201` | JSON：`title`, `content` | 文档详情和 v1 摘要 |
| `POST` | `/api/v1/admin/projects/{project_id}/documents/upload` | `201` | multipart：`title`, `file` | 文档详情和 v1 摘要 |
| `GET` | `/api/v1/admin/projects/{project_id}/documents` | `200` | 无 | 文档摘要数组，含版本数与最新版本摘要，不含 `raw_content` |
| `GET` | `/api/v1/admin/documents/{document_id}` | `200` | 无 | 文档、所属 Project 摘要、版本数与最新版本摘要 |
| `PATCH` | `/api/v1/admin/documents/{document_id}` | `200` | JSON：`title` | 更新后的完整文档详情 |
| `POST` | `/api/v1/admin/documents/{document_id}/versions` | `201` | JSON：`content` | 新版本，含 `raw_content` |
| `POST` | `/api/v1/admin/documents/{document_id}/versions/upload` | `201` | multipart：`file` | 新版本，含 `raw_content` |
| `GET` | `/api/v1/admin/documents/{document_id}/versions` | `200` | 无 | 版本摘要数组，按版本号倒序，不含 `raw_content` |
| `GET` | `/api/v1/admin/document-versions/{version_id}` | `200` | 无 | 指定版本及原始 Markdown |

主要业务错误为：`project_not_found`、`document_not_found`、`document_version_not_found`、`duplicate_document_version`、`unsupported_markdown_file`、`markdown_too_large`、`invalid_markdown_encoding`、`invalid_markdown_content`、`invalid_document_request` 和脱敏的 `service_unavailable`。

统一错误结构保持为：

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Safe client-facing message.",
    "details": null
  }
}
```

## 5. 管理员前端页面

新增并接入现有 React、TypeScript、Vite 管理员布局：

| 路径 | 页面能力 |
| --- | --- |
| `/admin/projects` | 每个项目新增“知识文档”入口；Project 的其他 CRUD 保持可用 |
| `/admin/projects/:projectId/documents` | 项目名称、返回入口、文档列表、空/loading/error 状态、粘贴或上传创建文档 |
| `/admin/documents/:documentId` | 文档及 Project 信息、修改标题、版本历史、粘贴或上传新版本、选择并预览版本 |

前端新增明确的 `KnowledgeDocument`、`KnowledgeDocumentSummary`、`DocumentVersion`、`DocumentVersionSummary`、`CreateDocumentRequest` 和 `CreateDocumentVersionRequest` 类型；生产代码未使用 `any` 或 Mock 数据。JSON 与 multipart 请求都携带 `credentials: "include"`，multipart 不手工伪造 `Content-Type`。

401 会回到管理员登录；404、409、413、415、422 和 503 显示预定义友好提示，不展示后端原始异常。新版本已经保存但列表刷新失败时，页面保留并选中已返回的新版本，避免向用户误报创建失败。标题保存错误显示在标题对话框内。

## 6. Markdown 上传安全限制

- `RESUMEGRAPH_MARKDOWN_MAX_BYTES` 为类型化配置，默认 1 MiB，粘贴和上传共用；
- 空内容或纯空白内容返回 422；
- 超限在读取 `limit + 1` 字节后返回 413，不写入数据库；
- 上传只接受扩展名 `.md`，不把客户端 Content-Type 作为唯一判断；
- 上传内容必须可按 UTF-8 解码；允许并移除 UTF-8 BOM；
- 拒绝 NUL 字符；
- 只保存安全 basename，不保存客户端或服务器真实路径；
- 上传内容不写入任意服务器路径；
- 只计算 SHA-256，不做换行标准化、空行压缩、结构化清洗或 LLM 清洗；
- 前端以字面文本 `<pre>` 展示 Markdown，不使用 `dangerouslySetInnerHTML`，原始 HTML/JavaScript 不执行。

## 7. 文档和版本完整数据流

```text
Route（HTTP、认证、Schema、状态码）
→ KnowledgeDocumentService（清洗标题、最小 Markdown 安全校验、SHA-256、业务错误）
→ KnowledgeDocumentRepository（SQLAlchemy 查询、事务、锁、持久化）
→ PostgreSQL（KnowledgeDocument + immutable draft DocumentVersion）
→ Pydantic 安全响应
→ typed frontend API client
→ 项目文档页 / 文档详情页
```

创建文档时，Project 校验、逻辑文档和 v1 在一个事务内完成。文档列表使用窗口函数一次取得版本数量和最新版本摘要，并用 `octet_length` 计算字节数；列表不加载完整内容，因此没有明显 N+1 或不必要的 Markdown 内容传输。

### v1/v2 创建流程

创建 v1 时，粘贴和上传入口先完成标题及 Markdown 安全校验，再校验并锁定所属 Project；Repository 在同一个事务中创建 `KnowledgeDocument` 和 `version_number = 1` 的 draft `DocumentVersion`。粘贴来源记录为 `pasted_markdown` 且文件名为 `NULL`；上传来源记录为 `markdown_file` 并只保存安全 basename。任一步骤失败都会回滚整个事务，不会留下没有 v1 的逻辑文档。

创建 v2 及后续版本时，Repository 使用 `SELECT ... FOR UPDATE` 锁定对应 Knowledge Document，先通过 SHA-256 检查相同内容，再以当前最大版本号加一分配新版本号并刷新文档 `updated_at`。新版本在独立事务中提交，旧版本内容保持不变；`(document_id, version_number)` 和 `(document_id, content_hash)` 唯一约束提供最终并发保护。粘贴和上传新版本复用相同流程，区别仅在 `source_type` 和 `original_filename`。

## 8. 新增及修改文件

### 后端、Migration 与测试

- 新增：`app/models/knowledge_document.py`、`app/models/document_version.py`；
- 新增：`app/schemas/knowledge_document.py`；
- 新增：`app/repositories/knowledge_document.py`；
- 新增：`app/services/knowledge_document.py`；
- 新增：`app/api/routes/admin_documents.py`；
- 新增：`alembic/versions/d7f6a2b4c8e1_create_phase_2_2_document_models.py`；
- 新增：`tests/test_knowledge_document_api.py`、`tests/test_knowledge_document_repository.py`、`tests/test_knowledge_document_service.py`、`tests/test_phase_2_2_migration.py`；
- 修改：model 导出/关系、应用启动装配、配置、统一异常、Project Repository 删除保护及其测试；
- 修改：`.env.example`、`docker-compose.yml`、`pyproject.toml`、`uv.lock`，加入 Markdown 限制配置和 multipart 运行依赖。

### 前端与文档

- 新增：`frontend/src/types/knowledgeDocument.ts`、`frontend/src/api/knowledgeDocuments.ts`；
- 新增：`frontend/src/components/MarkdownInputDialog.tsx`；
- 新增：`frontend/src/pages/ProjectDocuments.tsx`、`frontend/src/pages/DocumentDetail.tsx` 及对应测试；
- 修改：API Client、Project API/卡片/页面、Router 和相关测试；
- 修改：`README.md`、`docs/PHASE2_PLAN.md`、`AGENTS.md`；
- 新增：`docs/learning/PHASE_2_2_LEARNING.md`，解释模型、调用链、PostgreSQL 职责和未来 RAG 连接边界；
- 新增：`docs/architecture/PHASE_2_2_ARCHITECTURE.md`，记录当前架构、文档创建、版本创建和数据关系 Mermaid 图；
- 新增：本状态记录。

## 9. 当前系统新增能力

管理员现在可以正式创建逻辑文档及 v1、查看项目下的文档摘要、查看文档和版本历史、修改文档标题、粘贴或上传新版本，并安全查看任意版本的原始 Markdown。旧版本保持不变，完全相同的内容不能在同一文档中重复创建。

项目删除保护现在同时覆盖 `grant_projects` 和 `knowledge_documents`：任一关系存在都返回 `409 project_in_use`；检查和删除位于同一事务，冲突不会删除或修改 Grant、Document、Version 或关系数据。

## 10. 与 Phase 2.1 相比的变化

Phase 2.1 只有管理员 Project CRUD、Access Grant 与 Recruiter 授权展示。Phase 2.2 在不改变 Admin/Recruiter 认证和授权边界的前提下，新增两张文档持久化表、九个管理员文档 API、两个管理员页面、Markdown 上传/校验能力、版本历史及并发安全的版本号分配。

Project CRUD、管理员页面和 Access Grant 页面继续工作。文档接口不读写 Redis，不修改 Admin/Recruiter Session，也不修改 Grant 的 `request_count`、`max_requests`、`expires_at`、`revoked_at` 或授权项目范围。

## 11. 后端测试结果

最终实际执行：

```text
uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 76 files already formatted

uv run pytest -q
→ 266 passed in 11.34s（最终复验）
```

覆盖了 Admin/Recruiter 认证隔离、粘贴/上传创建、输入安全、空列表、详情、标题更新、v2 和递增版本号、重复内容、倒序列表、原始内容详情、Project 删除保护、数据库错误脱敏、Phase 0/1/2.1 回归，以及 Repository/Service 的并发版本分配。

真实 PostgreSQL Repository 验证输出：

```text
REAL_POSTGRES_REPOSITORY_FLOW_OK versions=2 duplicate=blocked delete=blocked
REAL_POSTGRES_CONCURRENT_VERSION_OK allocated=2,3
```

## 12. 前端检查结果

在 `frontend/` 最终实际执行：

```text
npm run lint
→ eslint .
→ exit 0

npm run typecheck
→ tsc -b --pretty false
→ exit 0

npm test
→ 9 test files passed
→ 52 tests passed
→ Duration 5.62s（最终复验）

npm run build
→ 46 modules transformed
→ built in 342ms（最终复验）
→ dist/index.html 0.51 kB
→ dist/assets/*.css 27.00 kB
→ dist/assets/*.js 341.07 kB
```

没有生成第二种 lockfile。

## 13. Alembic 和 Docker 检查结果

```text
uv run alembic upgrade head
→ exit 0

uv run alembic current
→ d7f6a2b4c8e1 (head)

uv run alembic check
→ No new upgrade operations detected.

docker compose -f docker-compose.yml config --quiet
→ exit 0

docker compose up -d --build backend
→ backend image rebuilt successfully
→ python-multipart 0.0.32 installed
→ backend, PostgreSQL and Redis healthy

GET /api/v1/health/ready
→ {"status":"ready","dependencies":{"postgresql":"up","redis":"up"}}
```

一次性数据库 downgrade/upgrade 往返验证也成功；开发数据库没有 downgrade。

## 14. 真实浏览器和 API 联调结果

使用虚构管理员和项目完成了真实联调：

```text
管理员登录
→ 创建 Phase 2.2 Browser Fictional Project 20260715
→ 打开项目知识文档页
→ 粘贴创建 Browser Document A v1
→ 查看文档详情与 v1
→ 粘贴创建 v2
→ 在 v1/v2 间切换并核对各自原始内容
→ 真实 multipart API 上传 browser-upload.md 创建 Document B v1
→ 浏览器刷新列表并查看 Document B、文件名、70 字节内容和 draft 状态
→ 尝试删除所属 Project
→ API 返回 409 project_in_use，Project 仍可查询
→ 打开 Access Grant 页面，页面和创建入口正常
→ 管理员退出并回到登录页
```

Markdown 安全预览在浏览器中实际验证为 `<pre>`：包含字面 `<script>`，内部 `script` 元素数量为 0，脚本未执行；浏览器控制台错误数为 0。

当前浏览器控制能力不能向本地文件选择器注入文件，因此没有把“浏览器点击选择本地文件”冒充为成功。上传链路通过独立的真实 API 登录/Cookie/multipart 请求验证，随后在同一真实浏览器页面中确认该上传文档及内容正确展示。

精确删除保护验证：

```text
REAL_API_MARKDOWN_UPLOAD_OK document_id=<generated UUID> filename=browser-upload.md
REAL_API_PROJECT_DELETE_PROTECTION_OK status=409 code=project_in_use
```

联调后按精确 UUID/用户名清理全部虚构数据和临时文件：2 个文档、3 个版本、1 个项目、1 个管理员均已移除；Admin Session 为 0，剩余测试管理员和测试项目均为 0。临时 Vite 进程已停止，Docker backend 保持健康。

## 15. 已知限制和非阻断问题

- 当前所有版本只能是 `draft`；没有发布、下线或当前发布版本；
- 没有文档或版本删除 API；版本内容只能通过创建新版本修正；
- 列表为当前范围要求的全量列表，没有分页、筛选或搜索；
- Markdown 预览是安全的原始文本预览，不是富文本 Markdown 渲染；
- 1 MiB 是当前默认配置限制，可通过类型化环境配置调整；
- 浏览器控制器不能自动选择本地文件，真实上传采用 API multipart 并由浏览器确认结果；仓库尚未加入 Playwright E2E 套件；
- Git 仓库 `main` 当前没有 Commit，Phase 0 至 Phase 2.2 共同处于既有未提交工作区，`git diff --stat` 不包含未跟踪文件。

## 16. 当前 Git 分支

```text
branch: main
HEAD: NO_COMMITS
```

本任务没有执行 Commit、Tag、Merge、Push、Reset、Clean、Restore 或 Rebase。

## 17. `git status --short`

```text
A  .dockerignore
AM .env.example
AM .gitignore
A  .python-version
AM AGENTS.md
A  CODEX_FIRST_TASK.md
A  Dockerfile
AM README.md
A  alembic.ini
A  alembic/env.py
A  alembic/script.py.mako
A  alembic/versions/.gitkeep
A  alembic/versions/a5b170c969c4_create_phase_1_1_models.py
A  app/__init__.py
A  app/api/__init__.py
A  app/api/routes/__init__.py
A  app/api/routes/health.py
A  app/core/__init__.py
AM app/core/config.py
AM app/core/exceptions.py
A  app/core/logging.py
A  app/infrastructure/__init__.py
AM app/infrastructure/database.py
A  app/infrastructure/health.py
AM app/infrastructure/redis.py
AM app/main.py
AM app/models/__init__.py
A  app/models/access_grant.py
A  app/models/admin_user.py
A  app/models/base.py
A  app/models/grant_project.py
AM app/models/project.py
A  app/schemas/__init__.py
A  app/schemas/error.py
A  app/schemas/health.py
AM docker-compose.yml
A  docs/PRODUCT_SPEC.md
A  docs/RUNTIME_AGENT_HARNESS.md
AM pyproject.toml
AM tests/test_config.py
A  tests/test_health.py
AM tests/test_models.py
AM uv.lock
?? alembic/versions/d7f6a2b4c8e1_create_phase_2_2_document_models.py
?? app/api/dependencies/
?? app/api/routes/admin_access_grants.py
?? app/api/routes/admin_auth.py
?? app/api/routes/admin_documents.py
?? app/api/routes/admin_projects.py
?? app/api/routes/recruiter_access.py
?? app/cli/
?? app/core/security.py
?? app/infrastructure/admin_login_limiter.py
?? app/infrastructure/admin_session.py
?? app/infrastructure/failure_limiter.py
?? app/infrastructure/recruiter_session.py
?? app/models/document_version.py
?? app/models/knowledge_document.py
?? app/repositories/
?? app/schemas/access_grant.py
?? app/schemas/admin_auth.py
?? app/schemas/knowledge_document.py
?? app/schemas/project.py
?? app/services/
?? docs/PHASE1_SUMMARY.md
?? docs/PHASE2_PLAN.md
?? docs/architecture/
?? docs/learning/
?? docs/status/
?? frontend/
?? tests/test_access_grant_api.py
?? tests/test_access_grant_repository.py
?? tests/test_access_grant_service.py
?? tests/test_admin_auth_api.py
?? tests/test_admin_auth_service.py
?? tests/test_admin_redis.py
?? tests/test_admin_repository.py
?? tests/test_create_admin_cli.py
?? tests/test_knowledge_document_api.py
?? tests/test_knowledge_document_repository.py
?? tests/test_knowledge_document_service.py
?? tests/test_phase_2_2_migration.py
?? tests/test_project_api.py
?? tests/test_project_repository.py
?? tests/test_project_service.py
?? tests/test_recruiter_redis.py
?? tests/test_security.py
```

## 18. `git diff --stat`

```text
 .env.example                   |  15 ++-
 .gitignore                     |  12 ++
 AGENTS.md                      | 138 ++++++++++++++++---
 README.md                      | 292 +++++++++++++++++++++++++++++++++++++++--
 app/core/config.py             |  47 ++++++-
 app/core/exceptions.py         | 230 ++++++++++++++++++++++++++++++++
 app/infrastructure/database.py |  28 +++-
 app/infrastructure/redis.py    |  59 ++++++++-
 app/main.py                    |  88 ++++++++++++-
 app/models/__init__.py         |  12 +-
 app/models/project.py          |   5 +
 docker-compose.yml             |  12 ++
 pyproject.toml                 |   2 +
 tests/test_config.py           |  75 +++++++++++
 tests/test_models.py           | 150 ++++++++++++++++++++-
 uv.lock                        |  92 +++++++++++++
 16 files changed, 1213 insertions(+), 44 deletions(-)
```

由于仓库没有基线 Commit，未跟踪的 Phase 1、Phase 2.1、Phase 2.2 文件不会出现在 `git diff --stat` 中；第 17 节是更完整的工作区摘要。

## 19. 当前尚未实现

Phase 2.2 明确没有实现：

- Job 或 `ingestion_jobs`；
- Worker；
- `BackgroundTasks`、Redis 队列或其他异步处理；
- 文本清洗 Pipeline 或 `normalized_content`；
- Chunk、Chunk 预览或 Chunk 审核；
- 文档发布、下线或版本冻结；
- Embedding；
- pgvector 扩展、向量字段或向量检索；
- RAG；
- LangGraph；
- Chat 或 SSE；
- PDF、Word、OCR、图片识别、网页抓取或对象存储；
- LLM 调用。

## 20. 停止条件

Phase 2.2 已完成并生成本检查点。当前尚未获得进入 Phase 2.3 的用户确认；不得自动创建 Job、Worker、清洗 Pipeline 或 `document_chunks`，也不得提前实现 Embedding、pgvector、发布、RAG、LangGraph 或 Chat。
