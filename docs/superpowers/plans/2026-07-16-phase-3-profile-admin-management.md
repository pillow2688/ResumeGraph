# Phase 3 Profile 与管理员管理实现计划

> 在当前工作树内按 TDD 顺序执行。用户明确禁止 commit、tag、push、merge、reset、clean、restore；计划中的每个切片以测试结果而不是 Git 提交作为检查点。

**目标：** 正式启用 Profile 全局检索，补齐安全的管理员账号管理，并改善知识生命周期入口。

**架构：** RetrievalRepository 在同一授权查询中合并 Profile 和 Grant-scoped Project 资料；Evidence/Citation 显式携带 scope。管理员管理沿用 AdminUserRepository 与 AdminAuthService 的分层模式。前端只调用新增 API，不复制后端授权或生命周期规则。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy async、PostgreSQL/pgvector、Redis、React、TypeScript、Vitest。

---

### 任务 1：Profile + Project Retrieval

**修改：**
- `app/repositories/retrieval.py`
- `app/services/retrieval.py`
- `app/services/interview.py`
- `app/schemas/interview.py`
- `frontend/src/types/interview.ts`
- `frontend/src/pages/Interview.tsx`
- `tests/test_retrieval_repository.py`
- `tests/test_retrieval_service.py`
- `tests/test_interview_service.py`
- `tests/test_interview_api.py`
- `tests/test_phase_3_postgres_integration.py`

- [ ] 先增加失败测试：Profile 无 Project 仍可检索，Project 仍要求 Grant/request scope。
- [ ] 增加失败测试：Profile/Project Citation 的 scope 与 nullable Project 字段。
- [ ] 最小修改 SQL、Evidence、Schema 和前端展示。
- [ ] 运行后端聚焦测试和 `frontend/src/pages/Interview.test.tsx`。

### 任务 2：管理员账号管理

**创建：**
- `app/api/routes/admin_users.py`
- `app/schemas/admin_user.py`
- `app/services/admin_user.py`
- `frontend/src/api/adminUsers.ts`
- `frontend/src/types/adminUser.ts`
- `frontend/src/pages/AdminUsers.tsx`
- `frontend/src/pages/AdminUsers.test.tsx`
- `tests/test_admin_user_management_api.py`
- `tests/test_admin_user_management_service.py`

**修改：**
- `app/repositories/admin_user.py`
- `app/core/exceptions.py`
- `app/main.py`
- `frontend/src/components/Layout.tsx`
- `frontend/src/router/index.tsx`

- [ ] 先增加失败测试：列表、创建、重复用户名、自删、最后管理员、删除其他管理员。
- [ ] Repository 用事务锁实现并发安全删除。
- [ ] Service/API 只返回最小管理员资料并映射脱敏错误。
- [ ] 前端新增管理员页面、创建表单和删除确认。
- [ ] 验证删除后的旧 Session 因 PostgreSQL 重验证立即失效。

### 任务 3：知识管理可见性

**修改：**
- `frontend/src/pages/ProfileDocuments.tsx`
- `frontend/src/pages/ProfileDocuments.test.tsx`
- `frontend/src/pages/ProjectDocuments.tsx`
- `frontend/src/pages/ProjectDocuments.test.tsx`
- `frontend/src/pages/DocumentDetail.tsx`
- `frontend/src/pages/DocumentDetail.test.tsx`

- [ ] 先增加失败测试：Profile 全局检索说明、发布状态、处理与发布入口、Chunk 审核入口。
- [ ] 复用现有状态字段和路由实现最小 UI 改进。
- [ ] 不新增自动发布或第二套生命周期 API。

### 任务 4：回归、真实验收与文档

**修改：**
- `AGENTS.md`
- `README.md`
- `docs/PHASE3_PLAN.md`
- `docs/PHASE3_SUMMARY.md`
- `docs/status/PHASE_3_STATUS.md`
- `docs/learning/PHASE_3_LEARNING.md`
- `docs/architecture/PHASE_3_ARCHITECTURE.md`

- [ ] 运行 Ruff、完整 pytest、Alembic current/check、Compose config 和 diff check。
- [ ] 运行前端 lint、typecheck、test、build。
- [ ] 用真实 PostgreSQL/pgvector 验证 Profile + Project 授权检索。
- [ ] 用真实浏览器验证 Profile 问答、Project 问答、Citation、管理员增删和撤销。
- [ ] 汇报对 Phase 4 的模型、权限、Citation 和前端计划影响。
