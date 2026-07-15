# Phase 2 数据生命周期最小补丁实现计划

> **面向 AI 代理的工作者：** 在当前会话内按 TDD 红—绿—重构执行；用户禁止任何 Commit、Tag、
> Merge 或 Push，因此计划中的检查点只记录测试证据，不执行 Git 集成。

**目标：** 为现有 Phase 2 Pipeline 增加 Profile scope、当前发布范围精确去重、下线与安全删除，
并完成管理员 Profile 管理页面和文档纠偏。

**架构：** 扩展现有 KnowledgeDocument 和 DocumentChunk，不建立平行模型。新增专注的
Deduplication Repository/Service 与 Knowledge Lifecycle 删除用例；通用处理、索引和发布链路保持
唯一。Profile 页面复用现有文档详情与任务页面。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy async、Alembic、PostgreSQL/pgvector、
pytest、React 19、TypeScript、Vitest。

---

## 文件结构

- 创建 `alembic/versions/e1b7c9d4a2f6_phase_2_lifecycle_patch.py`：scope、禁用来源、索引和级联。
- 修改 `app/models/knowledge_document.py`、`document_chunk.py`、`document_version.py`：模型事实。
- 修改 `app/repositories/knowledge_document.py`、`app/services/knowledge_document.py`：通用 scope 创建、
  Profile 列表和统计。
- 创建 `app/repositories/deduplication.py`、`app/services/deduplication.py`：幂等范围重建。
- 创建 `app/repositories/knowledge_lifecycle.py`、`app/services/knowledge_lifecycle.py`：版本和文档删除。
- 修改 `app/repositories/publication.py`、`app/services/publication.py`：禁用来源和重建触发。
- 修改 `app/services/indexing_worker.py`、`app/repositories/indexing.py`：持久化安全禁用来源。
- 修改 `app/api/routes/admin_documents.py`、`admin_publication.py`、`app/main.py`：Profile 与生命周期 API。
- 修改 `app/schemas/knowledge_document.py`、`ingestion.py`、`publication.py`：scope、统计、删除契约。
- 创建 `frontend/src/pages/ProfileDocuments.tsx` 及测试，扩展文档 API、类型、路由和导航。
- 修改 `frontend/src/pages/DocumentDetail.tsx` 及测试：scope 文案、下线确认与删除。
- 更新 Phase 2/Phase 3 事实文档和 `AGENTS.md`。

### 任务 1：模型和 Migration

- [ ] 在 `tests/test_models.py` 和新建 `tests/test_phase_2_lifecycle_migration.py` 中先断言
  `document_scope`、可空 `project_id`、scope Check、`disabled_reason`、一致性 Check、索引和级联。
- [ ] 运行 `uv run pytest -q tests/test_models.py tests/test_phase_2_lifecycle_migration.py`，确认因字段和
  Migration 缺失而失败。
- [ ] 最小修改模型并新增 Migration；旧 Migration 不改。
- [ ] 重跑聚焦测试，确认通过。

### 任务 2：Profile 文档后端

- [ ] 先扩展 Repository/Service/API 测试，覆盖多份 Profile 粘贴/上传、`project_id=None`、Project
  兼容、Admin/Recruiter 隔离和当前发布统计。
- [ ] 运行聚焦测试，确认新 API/字段缺失导致失败。
- [ ] 泛化 KnowledgeDocument Record、查询和创建方法，新增 `/api/v1/admin/profile-documents` 三个
  接口；通用详情和版本接口保持复用。
- [ ] 重跑聚焦测试并修复现有 Project 文档回归。

### 任务 3：禁用来源与索引兼容

- [ ] 先扩展 Quality/Indexing/Publication 测试，覆盖 hard block、quality、exact duplicate 和管理员
  禁用来源，确认管理员禁用不会被重新索引恢复。
- [ ] 运行聚焦测试，确认 `disabled_reason` 尚未传播而失败。
- [ ] 扩展 Chunk Record、Worker 更新、Embedding 选择和管理员开关；禁止自动恢复 hard block 和
  administrator 禁用。
- [ ] 重跑质量、索引和发布全套聚焦测试。

### 任务 4：范围级精确去重

- [ ] 新建 `tests/test_deduplication_repository.py` 和 `tests/test_deduplication_service.py`，先覆盖
  Profile 全局、同 Project、跨 Project 隔离、Hash 精确性、稳定 canonical、幂等、Hard Block、
  管理员禁用、Embedding 清理和缺失向量补齐。
- [ ] 运行测试，确认模块缺失而失败。
- [ ] 实现结构化 scope/candidate/plan，Repository 安全加载与条件应用，Service 使用当前
  EmbeddingProvider 补齐 canonical 向量。
- [ ] 重跑聚焦测试，确认所有边界通过。

### 任务 5：发布、下线与版本切换触发

- [ ] 先扩展 Publication Repository/Service/API 测试，覆盖 v1 在 v2 发布前仍 current、发布后
  superseded、scope 重建调用、下线保留历史和重建幂等。
- [ ] 运行测试，确认尚未编排重建而失败。
- [ ] 将 DeduplicationService 注入 PublicationService；成功发布/下线后按文档 scope 重建。
- [ ] 重跑聚焦测试并验证 Provider/Repository 错误保持脱敏。

### 任务 6：版本删除和文档永久删除

- [ ] 新建 Lifecycle Repository/Service/API 测试，覆盖允许状态、当前版本拒绝、活动 Job 409、
  Version 级联、Document 全级联、二次确认契约和删除后重建。
- [ ] 运行测试，确认删除用例缺失而失败。
- [ ] 实现 `DELETE /api/v1/admin/document-versions/{version_id}` 与
  `DELETE /api/v1/admin/documents/{document_id}`；永久删除的精确标题确认放在 JSON body 的
  `confirmation_title` 字段中，避免标题进入 URL 和访问日志，Route 保持薄层。
- [ ] 重跑聚焦测试和旧文档/项目删除测试。

### 任务 7：管理员 Profile 前端

- [ ] 先创建 `ProfileDocuments.test.tsx` 并扩展 `DocumentDetail.test.tsx`、`Layout.test.tsx`，覆盖
  列表统计、创建/上传、Profile 文案、下线确认、版本删除、永久删除二次确认、401/409/503。
- [ ] 运行 Vitest 聚焦命令，确认页面/API 缺失而失败。
- [ ] 实现类型、API、`/admin/profile-documents`、导航和通用详情生命周期交互。
- [ ] 运行聚焦 Vitest、TypeScript 和 ESLint，修复现有页面回归。

### 任务 8：真实 PostgreSQL 与 Migration 验收

- [ ] 扩展 opt-in PostgreSQL 集成测试，使用虚构 Profile A/B 验证重复、v2 切换、下线、永久删除、
  canonical 重选、向量保留/补齐和精确清理。
- [ ] 执行 Alembic upgrade/current/check；在隔离测试数据库验证 downgrade 后重新 upgrade。
- [ ] 执行 opt-in 生命周期真实验收；只按本次 UUID 清理，不 reset/truncate 既有数据。

### 任务 9：文档纠偏与全量验证

- [ ] 更新 `docs/PHASE2_PLAN.md`、`PHASE2_SUMMARY.md`、Phase 2.4 status/learning/architecture、
  `AGENTS.md` 和 `docs/PHASE3_PLAN.md`，明确 Phase 3 尚未开始且未来检索含 Profile + 授权 Project。
- [ ] 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest -q`。
- [ ] 运行 Alembic、Compose、前端 lint/typecheck/test/build 与 `git diff --check`。
- [ ] 记录真实退出码、测试数量、Git 分支/status/stat、`.idea/` 和其他无关修改，然后停止等待确认。
