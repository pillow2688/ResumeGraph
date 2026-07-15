# OpenAI-Compatible Embedding 与发布闭环实现计划

**目标：** 以单一通用 OpenAI-Compatible Provider 接入智谱 `embedding-3`，把 Embedding 身份扩展为 provider/model/dimensions，并完成管理员纠偏、发布和下线 MVP。

**架构：** Worker 只接收 `EmbeddingProvider`。通用 Provider 自己拥有共享异步 Client、批次、超时、重试、响应排序和校验；Repository 在事务中使用当前活动配置完成向量保存和发布完整性验证。前端消费供应商无关 API。

**技术栈：** Python 3.12、OpenAI Async SDK、FastAPI、SQLAlchemy async、PostgreSQL/pgvector、ARQ、React/TypeScript、pytest/Vitest。

**约束：** TDD；不调用未配置 Key 的真实服务；不进入 Retriever/RAG/LangGraph；不 Commit/Tag/Push/Merge。

---

### 任务 1：通用配置与 Provider

**文件：** `app/core/config.py`、`.env.example`、`docker-compose.yml`、`app/infrastructure/embedding.py`、`app/worker.py`、`tests/test_config.py`、`tests/test_embedding_provider.py`、`tests/test_worker_entrypoint.py`

- [ ] 先写失败测试：自定义 base URL、SecretStr、dimensions 开关、index 排序、数量/维度/NaN、401、429、timeout、5xx、Client 关闭和无 Fake 回退。
- [ ] 运行聚焦测试，确认因 `OpenAICompatibleEmbeddingProvider` 和配置缺失而失败。
- [ ] 实现供应商无关错误码、共享 Client、有限批次/超时/重试与安全关闭。
- [ ] Worker 改为只依赖 `EmbeddingProvider` 并通过通用配置构造生产 Provider。
- [ ] 复跑聚焦测试确认通过。

### 任务 2：Embedding 身份与最小 Migration

**文件：** `app/models/chunk_embedding.py`、`alembic/versions/c8e4f1a7b2d9_create_phase_2_4_mvp.py`、`app/repositories/indexing.py`、`app/services/indexing_worker.py`、模型/Migration/Repository/Worker 测试

- [ ] 先写失败测试：`provider_name` 列、四字段唯一约束、保存与完成时匹配当前 provider/model/dimensions/hash。
- [ ] 确认真实本地 Phase 2.4 表无需要保留的数据，并只 downgrade 到 Phase 2.3 Revision。
- [ ] 重写尚未提交的 Phase 2.4 Migration，增加 provider_name 和新唯一约束。
- [ ] 让 Worker 把 Provider 身份传到 Repository；业务层不出现厂商专用类型。
- [ ] 运行聚焦测试以及真实 PostgreSQL upgrade/current/check。

### 任务 3：管理员 Chunk 纠偏与通用配置 API

**文件：** `app/schemas/indexing.py`、`app/repositories/publication.py`、`app/services/publication.py`、`app/api/routes/admin_ingestion.py`、`app/main.py` 及对应测试

- [ ] 先写失败测试：管理员鉴权、Chunk 启停、不可修改状态、状态回退、配置响应不含 Key。
- [ ] 实现 PATCH Chunk enabled 和 GET 当前 Embedding 配置。
- [ ] 保持路由薄、Service 不依赖 FastAPI、Repository 不包含 HTTP 语义。
- [ ] 运行 API/Service/Repository 聚焦测试。

### 任务 4：发布和下线事务

**文件：** `app/repositories/publication.py`、`app/services/publication.py`、`app/schemas/knowledge_document.py`、`app/api/routes/admin_documents.py`、`app/main.py` 及对应测试

- [ ] 先写失败测试：状态、至少一个 enabled Chunk、活动配置向量完整性、hash、旧版本 superseded、未准备新版本不影响旧发布、下线。
- [ ] 实现 publish/unpublish 事务和供应商无关 Service 错误。
- [ ] 在文档响应中暴露当前发布版本，不暴露向量或秘密。
- [ ] 运行发布聚焦测试和原有 Phase 2.2/2.3 回归测试。

### 任务 5：前端最小控制面

**文件：** `frontend/src/api/knowledgeDocuments.ts`、`frontend/src/types/knowledgeDocument.ts`、`frontend/src/pages/DocumentDetail.tsx`、`frontend/src/pages/DocumentChunks.tsx`、`frontend/src/pages/IngestionJob.tsx` 及对应 Vitest 测试

- [ ] 先写失败测试：启动索引、质量摘要/异常、Chunk 启停、Embedding stage、通用配置显示、发布/current/unpublish。
- [ ] 实现供应商无关 API client、类型和最小按钮/状态显示。
- [ ] 不增加仪表盘、Prompt/参数管理或逐 Chunk 审批流程。
- [ ] 运行前端 lint、typecheck、test 和 build。

### 任务 6：真实边界验证与阶段检查

**文件：** `README.md`、`AGENTS.md`、`docs/status/PHASE_2_4_STATUS.md`（仅在真实联调和发布闭环确实完成时创建）

- [ ] 在 Key 仅由环境变量提供时运行一个最小真实 `embedding-3` 调用，确认 1024 维且不输出正文/Key。
- [ ] 通过统一 Job 在真实 PostgreSQL 写入 pgvector，并核对 provider/model/dimensions/hash。
- [ ] 运行 Ruff、完整 pytest、Alembic、Docker Compose 和前端全套检查。
- [ ] 只有真实向量化和发布闭环均验证后才生成 Phase 2.4 checkpoint；否则明确记录阻塞项并保持阶段进行中。
