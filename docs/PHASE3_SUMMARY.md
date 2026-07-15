# Phase 3 总结 — 单轮 RAG 面试 MVP

日期：2026-07-16

状态：**Phase 3 — Basic RAG interview MVP: completed**

## 交付结果

ResumeGraph 已完成 Recruiter 单轮 RAG 闭环：服务端重验证 Access Grant，原子扣减额度，使用
当前 Embedding Provider 生成 Query Vector，在 PostgreSQL/pgvector 中检索授权且已发布的有效
Chunk，再由 DeepSeek-compatible Chat Provider 生成带服务端引用 Handle 的第一人称答案。
证据不足时返回固定拒答。

用户选择 B 方案后，Phase 3 正式接入现有 Profile document scope：

- 发布的 Profile 文档对每个有效 Recruiter Grant 全局可检索；
- 发布的 Project 文档继续按 Grant 和请求项目交集过滤；
- Profile 与 Project Evidence 在同一 SQL Top-K 中排序并按 `content_hash` 去重；
- Citation 公开 `document_scope`，Profile 不伪造 Project 信息；
- 管理后台新增管理员列表、创建和安全删除，并显示文档处理、Chunk 审核、索引和发布状态。

## 关键安全边界

- 授权、发布、Chunk 和 Embedding 有效性全部在 SQL 内过滤，不委托 LLM。
- Project 请求空交集返回 403，不回退到全部项目，也不扣额度。
- Evidence Handle 由服务端生成；回答后重新验证引用对应 Chunk 仍然有效。
- `answered` 必须有合法引用；`insufficient_evidence` 必须没有引用。
- 请求额度通过 PostgreSQL 条件 `UPDATE ... RETURNING` 原子保留，并发不能超额。
- 管理员不能删除自己或最后一个管理员；管理员删除后旧 Session 因 PostgreSQL 身份复核失效。
- 页面问答历史只存在 React 内存，不进入下一次请求，也不写 localStorage。
- 公开响应不包含原始向量、完整 Chunk、Prompt、密钥、Cookie、Session Token 或推理过程。

## 最终验证

- 后端：`559 passed, 5 skipped in 21.55s`。
- 前端：`14` 个测试文件、`84 passed`；lint、typecheck、production build 通过。
- Ruff：`All checks passed!`；`158 files already formatted`。
- 真实 PostgreSQL/pgvector：`1 passed in 2.81s`；Profile 全局 + Project 授权检索、Top-K、
  发布/禁用/哈希过滤、去重、并发额度和撤销重验证通过。
- 真实 Provider：`1 passed in 6.77s`；智谱 `embedding-3` 1024 维、DeepSeek Chat
  answered/insufficient 调用通过。
- Docker：Docker Desktop / `desktop-linux` 可访问；postgres、redis、backend、worker、frontend
  均实际健康，Backend ready、Postgres readiness、Redis PONG、Worker 队列连接通过。
- Alembic：`e1b7c9d4a2f6 (head)`；`No new upgrade operations detected.`
- 真实浏览器：Profile v2 处理、3 个 Chunk 审核、真实索引和发布通过；管理员临时账号新增/删除
  通过；Grant 仅授权 ResumeGraph 时仍能回答 Profile 教育问题。
- 浏览器三问：教育和 Redis 均 answered 且引用范围正确；QPS/P99 返回固定拒答且无 Citation；
  remaining requests 为 `10 → 9 → 8 → 7`。
- 撤销：管理端显示 `3 / 10` 后撤销；旧 Recruiter Session 直接跳转 `/access`，未发生第 4 次扣减。
- 浏览器控制台：0 条 error/warning；没有发现敏感信息或内部错误泄漏。

首版短 Profile 因每个 Chunk 只有 41–53 字符，被质量规则全部禁用，索引任务正确失败并显示
`No chunks are enabled for embedding`。创建内容更完整的 v2 后，3 个 Chunk（130、126、174 字符）
全部通过并完成真实索引。这个结果说明发布流程和失败状态均真实可见。

## 测试数据清理

本轮临时管理员已删除；本轮 Profile 验收文档及其 Version、Chunk、Embedding 和任务已永久清理；
验收 Grant 已撤销并作为审计记录保留。任务开始前已存在、标题明确标注“手工验收-虚构”的
Project 文档未擅自删除。

## Phase 4 计划影响

Phase 4 不再需要安排 Profile Scope 迁移，也不需要重做管理员基础增删或文档状态可见性。新的
计划应直接继承以下事实：

1. Profile 是全局候选人知识，Project 是 Grant/request scoped 知识；
2. Citation 必须继续携带并验证 `document_scope`；
3. 当前仍是单轮 RAG，不持久化历史；
4. LangGraph、多 Agent、多轮、SSE、Query Rewrite、Hybrid Search、Reranker 和自动评估仍未实现；
5. 若 Phase 4 选择高级检索或 Agent 编排，不能放宽现有 SQL 授权、发布和引用重验证边界；
6. 测试/演示资料应让单个 Chunk 达到质量规则的最小信息量，避免“上传成功但全部被禁用”。

## 停止点

Phase 3 已完成。未执行 `git add`、Commit、Tag、Merge 或 Push；在用户确认前不开始 Phase 4。
