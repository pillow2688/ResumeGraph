# Phase 3 Project-only 单轮 RAG MVP 实现计划

> **面向 AI 代理的工作者：** 在当前工作树中内联执行；用户明确禁止子代理、额外 worktree 以及 Commit、Tag、Merge、Push。每项功能遵循测试先失败、最小实现、测试转绿的节奏。

**目标：** 交付可上线演示的 Project-only 单轮 RAG 面试问答，包括安全 pgvector 检索、原子额度、严格引用、Recruiter `/interview` 页面和真实联调。

**架构：** FastAPI 依赖先从 Redis Session 定位 Grant，再由 PostgreSQL 重算授权；InterviewService 在范围校验后原子扣减额度，复用共享 EmbeddingProvider 执行 Query Embedding，通过 RetrievalRepository 在 SQL 内过滤授权与当前发布数据，再调用 OpenAI-Compatible ChatProvider。React 页面只保存当前页面生命周期内的问答，不发送或持久化历史。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy async、PostgreSQL/pgvector、Redis、OpenAI-compatible DeepSeek、React 19、TypeScript、Vitest。

---

## 文件结构

- 创建 `app/repositories/retrieval.py`：Project-only pgvector 查询、发布/Chunk/Embedding 过滤与引用重验。
- 创建 `app/services/retrieval.py`：有效项目范围、Evidence 去重、稳定 Handle 和上下文预算。
- 创建 `app/infrastructure/chat.py`：通用 ChatProvider、DeepSeek/OpenAI-compatible 实现与安全错误分类。
- 创建 `app/rag/prompt.py`：第一人称、证据约束和提示注入防护 Prompt。
- 创建 `app/schemas/interview.py`：问答请求、严格模型输出、公开 Citation 和响应契约。
- 创建 `app/services/interview.py`：额度、Embedding、Retrieval、生成、重试和 Citation 校验编排。
- 创建 `app/api/routes/interview.py`：薄路由与安全错误翻译。
- 修改 `app/repositories/access_grant.py`：增加条件 UPDATE ... RETURNING 原子额度扣减。
- 修改 `app/services/access_grant.py` 与 `app/api/dependencies/recruiter_auth.py`：为已登录但额度为零的 Session 提供只读重验证，使问答返回 429 而非误报 401。
- 修改 `app/infrastructure/embedding.py`：在现有 Provider 上增加 `embed_query`，不创建第二套 Client。
- 修改 `app/core/config.py`、`.env.example`、`docker-compose.yml`：加入有界 RAG/Chat 配置。
- 修改 `app/main.py`：生命周期内复用 Embedding/Chat Client，装配 InterviewService 和路由。
- 创建 `frontend/src/types/interview.ts`、`frontend/src/api/interview.ts`、`frontend/src/pages/Interview.tsx`：单轮问答页面和 API 契约。
- 修改 `frontend/src/router/index.tsx`、`frontend/src/pages/Portfolio.tsx`：注册 `/interview` 并提供入口。
- 创建后端与前端 Phase 3 测试；扩展现有 Provider、配置和访问控制测试。
- 创建四份 Phase 3 收尾文档并更新 `AGENTS.md`、`README.md`、`docs/PHASE3_PLAN.md` 的当前事实。

### 任务 1：锁定 Query Embedding 与 Chat 边界

- [ ] 在 `tests/test_embedding_provider.py` 增加 `embed_query` 单文本、维度校验和未配置错误测试。
- [ ] 创建 `tests/test_chat_provider.py`，覆盖严格 JSON 请求、超时/鉴权/限流/服务错误脱敏和 Client 关闭。
- [ ] 运行 `uv run pytest -q tests/test_embedding_provider.py tests/test_chat_provider.py`，确认新测试因接口缺失失败。
- [ ] 最小实现 `app/infrastructure/embedding.py` 与 `app/infrastructure/chat.py`，再次运行并确认通过。

### 任务 2：实现安全 Project-only Retriever

- [ ] 创建 `tests/test_retrieval_repository.py`，通过 SQL 编译和受控 Session 结果验证 Project/Grant、current_published_version、published、enabled、活动 Embedding 身份、content_hash 和 Top-K 排序条件。
- [ ] 创建 `tests/test_retrieval_service.py`，覆盖默认全部授权、请求交集、空交集错误、相同 content_hash 去重、稳定 Handle 与字符预算。
- [ ] 运行两份测试，确认 Repository/Service 尚不存在而失败。
- [ ] 最小实现 `app/repositories/retrieval.py` 与 `app/services/retrieval.py`，运行两份测试转绿。

### 任务 3：实现原子额度和单轮 InterviewService

- [ ] 扩展 `tests/test_access_grant_repository.py` 并创建 PostgreSQL 并发集成用例，验证单条条件 UPDATE ... RETURNING 和并发不超额。
- [ ] 创建 `tests/test_interview_service.py`，覆盖扣减时机、无证据拒答、合法回答、伪造 Handle 重试一次、引用重验、Provider 失败不退款与错误脱敏。
- [ ] 运行相关测试，确认原子消费和服务缺失导致预期失败。
- [ ] 实现 `consume_request`、Prompt、InterviewService 和配置约束，运行相关测试转绿。

### 任务 4：实现 Interview API

- [ ] 创建 `tests/test_interview_api.py`，覆盖未登录、撤销、过期、额度耗尽、未授权项目、参数错误不扣、成功/拒答响应和 Provider 503 安全错误。
- [ ] 运行 API 测试，确认 `/api/v1/interview/ask` 尚未注册而失败。
- [ ] 实现 Schema、依赖、路由、异常与 `create_app` 生命周期装配。
- [ ] 运行 Interview API 与 Phase 1 Access Grant API 测试，确认新旧行为同时通过。

### 任务 5：实现 `/interview` 单轮页面

- [ ] 创建 `frontend/src/pages/Interview.test.tsx`，覆盖有效/无效 Session、默认和手动项目选择、成功引用、证据不足、额度耗尽、服务错误、防重复提交、登出及历史不进入后续请求。
- [ ] 扩展 Portfolio/Router 测试，验证 Recruiter 可进入 `/interview` 且现有页面保留。
- [ ] 运行 `npm test -- --run src/pages/Interview.test.tsx`，确认组件和路由缺失而失败。
- [ ] 实现类型、API、页面、路由和 Portfolio 入口，运行前端相关测试转绿。

### 任务 6：真实 PostgreSQL/pgvector 与 Docker 验收

- [ ] 创建 `tests/test_phase_3_postgres_integration.py`，使用虚构的“候选人简历与个人背景”和 ResumeGraph Project 建立 Grant、当前发布版本、Chunk 与向量。
- [ ] 验证教育/项目检索只返回授权已发布内容、性能指标问答拒答、额度递增且撤销后旧 Session 无效；所有临时记录使用精确 ID 清理。
- [ ] 运行 Docker Compose 配置和服务，执行 Alembic upgrade/current/check 与真实集成测试；若 Live Provider 环境变量已配置，再运行显式启用的真实 Embedding/Chat 验收。

### 任务 7：文档与完整验证

- [ ] 创建 `docs/status/PHASE_3_STATUS.md`、`docs/learning/PHASE_3_LEARNING.md`、`docs/architecture/PHASE_3_ARCHITECTURE.md`、`docs/PHASE3_SUMMARY.md`，只记录实际命令和事实。
- [ ] 更新 `AGENTS.md` 为 `Phase 3 — Basic RAG interview MVP: completed`，并明确 Project-only 临时方案、单轮、无 LangGraph/多 Agent。
- [ ] 更新 `README.md` 与 `docs/PHASE3_PLAN.md`，移除被本次批准规格否决的 Phase 3 Profile/admin retrieval 实施要求。
- [ ] 运行后端 Ruff、format check、完整 pytest、Alembic current/check、Docker Compose config、`git diff --check`。
- [ ] 运行前端 lint、typecheck、test、build。
- [ ] 审计 `git status --short --branch`、`git diff --stat` 和禁止项关键词，记录结果后停止等待用户确认。
