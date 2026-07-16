# Phase 4.5 Public Demo Experience 设计规格

日期：2026-07-17

状态：已获用户批准实施；禁止 Commit、Push、生产部署和 ECS 操作。

## 1. 目标与范围

Phase 4.5 将根路径从管理员登录跳转改为公开的 ResumeGraph AI Interview 产品首页。访问者点击
`Start Interview` 后，由后端根据管理员维护的单例 Public Demo 配置创建现有 Recruiter Session，
随后进入原有 `/interview`。本阶段只增加公开入口配置、Session 引导与 UI 改进，不改变 RAG、
Retrieval、LangGraph、Agent、证据校验、额度扣减或授权范围计算。

## 2. 后端架构

```text
PublicDemoConfig
  -> PublicDemoRepository
  -> PublicDemoService
  -> AccessGrantService.create_session_from_grant(grant_id)
  -> Recruiter Session Cookie
  -> existing Interview API
  -> existing RAG + LangGraph workflow
```

`PublicDemoRepository` 只读写配置。`PublicDemoService` 只编排配置可用性与 Access Grant 能力。
`AccessGrantService` 不感知 Public Demo，只新增按 Grant ID 验证并创建 Session 的通用内部能力。

## 3. 数据模型

新增 `public_demo_config` 单例表：

- `id`: `SmallInteger` 主键，固定为 `1`，数据库 Check Constraint 强制单例；
- `candidate_name`: 非空、最长 200；
- `default_access_grant_id`: 非空 UUID 外键，关联 `access_grants.id`，不修改 Access Grant 表；
- `enabled`: 非空 Boolean，默认 false；
- `created_at` / `updated_at`: 带时区时间戳，数据库默认当前时间。

不存在配置时代表 Public Demo 尚未配置。Grant 不提供删除接口；外键使用默认限制行为，撤销、过期
或额度耗尽由每次公开状态读取和 Session 创建时的 Access Grant 校验处理。Migration 只创建/删除
新表，upgrade 不写入默认候选人或 Grant，不影响已有数据。

## 4. 服务与错误语义

`AccessGrantService.validate_grant_for_session(grant_id)` 复用现有 `_is_currently_valid` 规则：Grant
必须存在、未撤销、未过期、额度未耗尽且至少包含一个项目。`create_session_from_grant(grant_id)`
再次加载并验证数据库事实，然后复用现有 Recruiter Session 创建逻辑。Token exchange 保持兼容。

`PublicDemoService.get_public_status()` 在无配置、disabled 或 Grant 不可建立 Session 时返回
`available=false` 和固定中文提示 `AI Interview 尚未开放`。依赖故障仍作为脱敏 503，不伪装成业务关闭。
`create_public_session()` 对业务不可用抛出受控 `PublicDemoUnavailableError`，API 映射为 409；对数据库、
Redis 故障映射为既有脱敏 503。管理员更新在启用配置时要求 Grant 当前可建立 Session；关闭配置时
仍要求 Grant 存在，但允许管理员保存 disabled 状态后更换 Grant。

## 5. API 合同

公开接口：

- `GET /api/v1/public/demo`
  - 可用：`{"available": true, "candidate_name": "马腾飞"}`；
  - 不可用：`{"available": false, "message": "AI Interview 尚未开放"}`；
- `POST /api/v1/public/demo/session`
  - 成功设置现有名称、Path、Secure、HttpOnly、SameSite 策略的 Recruiter Cookie；
  - 返回 `{"redirect_url": "/interview"}`；
  - 不返回 Grant ID、Token、项目范围、Session Token 或私密 Grant 元数据。

管理员接口继续使用 `get_current_admin`：

- `GET /api/v1/admin/public-demo` 返回单例配置或未配置状态，并为管理员返回绑定 Grant 的安全元数据
  与当前项目范围；
- `PUT /api/v1/admin/public-demo` 全量 upsert `candidate_name`、`default_access_grant_id` 和 `enabled`。

## 6. 前端信息架构

根路由 `/` 渲染 `LandingPage`。页面加载公开状态，采用 Editorial White 方向：白色主背景、浅灰区块、
深灰文字、大留白、16-24px 圆角、轻阴影和系统字体。内容包括 ResumeGraph 品牌、AI Interview
Assistant、候选人介绍、可提问主题、LangGraph/RAG/pgvector/Multi-Agent 标签和主按钮。按钮调用
POST Session API，成功后导航 `/interview`；关闭或故障时显示友好状态，不要求姓名或访问码。

`/admin` 显式进入现有管理员入口，`/admin/public-demo` 渲染 `PublicDemoSetting`。页面通过 `Layout`
复用管理员 Cookie 认证行为，使用 `AdminCard`、Badge 和范围卡片选择默认 Grant、查看项目范围并切换
Enabled/Disabled。现有管理员页面不删除功能；共享 Admin shell 与基础颜色调整为低饱和 Apple 风格。

## 7. Interview 布局与组件

`InterviewLayout` 固定为 `100dvh` 且外层不滚动。主列使用 `min-h-0 flex-col`：Header 和 Composer
`shrink-0`，`ChatWindow` 为唯一 `min-h-0 flex-1` 区域，内部消息列表 `overflow-y-auto`。输入框始终
位于底部且不覆盖消息。新问题、Agent 进度或最终回答更新时，仅当用户处于底部附近才平滑跟随；
用户向上阅读时显示“回到底部”。

`MessageBubble` 提供左右消息壳：AI 左侧白卡，用户右侧浅灰卡。`CitationCard` 以 Source、Chunk、
知识类型和允许公开的摘要展示引用，不显示表格、内部 UUID 或 Chunk ID。已有 SSE、停止生成、重试、
安全 Markdown、Citation Drawer 和对话 API 保持不变。`ChatWindow` 组合上下文条、空状态、消息区和
Composer，支持十轮以上历史。

## 8. 测试与验证

后端采用 TDD 覆盖 Model/Migration、Repository、Service、公开 API 与管理员 API。关键分支包括：
正常配置、disabled、无配置、Grant 缺失/撤销/过期/额度耗尽、依赖故障脱敏、公开响应不泄漏 Grant
和 Token、管理员认证隔离、Cookie 安全属性及单例约束。

前端采用 Vitest/Testing Library 覆盖 Landing 状态和启动跳转、Public Demo 管理页认证/保存/范围、
路由兼容、十轮消息渲染、独立滚动区、自动滚动、左右消息与 Citation Card。最终运行 Ruff、pytest、
Alembic 检查、前端 lint/typecheck/test/build；不运行真实 Provider、不部署、不提交。

## 9. 文档与检查点

完成后更新 README，并生成 `docs/status/PHASE_4_5_STATUS.md`、
`docs/learning/PHASE_4_5_LEARNING.md` 和 `docs/architecture/PHASE_4_5_ARCHITECTURE.md`。记录真实命令
结果、Git 状态、已实现边界和限制。Phase 5 仍未开始。
