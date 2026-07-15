# Phase 2 数据生命周期最小补丁设计

日期：2026-07-15

状态：用户已批准；Phase 3 保持暂停

## 目标

在不建立第二套文档 Pipeline、复杂质量平台或 `duplicate_of_chunk_id` 的前提下，让现有
Document → Version → Chunk → Quality → Embedding → Publish 链路同时支持全局 Profile 文档和
Project 文档，并补齐当前发布范围内的精确去重、下线、版本删除和文档永久删除。

## 范围边界

- 本任务仍属于 Phase 2 收尾，不新增 Phase 编号。
- 不实现 Retriever、RAG、Chat、LangGraph、SSE 或 `/interview`。
- 不创建虚拟 Profile Project，不创建第二套 Worker、Job、Chunk 或 Publication Service。
- 不执行 Commit、Tag、Merge、Push、Reset、Clean、Restore 或 Rebase。
- 保留既有 `AGENTS.md`、`docs/PHASE3_PLAN.md` 和 `.idea/` 用户修改，只做本任务明确要求的纠偏。

## 数据模型

### KnowledgeDocument

新增 `document_scope`，只允许 `profile` 和 `project`。现有数据迁移为 `project`。
`project_id` 改为可空，并增加数据库约束：

```text
scope = project → project_id IS NOT NULL
scope = profile → project_id IS NULL
```

Profile 和 Project 文档继续共享 Version、Job、Chunk、Embedding 与发布指针。

### DocumentChunk 禁用来源

新增最小字段 `disabled_reason`：

- `NULL`：当前启用；
- `hard_block`：确定性安全规则阻断；
- `exact_duplicate`：当前发布范围精确重复；
- `quality`：非安全类质量判断自动禁用；
- `administrator`：管理员明确禁用。

数据库约束保证 `enabled=true` 时 `disabled_reason IS NULL`，`enabled=false` 时必须有原因。迁移按
现有 `quality_issues`、`auto_indexable` 和 `enabled` 安全回填。去重重建只会自动恢复
`exact_duplicate`，不会恢复 `hard_block`、`quality` 或 `administrator`。

### 索引与级联

新增面向当前发布范围和 Hash 分组的组合索引；将 `document_versions.document_id` 外键修正为
`ON DELETE CASCADE`。Document 删除前先清空当前发布指针，之后由数据库级联删除 Version、Job、
Chunk 和 Embedding。

## Profile 管理

KnowledgeDocument Repository/Service 接受显式 scope：

- Project 创建仍验证 Project 存在；
- Profile 创建强制 `project_id=None`；
- 新增 Profile 列表、粘贴创建和上传创建 API；
- 通用详情、版本、处理、索引、Chunk 与发布 API 同时服务两种 scope；
- Profile 详情返回 `project=null`，Project 详情保持原契约；
- 管理接口继续只接受 Admin Cookie，Recruiter Cookie 不能调用。

列表响应增加当前发布版本统计：Chunk 总数、enabled、exact duplicate、hard block 和 Embedding
数量。统计只针对 `current_published_version_id`。

## 精确去重重建

`DeduplicationService.rebuild_scope()` 接受 `profile` 或 `(project, project_id)`。Repository 只读取
该范围所有 `current_published_version_id` 指向且状态为 `published` 的 Chunk。

候选只包括：

- 当前启用 Chunk；或
- 仅因 `exact_duplicate` 自动禁用的 Chunk。

`hard_block`、`quality` 和 `administrator` 禁用项不会成为 canonical。候选按 `content_hash` 分组，
每组以 `(created_at, chunk_id)` 升序选择 canonical：

- canonical 清除 `exact_duplicate` Issue，设为 enabled；
- 其他成员增加规范化 `exact_duplicate` Issue，设为禁用；
- 重复成员的 Embedding 被删除；
- canonical 保留当前 provider/model/dimensions/content_hash 对应向量；
- canonical 缺失当前向量时，Service 通过现有 `EmbeddingProvider.embed_texts` 对经过确定性规则脱敏
  的相同内容补向量，然后才启用；
- Apply 阶段重新校验当前发布指针和 Hash，避免对过期快照写入；冲突时有限重试；
- 相同输入重复执行结果不变。

不同 Project 永远分开重建；所有 Profile 文档共享一个全局范围。只按完全相同的标准化
`content_hash` 去重，不做语义、LLM 或向量相似去重。

## 发布、下线与删除

发布仍保持现有顺序：新版本完成索引并通过完整性校验后才切换指针，旧版本在此之前继续有效。
发布成功后重建所属 scope。

下线只清空 `current_published_version_id` 并把旧当前版本改为 `superseded`，保留全部历史数据，随后
重建所属 scope。

版本删除：

- 只允许 `draft`、`indexing_failed`、`ready_to_publish`、`superseded`，以及没有活动 Job 的失败
  状态；
- 当前发布版本必须先下线或被替换；
- `pending/processing` Job 返回 409；
- 删除 Version 后由级联清理 Job、Chunk 和 Embedding。

KnowledgeDocument 永久删除：

- Admin API 与前端危险二次确认；
- 有活动 Job 返回 409；
- 清空发布指针后删除 Document，级联全部下属数据；
- 删除完成后重建受影响 scope。

## 前端

新增 `/admin/profile-documents`，复用 `Layout`、API Client、Cookie 和 Markdown 创建对话框。页面
显示多份 Profile 文档及当前发布统计。点击文档进入通用详情页。

通用详情页根据 `document_scope` 切换返回链接和归属文案，新增：

- 下线普通确认；
- 合法非当前版本删除；
- 永久删除危险二次确认；
- 活动任务冲突和服务错误的脱敏提示。

不创建 `/interview` 或任何 Phase 3 UI。

## 错误与安全

- 约束、scope、版本状态和活动 Job 由数据库/Repository 强制，而非仅靠 UI。
- 409 区分活动 Job、当前发布版本和非法删除状态。
- 503 不返回 SQL、原始异常、Provider 响应或秘密。
- Profile 管理仍使用独立 Admin Principal；Recruiter Principal 没有写入口。
- Hard Secret 内容不因去重、发布或删除重建重新启用或外发。

## 验证

采用 TDD 覆盖模型/迁移、Profile API、禁用来源、稳定 canonical、范围隔离、向量唯一性、发布切换、
下线保留、版本/文档级联、活动 Job 冲突和管理员前端。完成前运行全量 Ruff、pytest、Alembic、
Compose、前端 lint/typecheck/test/build 与 `git diff --check`，并用虚构 Profile 数据在真实 PostgreSQL
完成升级、生命周期和清理验收。
