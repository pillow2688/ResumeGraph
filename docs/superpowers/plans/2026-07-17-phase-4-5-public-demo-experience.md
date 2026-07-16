# Phase 4.5 Public Demo Experience 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 在当前会话逐任务实现。用户明确禁止 Commit，因此所有步骤只编辑、测试和记录，不执行 Git Commit。

**目标：** 在现有 Access Grant 和 Interview 之上增加安全的公开 Demo 入口，并修复/升级公开聊天与管理员 UI。

**架构：** 新增单例 PublicDemoConfig、Repository、Service 和公开/管理员 API；PublicDemoService 调用 AccessGrantService 的通用按 Grant 建立 Session 能力，不进入 RAG 或 Agent。React 增加 Landing/Public Demo 管理组件，并将 Interview 调整为唯一消息滚动区的固定视口布局。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2 async、Alembic、React 19、TypeScript、React Router、Tailwind CSS、pytest、Vitest。

---

## 文件结构

**新增后端文件**

- `app/models/public_demo_config.py`：单例 ORM 模型。
- `app/repositories/public_demo.py`：配置查询和 upsert。
- `app/schemas/public_demo.py`：公开及管理员 Pydantic 合同。
- `app/services/public_demo.py`：配置与 Grant/Session 编排。
- `app/api/routes/public_demo.py`：公开状态与 Session API。
- `app/api/routes/admin_public_demo.py`：管理员配置 API。
- `alembic/versions/c7d9e2f4a6b8_phase_4_5_public_demo.py`：单例表 Migration。
- `tests/test_public_demo_*.py`：模型、Migration、Repository、Service、API 测试。

**新增前端文件**

- `frontend/src/types/publicDemo.ts`、`frontend/src/api/publicDemo.ts`：类型和 API。
- `frontend/src/pages/LandingPage.tsx`：公开首页。
- `frontend/src/pages/PublicDemoSetting.tsx`：管理员配置页。
- `frontend/src/components/AdminCard.tsx`：共享管理员卡片。
- `frontend/src/components/interview/ChatWindow.tsx`：固定视口聊天组合。
- `frontend/src/components/interview/MessageBubble.tsx`：左右消息壳。
- `frontend/src/components/interview/CitationCard.tsx`：引用卡。
- 对应 `*.test.tsx`：页面和组件行为测试。

**修改文件**

- `app/models/__init__.py`、`app/main.py`、`app/services/access_grant.py`、`app/core/exceptions.py`：注册模型/服务/路由，增加通用 Session 能力与受控错误。
- `frontend/src/router/index.tsx`、`frontend/src/components/Layout.tsx`、Interview 现有组件、`frontend/src/index.css`：路由、导航、布局与主题。
- `README.md` 与 Phase 4.5 状态/学习/架构文档：记录事实和验证。

### 任务 1：Access Grant 通用 Session 扩展

- [ ] 在 `tests/test_access_grant_service.py` 添加失败测试：`validate_grant_for_session` 和 `create_session_from_grant` 对有效、缺失、撤销、过期、耗尽 Grant 的行为；验证新 Session 不消费问题额度。
- [ ] 运行 `uv run pytest tests/test_access_grant_service.py -q`，确认因方法缺失失败。
- [ ] 在 `app/services/access_grant.py` 提取仅在 Service 内复用的记录验证和 Session 创建方法，实现两个通用方法，不加入 public-demo 命名或分支。
- [ ] 重跑同一测试，确认通过并保持 Token exchange 行为。

### 任务 2：单例 Model 与 Migration

- [ ] 新建 `tests/test_public_demo_model.py` 与 `tests/test_public_demo_migration.py`，断言字段、FK、`id=1` Check Constraint、upgrade/downgrade 和 Revision 链。
- [ ] 运行两文件，确认因模型/Migration 缺失失败。
- [ ] 新建 ORM 模型和 Revision `c7d9e2f4a6b8`，只创建 `public_demo_config`；在 `app/models/__init__.py` 导出。
- [ ] 重跑测试，确认通过。

### 任务 3：Repository

- [ ] 新建 `tests/test_public_demo_repository.py`，使用数据库 Session fake/SQLAlchemy 测试模式覆盖 get、首次 upsert、更新固定行和故障翻译。
- [ ] 运行测试，确认模块缺失失败。
- [ ] 实现 `PublicDemoRecord`、`PublicDemoRepository.get()` 和 `upsert()`；Repository 不导入 AccessGrantService、Session 或 RAG。
- [ ] 重跑测试，确认通过。

### 任务 4：Service 与 Schema

- [ ] 新建 `tests/test_public_demo_service.py`，用 fake repository/access service 覆盖正常、disabled、无配置、缺失/撤销/过期/耗尽 Grant、admin update 与依赖故障。
- [ ] 运行测试，确认失败。
- [ ] 新建 Pydantic 合同和 `PublicDemoService`，固定关闭提示，编排 Grant 校验与 `create_session_from_grant`，不复制授权规则。
- [ ] 重跑测试，确认通过。

### 任务 5：公开与管理员 API

- [ ] 新建 `tests/test_public_demo_api.py`，覆盖公开 GET/POST、Cookie 属性、响应脱敏、不可用 409、管理员 GET/PUT、管理员/Recruiter Cookie 隔离。
- [ ] 运行测试，确认路由缺失失败。
- [ ] 新建两组路由、受控异常映射，并在 `create_app` 注入/注册 `PublicDemoService`；保持测试可注入 fake service。
- [ ] 重跑 API 测试与 `tests/test_access_grant_api.py`，确认兼容。

### 任务 6：Landing Page

- [ ] 新建 `LandingPage.test.tsx`、`publicDemo` API client 测试，覆盖可用、不可用、加载/错误、点击 POST 后跳转且 URL 无 Grant。
- [ ] 运行 `npm test -- LandingPage`，确认组件缺失失败。
- [ ] 新建类型、API client、`LandingPage`，把 `/` 指向公开首页；增加 `/admin` 到现有管理员入口的显式路由。
- [ ] 重跑相关前端测试，确认通过。

### 任务 7：管理员 Public Demo 页面

- [ ] 新建 `PublicDemoSetting.test.tsx`，覆盖认证跳转、加载当前配置/Grant/范围、切换、保存、错误脱敏。
- [ ] 运行定向测试，确认失败。
- [ ] 新建 `AdminCard` 与 `PublicDemoSetting`，复用 `listAccessGrants` 和管理员 Layout；在 Router/Layout 增加 `/admin/public-demo`。
- [ ] 重跑页面与 Layout 测试，确认通过。

### 任务 8：Interview 滚动和组件化

- [ ] 扩展 `Interview.test.tsx` 并增加组件测试：十轮消息、唯一 overflow-y-auto 消息区、底部 Composer、`scrollTo` 自动跟随、用户右/AI 左、Citation Card 的 Source/Chunk。
- [ ] 运行定向测试，确认现有布局不满足新断言。
- [ ] 实现 `ChatWindow`、`MessageBubble`、`CitationCard`；调整 `InterviewLayout`、`Interview.tsx`、消息和 Composer 组件的 `min-h-0`/`shrink-0`/neutral styles，保留 SSE/API。
- [ ] 重跑 Interview 全部测试，确认通过。

### 任务 9：统一 UI 与回归

- [ ] 更新 `index.css` 设计基础、Admin `Layout` 和当前共用 Card/Badge/Timeline 表现，移除公开主流程的高饱和 cyan 与重阴影，不删除已有操作。
- [ ] 运行全部前端测试，修复仅由样式/可访问名称变化造成的回归。
- [ ] 运行 `npm run lint`、`npm run typecheck`、`npm test`、`npm run build`。

### 任务 10：后端全量、Migration 与文档检查点

- [ ] 运行 `uv run ruff check .` 和 `uv run ruff format --check .`，修复本阶段文件问题。
- [ ] 运行 `uv run pytest -q`，记录 pass/skip/耗时。
- [ ] 在可用数据库环境运行 `uv run alembic current`、`uv run alembic check`；若环境不可用，记录真实阻塞，不推断成功。
- [ ] 更新 README，并新增 Phase 4.5 status/learning/architecture 文档，写入实际结果、限制、Git branch/status/diff summary。
- [ ] 运行 `git status --short --branch` 与 `git diff --stat`；确认未修改生产配置、未 Commit、未 Push、未部署。
