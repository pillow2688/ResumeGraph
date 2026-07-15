# Phase 2.3 文档异步处理与 Chunk 切分设计

## 目标与边界

本设计只把 Phase 2.2 已持久化的 Markdown `DocumentVersion` 转换为持久化
`DocumentChunk`，并通过独立 Worker 和 PostgreSQL `IngestionJob` 暴露处理状态。

包含：Job、Redis 队列、独立 Worker、确定性清洗、Markdown-aware Chunk、Chunk 只读
API/页面。明确不包含 Embedding、pgvector、发布、审核编辑、RAG、Retriever、LangGraph、
Chat、SSE、LLM 清洗、PDF、OCR、Word 或网页抓取。

`docs/PHASE2_PLAN.md` 的全局约束仍写着“不实现前端”，但 Phase 2.2 已有前端，且本次
用户要求 Phase 2.3 前端。以本次更具体的显式范围为准，并在状态记录中保留该差异。

## 队列方案

选择 Arq + Redis：

- Arq 原生使用 asyncio，能直接复用 async SQLAlchemy/asyncpg 处理路径；
- Worker 通过独立 `arq app.worker.WorkerSettings` 进程运行；
- API 仅 enqueue PostgreSQL Job UUID，队列载荷不包含文档正文；
- `_job_id` 使用 PostgreSQL Job UUID，避免相同任务重复入队；
- Arq Redis Job/Result 不是业务状态来源，管理 API 只查询 PostgreSQL。

Celery 对当前单队列切片过重；RQ 标准 Worker 的同步执行模型会增加 async 数据库桥接。
第一版不实现调度、周期任务、自动重试或任务编排框架。

## 数据模型

### `ingestion_jobs`

- UUID `id`；
- `document_version_id` 外键；
- `status`：`pending | processing | completed | failed`；
- `stage`：`reading | cleaning | chunking | saving`，pending 初始为 `reading`；
- `progress`：0–100；
- 可空、脱敏的 `error_message`；
- `created_at`、可空 `started_at`、可空 `finished_at`；
- PostgreSQL partial unique index 限制同一版本最多一个 pending/processing Job。

### `document_chunks`

- UUID `id`；
- `document_version_id` 外键；
- 从 0 开始的稳定 `chunk_index`；
- JSON 数组 `heading_path`；
- `content`、SHA-256 `content_hash`、Unicode 字符数 `character_count`；
- `enabled` 默认 true；
- `created_at`；
- `(document_version_id, chunk_index)` 唯一。

### `document_versions.status`

数据库约束扩展为 `draft | processing | ready_for_review`。创建 Job 时在同一 PostgreSQL
事务中由 `draft` 进入 `processing`；成功保存 Chunk 时进入 `ready_for_review`；失败或
入队失败时恢复 `draft`。成功不代表发布。

## API 与数据流

`POST /api/v1/admin/document-versions/{version_id}/process`：

1. `get_current_admin` 完成管理员认证；
2. 锁定 DocumentVersion；
3. 若有 active Job，幂等返回该 Job；若已 `ready_for_review`，返回 409；
4. 原子创建 pending Job 并把版本置为 processing；
5. 使用 Job UUID 作为 Arq `_job_id` 入队；
6. 返回 `202 {job_id, status}`；入队失败则将 Job 记为 failed、版本恢复 draft，并返回脱敏 503。

`GET /api/v1/admin/jobs/{job_id}` 只查 PostgreSQL，返回文档标题、版本号、status、stage、
progress、脱敏 error_message 和时间戳。

`GET /api/v1/admin/document-versions/{version_id}/chunks` 按 `chunk_index ASC` 返回只读列表。

所有三个接口都只接受管理员身份。Recruiter Cookie 不参与任何处理或 Chunk 管理。

## Worker 与失败语义

Worker startup 创建自己的 async Database/连接池，shutdown 显式关闭。每个阶段都先把
状态提交到 PostgreSQL：reading 5、cleaning 25、chunking 55、saving 85，最终 completed/
saving/100。

保存阶段在一个事务内删除该版本的旧 Chunk、插入全部新 Chunk、设置版本
`ready_for_review` 并完成 Job，因此不会暴露部分 Chunk。Worker 顶层捕获异常：空文档写入
明确且安全的失败消息，其他异常只存统一消息；日志记录异常类型而不记录正文、DSN 或原始
驱动消息。Arq Job 配置 `max_tries=1`，第一版失败后由管理员显式重试。

PostgreSQL Job 记录不受 API 重启影响。Redis AOF 保持现有本地队列持久性；但第一版不实现
数据库 outbox。API 在“Job commit 后、Redis enqueue 前”进程硬崩溃仍可能暂时留下
stranded pending Job；管理员重复调用 process 接口会重新入队该 pending Job。此限制与
Worker 硬终止无法执行失败落库的限制均写入阶段状态记录。

## 确定性清洗

按固定顺序：删除开头 UTF-8 BOM、删除全部 NUL、把 CRLF/CR 统一为 LF、清理每行行尾
空格、把连续空行压缩为一个空行、去除全文首尾空白、拒绝空结果、计算清洗后全文
SHA-256。原始 `raw_content` 和 Phase 2.2 原始 hash 不修改；清洗后全文 hash 仅作为本次
Pipeline 的确定性结果，Chunk 各自持久化自己的 hash。

## Markdown-aware Chunk

- 只在 fenced code block 之外识别 ATX `#` 到 `######` 标题；
- 首个 H1 视为文档标题并从 `heading_path` 省略；后续标题按层级维护路径；
- 标题开启新语义 section，段落/列表/code fence 以空行作为块边界；
- 默认最大 Chunk 为 2,000 字符，可由类型化设置调整；
- 超长 section 只在段落边界二次拆分，相同标题路径保持不变；
- 单个不可再分的超长段落或 code fence 保持完整，不按 N 个字符硬切；
- 输出顺序决定从 0 开始的稳定 `chunk_index`；内容保留当前 section 标题行。

示例中的首个 `# ResumeGraph` 是文档标题，因此 `### LangGraph` section 的
`heading_path` 为 `["技术架构", "LangGraph"]`。

## 前端

文档详情页对所选 draft 版本显示“开始处理”，成功后进入 `/admin/jobs/:jobId`。Job 页面
每秒轮询 pending/processing Job，显示文档名、版本、四种 status、本地化 stage 和进度；
completed 后提供 Chunk 页面入口，failed 显示后端脱敏消息。Chunk 页面按序显示 index、
heading path 和字面文本 content，不执行 Markdown HTML。401 统一跳回管理员登录。

## 测试与验证

后端测试覆盖模型/迁移、清洗、空文档、标题路径、Chunk 数量与稳定顺序、Repository 事务、
Job 状态、Worker 成功/失败、三个 API 的 Admin/Recruiter 隔离和脱敏 503。前端测试覆盖开始
处理、Job processing/completed/failed、Chunk 展示和 401 跳转。

最终运行 Ruff、pytest、Alembic upgrade/check、前端 lint/typecheck/test/build，并用虚构数据
实际启动 API + Arq Worker 完成 Markdown → Job → ready_for_review → Chunk 流程。不执行
Commit、Tag、Push 或 Merge。
