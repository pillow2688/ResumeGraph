# Phase 3 Profile 与管理员管理修正设计

日期：2026-07-16

状态：用户已选择方案 B 并授权实施；不得进入 Phase 4。

## 目标

修正管理端与 Interview 知识边界不一致的问题：已发布 Profile 资料应作为候选人全局背景对每个有效 Recruiter 可检索，Project 资料仍严格受 Access Grant 与请求项目范围约束。同时补齐管理员账号列表、新增和安全删除，并让文档处理、Chunk 审核、索引和发布入口在管理页面中清晰可见。

## Profile 检索合同

- `profile` 文档不属于 Project，`project_id` 必须为空。
- 只有存在当前发布 Version、Version 状态为 `published`、Chunk 启用且 Embedding 身份和 `content_hash` 有效的 Profile 才能进入检索。
- 每个未撤销、未过期且未耗尽前置校验的 Recruiter Grant 都可以检索已发布 Profile；LLM 不参与授权判断。
- `project` 文档继续要求 Project 同时属于 Grant 授权范围和本次请求范围。
- `requested_project_ids` 只缩小 Project 资料范围；合法请求中的 Profile 始终可用。请求包含未授权 Project 时仍按现有规则拒绝，不回退。
- Profile 与 Project 结果在 PostgreSQL 中统一按 pgvector 距离排序，并在当前返回集按 `content_hash` 去重。
- Evidence/Citation 增加 `document_scope`。Profile Citation 的 `project_id`、`project_name` 为空；前端显示“候选人 Profile”。Project Citation 继续返回 Project 标识和名称。

## 管理员账号合同

- 新增 `GET/POST/DELETE /api/v1/admin/users`，只允许当前有效管理员调用。
- 创建复用现有用户名规范化、Argon2 密码哈希和重复用户名校验；响应不含密码或哈希。
- 所有管理员暂时同权限，不引入角色、邀请、邮箱或密码重置。
- 禁止删除当前登录管理员。
- 禁止删除系统最后一个管理员。
- 删除管理员后，旧 Redis Session 即使仍等待 TTL，也会因每次请求重新查询 PostgreSQL 管理员而立即失效。
- 删除的并发安全由数据库事务内锁定管理员集合保证，不能并发删成零管理员。

## 管理端 UX

- 导航保留并明确标注“Profile 全局资料”，增加“管理员账号”。
- Profile 页面说明其资料会进入每个有效 Recruiter 的 Interview 检索。
- Project 文档列表和 Profile 列表显示当前发布状态、最新版本状态及下一步操作。
- 文档卡片提供“处理与发布”入口；存在可审核 Chunk 的版本时提供“审核 Chunk”入口。
- 文档详情继续作为唯一执行处理、索引、发布和下线的页面，不新增第二套生命周期 API。

## 非目标

- 不新增数据库 Migration；现有 `document_scope` 与 nullable `project_id` 已足够。
- 不实现 RBAC、超级管理员、管理员邀请、密码重置或审计平台。
- 不实现自动处理/自动发布流水线；发布仍由管理员显式确认。
- 不实现 LangGraph、多 Agent、多轮、SSE、Query Rewrite、Reranker 或自动评估。

## 验收

- Profile 与授权 Project 可在一次检索中共同参与 Top-K；未授权 Project 永不返回。
- Profile Citation 不伪造 Project UUID，前端能正确展示。
- 管理员可列表、新增和删除其他管理员；自删与删最后一个被拒绝。
- 被删除管理员的旧 Session 立即失效。
- Profile/Project 管理页面能看出当前发布状态和下一步操作。
- 既有 Phase 0～3 测试、Ruff、Alembic、Compose、前端 lint/typecheck/test/build 继续通过。
