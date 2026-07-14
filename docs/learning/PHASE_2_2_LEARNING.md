# Phase 2.2 开发者学习笔记：知识文档与版本管理

## 1. 这一阶段解决了什么问题

Phase 2.1 已经能够维护 Project，但项目知识只能停留在项目名称和描述中。Phase 2.2 增加了一个最小、完整的知识录入边界：管理员可以把 Markdown 作为一份逻辑文档保存，并在内容变化时追加新版本。

本阶段的重点不是“让 AI 读懂文档”，而是先回答三个更基础的问题：

1. 这份资料属于哪个 Project？
2. 这份资料在不同时间有哪些原始版本？
3. 哪一次写入产生了哪个不可变内容快照？

只有先把这些事实可靠地保存下来，后续处理、发布和检索才有稳定的来源。

## 2. 为什么需要 `knowledge_documents`

`knowledge_documents` 表示一份跨版本保持稳定的逻辑文档，例如“ResumeGraph 架构说明”。它保存：

- 文档自己的 UUID；
- 所属 `project_id`；
- 管理员可修改的标题；
- 文档级创建时间和更新时间。

如果只保存一张版本表，调用方就缺少一个稳定的文档身份：每次修改内容都会得到新的版本 ID，标题、项目归属和“这些版本属于同一份资料”的关系只能被重复保存或由应用猜测。

把逻辑身份独立出来后，可以稳定地执行以下操作：

- 打开固定的文档详情 URL；
- 修改标题而不改写历史内容；
- 汇总版本数量和最新版本；
- 在创建新版本时锁定一个明确的父记录；
- 未来把处理和发布状态关联到明确的文档或版本。

Project 删除时也会检查 `knowledge_documents` 引用。这样不会因为删除 Project 而静默丢失知识资料。

## 3. 为什么需要 `document_versions`

`document_versions` 表示某次写入产生的原始 Markdown 快照。每个版本包含来源、原始文件名、原始内容、SHA-256、版本号、draft 状态和创建时间。

版本独立存在的价值是：

- 历史可追溯：v2 不覆盖 v1；
- 内容不可变：修改内容通过创建新版本表达，而不是 PATCH 旧内容；
- 来源可解释：能区分粘贴和 `.md` 上传；
- 重复可识别：同一文档下相同 SHA-256 被拒绝；
- 并发可约束：文档行锁与数据库唯一约束共同避免重复版本号；
- 后续处理可复现：未来系统可以明确指出处理的是哪个原始版本。

这里的“不可变”由 API 和用例边界保证：当前没有修改 `raw_content` 的接口。数据库同时约束 `(document_id, version_number)` 和 `(document_id, content_hash)` 唯一。

## 4. 文档与版本的数据关系

当前关系是：

```text
Project 1 ── N KnowledgeDocument 1 ── N DocumentVersion
```

- Project 是项目范围和 Project CRUD 的事实记录；
- Knowledge Document 是一份资料的稳定身份；
- Document Version 是该资料在某次写入时的不可变原始内容。

外键没有配置 `ON DELETE CASCADE`。当前也没有文档或版本删除 API，因此不会通过管理接口级联删除历史资料。

## 5. 一次创建文档请求的数据流

创建文档有 JSON 粘贴和 multipart 上传两个入口，但最终进入相同的业务用例。

### 5.1 Route 层

Route 负责：

- 解析 `project_id`、JSON、Form 和 `UploadFile`；
- 通过 `Depends(get_current_admin)` 验证管理员身份；
- 上传时只读取配置上限再加一个字节，以便尽早识别超限；
- 调用 Service；
- 将业务异常转换成统一 HTTP 错误；
- 通过 Pydantic response model 返回安全字段。

Route 不执行 SQL，也不决定版本号。

### 5.2 Service 层

Service 负责：

- 清理并验证标题；
- 检查 `.md` 扩展名并提取安全 basename；
- UTF-8 解码和 BOM 移除；
- 校验空白、NUL 和最大字节数；
- 计算原始内容 SHA-256；
- 选择 `pasted_markdown` 或 `markdown_file`；
- 调用 Repository 创建文档和 v1；
- 把持久化记录转换为 Pydantic 安全响应。

Service 不依赖 FastAPI Request/Response，也不直接管理驱动异常。

### 5.3 Repository 和 PostgreSQL

Repository 打开一个事务，锁定并校验 Project，然后同时新增：

1. `KnowledgeDocument`；
2. `version_number = 1`、`status = draft` 的 `DocumentVersion`。

随后 flush/refresh 并提交。任何一步失败都会回滚，所以不会出现“文档存在但 v1 不存在”的半成品。

成功响应包含文档详情、Project 摘要、版本数量和最新版本摘要，不会暴露 ORM 内部状态或内容哈希。

## 6. 一次创建新版本的数据流

创建新版本同样有粘贴和上传两个入口：

1. Route 完成 Admin 认证和 HTTP 输入读取；
2. Service 执行与 v1 相同的 Markdown 安全校验并计算 SHA-256；
3. Repository 开启事务并以 `SELECT ... FOR UPDATE` 锁定 Knowledge Document；
4. 如果文档不存在，返回 `document_not_found`；
5. 如果同一文档已有相同 `content_hash`，返回 `duplicate_document_version`；
6. 查询当前最大 `version_number`，新版本取最大值加一；
7. 插入新的 draft 版本，并刷新文档 `updated_at`；
8. 提交事务，旧版本保持不变；
9. 返回包含原始 Markdown 的新版本响应。

行锁让同一文档的版本分配串行化；数据库的版本号和内容哈希唯一约束是最后一道一致性保护。其他数据库完整性错误不会被误报成重复内容，而会被转换成脱敏的服务不可用错误。

## 7. Route–Service–Repository 分层

### Route：HTTP 边界

Route 理解 Cookie、Depends、状态码、JSON、multipart 和 response model。它不理解 SQLAlchemy 查询细节。

如果把 SQL 写进 Route，认证、HTTP、事务和数据访问会绑在一起，单元测试困难，也容易在多个入口复制不一致的业务规则。

### Service：用例与业务规则

Service 表达“创建文档”“创建版本”“修改标题”等用例，统一内容安全规则、SHA-256 和业务异常。

如果省略 Service，粘贴与上传入口很容易产生不同的校验行为，Route 也会被迫依赖数据库细节。

### Repository：持久化边界

Repository 负责 SQLAlchemy 查询、事务、行锁、排序和记录转换。它返回领域记录，不返回 FastAPI Response，也不设置 HTTP 状态码。

如果省略 Repository，Service 将直接依赖查询形状和 Session 生命周期，事务所有权与并发控制会变得分散。

## 8. PostgreSQL 在这里承担什么职责

PostgreSQL 是文档和版本的持久化事实来源，具体承担：

- 保存 Project、逻辑文档和原始版本关系；
- 用外键保证引用存在；
- 用 Check 约束保证版本号、来源和 draft 状态合法；
- 用唯一约束保证版本号与内容哈希不重复；
- 用事务保证文档和 v1 原子创建；
- 用行锁协调同一文档的并发版本分配；
- 用稳定排序、窗口函数和 `octet_length` 高效生成列表摘要。

Redis 在这条数据流中不保存文档或版本，只继续承担 Phase 1 的临时 Session 等职责。文档 CRUD 不修改 Admin Session、Recruiter Session 或 Access Grant。

## 9. 为什么现在不做 Chunk 和 Embedding

Chunk 和 Embedding 是派生数据，不是管理员提交的原始事实。过早加入会把多个尚未确认的问题耦合到一次简单的文档写入：

- Markdown 应如何清洗和标准化；
- 标题、段落和代码块如何切分；
- 如何审核、禁用或重新生成 Chunk；
- 使用哪个 Embedding 模型和维度；
- 处理失败如何重试、追踪和恢复；
- 哪个版本可以进入公开检索范围。

Phase 2.2 先建立稳定、可追溯、不可变的原始输入层。这样即使未来清洗或切分策略变化，也可以从明确的 `document_version_id` 重新生成派生数据，而不会污染原始 Markdown。

因此当前请求同步返回 `201`，没有 Job、Worker、`202 Accepted`、Chunk、Embedding 或 pgvector。

## 10. 未来如何连接 RAG

未来连接 RAG 时，边界应保持为一条从权威原文到授权检索结果的单向派生链：

```text
DocumentVersion 原始 Markdown
→ 受控处理产生可追溯的 Chunk
→ 人工确认可用范围
→ 为启用的 Chunk 生成 Embedding
→ 显式发布可检索版本
→ 按 Recruiter Session 的 allowed_project_ids 做服务端过滤
→ 检索 Chunk 并校验真实来源
→ 用检索证据生成带引用回答
```

每个未来 Chunk 都应能追溯到 `document_version_id`，每次检索都必须把请求范围与 PostgreSQL 中当前有效的授权项目取交集。未发布版本不能进入公开检索，LLM 也不能扩大项目范围、伪造文档 ID 或绕过授权。

这只是与未来 RAG 的架构连接点说明，不代表 Phase 2.3 或之后的 Job、Worker、Chunk、Embedding、发布、RAG、LangGraph、Chat 已经实现。

## 11. 当前学习边界

Phase 2.2 已经提供可靠的原始知识版本层，但仍然只有 draft Markdown。当前没有 Job、Worker、异步处理、Chunk、Embedding、pgvector、发布、RAG、LangGraph 或 Chat；进入任何后续小节都需要用户明确确认。

