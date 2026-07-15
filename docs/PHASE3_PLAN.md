# Phase 3 — 单轮 RAG 面试 MVP 实施记录

日期：2026-07-15

状态：已实施并完成外部验收

## 1. 决策背景

Phase 3 优先交付可上线演示的单轮 RAG 闭环。实施后经用户选择 B 方案完成范围修正：候选人教育、
简介、技能、获奖、研究和求职方向使用已存在的 Profile document scope；每个有效 Recruiter Grant
默认可检索已发布 Profile，Project 资料仍按 Grant 和请求项目交集过滤。没有新增 Migration，也
没有重构 Phase 2 的生命周期或全局去重。

## 2. 本阶段交付

- PostgreSQL/pgvector 余弦距离 Top-K 检索；
- Grant 授权项目与可选请求项目的服务端交集；
- 已发布 Profile 全局检索，并在 Citation 中区分 `profile` / `project`；
- 当前发布 Version、enabled Chunk、活动 Embedding 身份和 `content_hash` 校验；
- 当前返回集按 `content_hash` 保留一条 Evidence；
- 复用现有 Embedding Provider 的 `embed_query`；
- 通用 OpenAI-compatible Chat Provider 和 DeepSeek 配置；
- 第一人称、严格 JSON、引用校验和证据不足拒答；
- `POST /api/v1/interview/ask`；
- PostgreSQL 单条 `UPDATE ... RETURNING` 原子扣减请求次数；
- Recruiter `/interview` 页面；
- 管理员列表、新增、安全删除页面，以及可见的文档处理/审核/索引/发布状态；
- 后端、前端及真实 PostgreSQL 集成测试；
- Phase 3 状态、学习、架构和总结文档。

## 3. 有效项目范围

```text
未提交 requested_project_ids
→ effective_project_ids = allowed_project_ids

提交 requested_project_ids
→ effective_project_ids = requested_project_ids ∩ allowed_project_ids

交集为空
→ 403 project_scope_forbidden，不扣额度，不执行 Provider
```

客户端项目 ID 永远是不可信输入。请求项目只收窄 Project 分支；Profile 分支对合法 Grant 始终
存在。检索 SQL 同时验证 Grant、`grant_projects`、发布指针和 Embedding 身份。

## 4. 检索不变量

一次 Recruiter 检索必须在 SQL 内同时满足：

1. Grant 未撤销且未过期；
2. KnowledgeDocument 是 `profile` 且 `project_id IS NULL`，或是已授权且位于有效请求范围的
   `project` 文档；
3. Project 分支存在对应 `grant_projects`；
4. Profile 与 Project 分支在同一 SQL Top-K 中排序；
5. `current_published_version_id` 指向被连接的 Version；
6. Version 状态为 `published`；
7. Chunk `enabled=true` 且没有禁用原因；
8. Chunk 存在 Embedding；
9. Embedding provider、model、dimensions 等于活动配置；
10. Embedding `content_hash` 等于 Chunk `content_hash`。

禁止全库检索后让 LLM 判断权限。

## 5. Evidence 和回答合同

Repository 返回数据库事实，Service 生成 `evidence_1`、`evidence_2` 等 Handle。模型看不到
Chunk、Document 或 Project UUID，只看到 Handle、正文和最小来源元数据。公开 API 只返回被
引用的项目、文档、版本和标题路径，不返回 Chunk 正文、内部 UUID 或向量。

模型只允许返回：

```json
{
  "status": "answered",
  "answer": "我在这个项目中……",
  "citation_handles": ["evidence_1"]
}
```

`answered` 至少包含一个本次合法 Handle；`insufficient_evidence` 不包含 Handle。非法结构或
伪造 Handle 最多重试一次。最终拒答固定为：

> 我目前提供的资料中没有记录这一点，因此无法给出准确回答。

## 6. 请求额度

参数、Session 和项目范围合法后，检索开始前执行单条条件更新：

```sql
UPDATE access_grants
SET request_count = request_count + 1
WHERE id = :grant_id
  AND request_count < max_requests
  AND revoked_at IS NULL
  AND expires_at > NOW()
RETURNING request_count, max_requests;
```

证据不足和 Provider 失败仍计费；参数、Session 或项目范围非法不计费；本阶段不退款。

## 7. 前端合同

`/interview` 展示当前 Grant、剩余额度和授权项目，默认选择全部项目。页面可以在 React 内存中
显示多条问答，但每次请求只发送当前问题和当前选择的项目 ID；不发送历史、不持久化、不使用
SSE。无效 Session 跳转 `/access`，页面区分拒答、额度耗尽、授权失效和服务异常。

## 8. 明确排除

- 新的 Profile 生命周期 Migration（现有 Profile scope 已正式接入检索）；
- `duplicate_of_chunk_id` 或 Phase 2 全局去重重构；
- LangGraph、多 Agent、多轮对话或持久化历史；
- SSE、Query Rewrite、Hybrid Search、Reranker；
- RAG Baseline、自动评估平台或管理员检索调试页；
- Web Search、任意工具执行或管理写操作。

## 9. 验证门槛

完成检查包括 Ruff、pytest、真实 PostgreSQL/pgvector 集成、Alembic current/check、Docker
Compose config、Git diff check，以及前端 lint、typecheck、test 和 build。真实智谱/DeepSeek、
Docker daemon、完整浏览器三问、管理员增删、Profile 发布和 Grant 撤销均已实际执行通过。
