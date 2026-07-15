# Phase 2.3 文档异步处理与 Chunk 切分实现计划

> **面向 AI 代理的工作者：** 必需子技能：在当前会话中使用
> `superpowers:executing-plans` 逐任务实现；每项遵循 TDD 红—绿—重构。用户明确禁止
> Commit、Tag、Push、Merge，因此计划不含提交步骤。

**目标：** 用独立 Arq Worker 把 Markdown DocumentVersion 确定性清洗、按结构切分并保存
为 PostgreSQL Chunk，同时提供管理员状态 API 和 React 只读页面。

**架构：** FastAPI 原子创建 PostgreSQL Job 后只负责 Arq 入队；Worker 使用独立数据库连接
分阶段更新 Job，并在单事务内保存 Chunk 和完成版本状态。Redis 只协调队列，PostgreSQL 是
Job、版本和 Chunk 的事实来源。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy async、Alembic、PostgreSQL、Redis、Arq、
pytest、React 19、TypeScript、Vitest。

---

## 文件结构

- 创建 `app/models/ingestion_job.py`、`app/models/document_chunk.py`：持久化实体。
- 修改 `app/models/document_version.py`、`app/models/__init__.py`：状态约束和关系。
- 创建 `alembic/versions/f3a9c2d8e4b1_create_phase_2_3_ingestion.py`：增量 schema。
- 创建 `app/ingestion/cleaning.py`、`app/ingestion/chunking.py`：无 I/O 纯函数。
- 创建 `app/repositories/ingestion.py`：Job/Chunk 事务与查询。
- 创建 `app/services/ingestion.py`：API use cases 和队列边界。
- 创建 `app/infrastructure/job_queue.py`：Arq enqueue adapter 和 JSON serializer。
- 创建 `app/worker.py`：独立 Worker startup/shutdown/Job 入口。
- 创建 `app/schemas/ingestion.py`、`app/api/routes/admin_ingestion.py`：HTTP 合同。
- 修改 `app/main.py`、`app/core/config.py`、`app/core/exceptions.py`：装配、设置、脱敏错误。
- 创建后端 `tests/test_ingestion_*.py`、`tests/test_phase_2_3_migration.py` 并更新模型测试。
- 修改 `frontend/src/types/knowledgeDocument.ts`、API、DocumentDetail、Router。
- 创建 `frontend/src/pages/IngestionJob.tsx`、`DocumentChunks.tsx` 及测试。
- 修改 `Dockerfile`、`docker-compose.yml`、`.env.example`、`README.md`、依赖锁。
- 最后创建 `docs/status/PHASE_2_3_STATUS.md` 并同步 `AGENTS.md` 简要状态。

### 任务 1：模型和 Migration

- [ ] 在 `tests/test_models.py` 与新 `tests/test_phase_2_3_migration.py` 写失败测试：三种版本
  状态、两个新表精确字段、status/stage/progress/check、Chunk 唯一顺序、active Job partial
  unique index、downgrade 顺序。
- [ ] 运行 `uv run pytest -q tests/test_models.py tests/test_phase_2_3_migration.py`，确认因模型/
  migration 缺失失败。
- [ ] 添加 `IngestionJob`、`DocumentChunk`、关系和 revision
  `f3a9c2d8e4b1 -> d7f6a2b4c8e1` 的最少实现。
- [ ] 重跑同一命令直到通过，再运行 `uv run ruff check app/models alembic/versions tests/test_models.py tests/test_phase_2_3_migration.py`。

### 任务 2：清洗与 Markdown Chunk 纯函数

- [ ] 创建 `tests/test_markdown_processing.py`，先定义 API：

```python
cleaned = clean_markdown(raw)
chunks = split_markdown(cleaned.content, max_characters=2000)
assert cleaned.content_hash == sha256(cleaned.content.encode("utf-8")).hexdigest()
assert chunks[0].heading_path == ("技术架构", "LangGraph")
```

- [ ] 测 BOM/NUL/换行/行尾/空行/trim、空结果异常、fence 内伪标题、段落二次拆分、稳定
  顺序和不可硬切的超长单段；运行测试并确认缺失实现导致失败。
- [ ] 在 `app/ingestion/cleaning.py` 和 `chunking.py` 编写最少纯函数，重跑测试至通过。

### 任务 3：Repository、API Service 与 Arq Queue

- [ ] 创建 `tests/test_ingestion_repository.py` 和 `tests/test_ingestion_service.py`，先测试：
  draft 原子变 processing + pending Job、active 幂等、ready 409、入队失败落库 failed 并恢复
  draft、Job/Chunk 稳定查询、SQLAlchemy/OSError 脱敏。
- [ ] 运行这两个文件，确认红灯。
- [ ] 实现 `IngestionRepository`、`IngestionService`、记录 dataclass、领域错误和
  `ArqJobQueue.enqueue(job_id)`；Arq 只传 UUID 字符串，使用 JSON serializer，创建 pool 失败
  映射为安全 QueueUnavailableError。
- [ ] 添加 `arq>=0.28,<0.29`，更新 `uv.lock`，重跑窄测试至绿灯。

### 任务 4：Worker 状态机

- [ ] 创建 `tests/test_ingestion_worker.py`，先测试完整状态序列
  `reading -> cleaning -> chunking -> saving -> completed`、空文档 failed、未知异常只存统一
  消息、保存时 Chunk 索引/hash/字符数/enabled 正确。
- [ ] 运行并确认 Worker/runner 缺失导致失败。
- [ ] 实现 Worker runner；startup 创建 Database，shutdown 关闭；注册
  `func(process_document_version_job, max_tries=1, keep_result=0)`；失败只记录安全消息并抛出。
- [ ] 重跑 Worker 和纯函数测试至通过。

### 任务 5：管理员 API 与应用装配

- [ ] 创建 `tests/test_ingestion_api.py`，先覆盖未登录、Recruiter Cookie、202 创建、GET Job、
  GET Chunks、404/409、PostgreSQL/队列脱敏 503；运行确认路由 404/依赖缺失。
- [ ] 添加 Pydantic schema、三条 admin route、AppError 映射；在 `create_app` 注入/装配
  ingestion service 和生命周期 queue close。
- [ ] 更新 DocumentVersion schema status literal；重跑 ingestion API 和既有 document API。

### 任务 6：React 管理页面

- [ ] 先修改/创建 Vitest：DocumentDetail “开始处理”并导航；Job 页面显示 processing/stage/
  progress、failed；Chunk 页面显示 index/path/content；三个入口 401 跳登录。
- [ ] 运行 `npm test -- DocumentDetail.test.tsx IngestionJob.test.tsx DocumentChunks.test.tsx`，
  确认新行为失败。
- [ ] 添加 typed API、类型、两个页面、轮询和路由；不使用 `any`、SSE、Markdown HTML 或编辑。
- [ ] 重跑窄前端测试至通过。

### 任务 7：运行方式、全量验证与检查点

- [ ] 更新 Docker worker service、配置示例和 README，仅记录本阶段能力/运行命令/边界。
- [ ] 运行后端：`uv run ruff check .`、`uv run ruff format --check .`、
  `uv run pytest -q`、`uv run alembic upgrade head`、`uv run alembic check`。
- [ ] 运行前端：`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`。
- [ ] 启动 PostgreSQL、Redis、API、Arq Worker；使用虚构管理员/项目/Markdown 真实执行登录、
  创建版本、POST process、轮询 completed、GET chunks；记录命令事实并清理精确测试数据。
- [ ] 检查禁止项：`rg` 确认没有 embedding/vector/RAG/LangGraph/Chat/SSE/发布实现。
- [ ] 获取 `git branch --show-current`、`git status --short`、`git diff --stat`，生成
  `docs/status/PHASE_2_3_STATUS.md`，同步 AGENTS.md 为 Phase 2.3 completed，重新运行必要文档/
  格式检查后停止等待 Phase 2.4 明确确认。
