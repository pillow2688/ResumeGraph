# ResumeGraph Phase 2 总结 — Knowledge-base construction

Date: 2026-07-15
Status: Phase 2 completed; next phase not started

Related records:

- [Phase 2 final implementation route](PHASE2_PLAN.md)
- [Phase 2.1 status](status/PHASE_2_1_STATUS.md)
- [Phase 2.2 status](status/PHASE_2_2_STATUS.md)
- [Phase 2.3 status](status/PHASE_2_3_STATUS.md)
- [Phase 2.4 status](status/PHASE_2_4_STATUS.md)
- [Phase 2.4 learning notes](learning/PHASE_2_4_LEARNING.md)
- [Phase 2.4 architecture](architecture/PHASE_2_4_ARCHITECTURE.md)

## 1. Phase 2 目标与最终结果

Phase 2 的目标是让管理员把候选人的项目材料安全地建设为可版本化、可异步处理、可判断、
可向量化并可显式发布的知识库。

最终链路为：

```text
Project
→ Knowledge Document
→ Document Version
→ Ingestion Job
→ Cleaning
→ Chunking
→ Rule Check
→ DeepSeek Indexability Check
→ Embedding
→ PostgreSQL + pgvector
→ Publish / Supersede / Unpublish
```

Phase 2.1～2.4 已把这条管理员链路闭环。当前系统已经拥有可发布的向量知识，但还没有
面试官问题检索或答案生成能力。

## 2. Phase 2.1 — 项目管理与访问入口

Phase 2.1 完成：

- 管理员 Project CRUD；
- Access Grant 引用下的 Project 删除保护；
- 管理员 Project 和 Access Grant 管理页面；
- 一次性 Access Token 展示和安全清除；
- Recruiter Token Exchange 入口；
- Recruiter 授权项目页面；
- Admin/Recruiter 独立 Cookie、Redis Session 和前后端联调。

它让后续知识资料拥有明确的 Project 归属，并继续保持 PostgreSQL 服务端授权范围。

## 3. Phase 2.2 — 文档与不可变版本

Phase 2.2 完成：

- `knowledge_documents` 逻辑文档；
- `document_versions` 递增且内容不可变的版本；
- Markdown 粘贴和 `.md` 上传；
- 文档列表、详情、标题编辑、创建新版本和版本查看页面；
- 文件大小、UTF-8、扩展名、NUL、文件名和重复内容安全校验；
- 原始 Markdown 字面预览，不执行 HTML 或脚本。

管理员修改正文的方式是创建 v2、v3，而不是原地修改旧版本。这为旧发布版本持续有效和原子
版本切换提供了基础。

## 4. Phase 2.3 — 异步处理与 Chunk

Phase 2.3 完成：

- PostgreSQL `ingestion_jobs`；
- Redis + ARQ 和独立 Worker；
- `202 Accepted + job_id` 长任务接口；
- 确定性 Markdown 清洗；
- Markdown-aware Chunking；
- `document_chunks`、稳定 Chunk 顺序、标题路径、字符数和 SHA-256 `content_hash`；
- Job 状态/进度接口和页面；
- Chunk 查看页面；
- 成功后 `draft → processing → ready_for_review`。

API 只创建和查询 Job；Worker 在请求之外完成耗时处理；PostgreSQL 保存耐久状态，Redis 只投递
Job UUID。

## 5. Phase 2.4 — 知识增强、Embedding、pgvector 与发布

Phase 2.4 完成：

- LLM 前的确定性 Rule Check；
- Hard Secret 不外发；
- 手机号/邮箱 Warning、外发前脱敏并默认不索引；
- `too_long` Chunking 回归 Warning；
- DeepSeek V4 Pro 严格 JSON/Pydantic 索引判断和最小 Metadata；
- 当前批次 Chunk ID 完整匹配；
- `auto_indexable` 自动建议和 `enabled` 管理员最终开关；
- 通用 `EmbeddingProvider`、OpenAI-compatible 实现、Fake 和 Unconfigured 实现；
- 智谱 `embedding-3`、1024 维、批大小 10；
- PostgreSQL pgvector 和 `chunk_embeddings`；
- provider/model/dimensions/content hash 完整性；
- 单一 `knowledge_indexing` Job；
- `ready_to_publish`、`published`、`superseded`；
- `current_published_version_id`、原子版本切换和文档下线；
- 管理员索引、判断摘要、异常 Chunk、启停、Job 阶段、发布和下线页面。

没有创建独立质量表、质量分数、Prompt 管理、复杂审批、质量平台、厂商专用 Provider 或分裂的
Quality/Embedding Job。

## 6. 管理员当前可完成的完整流程

管理员现在可以：

1. 使用独立管理员 Cookie 登录；
2. 创建和管理 Project；
3. 创建 Knowledge Document；
4. 粘贴 Markdown 或上传 `.md` 生成 v1；
5. 启动异步 document processing；
6. 查看清洗、Chunking Job 进度和生成的 Chunks；
7. 启动统一 knowledge indexing；
8. 查看 Rule Check 和 DeepSeek 判断、issues 与 metadata；
9. 简单启用或禁用 Chunk，并在修改后重新索引；
10. 查看 Embedding 阶段和当前非秘密配置；
11. 在完整性通过后显式发布；
12. 创建和处理 v2，且在 v2 完成前保持 v1 有效；
13. 原子发布 v2，使 v1 变为 superseded；
14. 将文档下线。

## 7. Recruiter 当前仍然只能做什么

Recruiter 可以用有效 Access Grant 建立独立 Session，查看授权范围、剩余次数、到期时间和授权
Project 基础信息。Grant 被撤销后，旧 Session 会被 PostgreSQL 重校验立即拒绝。

Recruiter 还不能：

- 搜索已发布 Chunks；
- 提问或获得 RAG 回答；
- 使用 Chat、SSE 或多轮对话；
- 查看管理员 Chunk 判断、Job 或未发布版本；
- 创建、修改、索引、发布或删除资料。

“知识已发布”仅建立未来检索可使用的权威版本关系，不等于面试官问答已经存在。

## 8. 主要数据库实体

| 实体 | 作用 |
| --- | --- |
| `projects` | 项目基础事实和知识文档归属。 |
| `access_grants` / `grant_projects` | Recruiter 授权、配额、有效期、撤销与项目范围。 |
| `knowledge_documents` | 逻辑文档及 `current_published_version_id`。 |
| `document_versions` | 不可变 Markdown 版本和处理/发布状态。 |
| `ingestion_jobs` | `document_processing` 与 `knowledge_indexing` 耐久 Job。 |
| `document_chunks` | 清洗切分结果、自动判断、issues、metadata 和最终 enabled 开关。 |
| `chunk_embeddings` | pgvector 向量、provider、model、dimensions 和 Chunk hash 身份。 |

Phase 2.4 Migration 为 `c8e4f1a7b2d9`，基于 Phase 2.3 的 `f3a9c2d8e4b1`，未改写已应用的
Phase 0～2.3 Migration。

## 9. PostgreSQL、Redis、Worker 和外部模型职责

- PostgreSQL 是用户、Project、Grant、Document、Version、Job、Chunk、Embedding 身份和发布
  关系的事实来源，并在同一事务内执行发布完整性和版本切换；
- pgvector 在 PostgreSQL 内保存向量，本阶段没有执行相似度查询；
- Redis 保存临时 Admin/Recruiter Session、限流计数和 ARQ 队列，不保存唯一发布事实；
- FastAPI 提供短请求 API，不在请求线程里清洗、调用模型或批量向量化；
- Worker 执行确定性清洗、Chunking、规则、DeepSeek、Embedding 和保存；
- DeepSeek 只做最小结构化索引建议，不生成向量、不改正文、不创建权限；
- OpenAI-compatible Embedding Provider 只把允许的 enabled 文本转换为固定维度向量。

## 10. 主要前端页面

- `/admin/login`：管理员登录；
- `/admin/projects`：Project 管理；
- `/admin/projects/:projectId/documents`：项目文档列表和创建；
- `/admin/documents/:documentId`：文档、版本、处理、发布状态和下线；
- `/admin/jobs/:jobId`：document processing / knowledge indexing 阶段和进度；
- `/admin/document-versions/:versionId/chunks`：Chunk、质量摘要、metadata 和启停；
- `/admin/access-grants`：授权管理；
- `/access`：Recruiter Token Exchange；
- `/portfolio`：Recruiter 当前授权信息和 Project 范围。

运行时代码不使用 Mock 生产数据；Vitest mock 只隔离前端测试。

## 11. Phase 2 安全约束

- 管理员和 Recruiter 认证、Cookie、Session、Principal 和 Depends 始终分离；
- raw Access Token 只在创建 Grant 时显示一次，数据库只保存摘要；
- Recruiter 范围由 PostgreSQL 服务端查询决定，前端或模型不能扩大权限；
- 未发布版本、禁用 Chunk 和无有效当前配置 Embedding 的数据不能通过发布完整性；
- Hard Secret 在外部调用前阻断，PII 在外发前脱敏；
- API Key 使用 `SecretStr` 和环境变量，不返回前端、不进入日志或 Git；
- DeepSeek JSON 严格校验，当前批次 ID 缺失、额外或重复都会拒绝；
- 外部模型调用使用有限批次、有限超时和有限重试；
- Fake Provider 不会成为生产静默回退；
- Public/Recruiter 侧没有写工具，也没有 Retriever、Web Search 或任意执行能力。

## 12. 完整验证与真实联调证据

2026-07-15 的 Phase 2 最终回归结果：

- `uv run ruff check .`：通过；
- `uv run ruff format --check .`：通过，125 files already formatted；
- `uv run pytest -q`：459 passed，2 skipped，42.11 seconds；
- Alembic upgrade/current/check：通过，当前为 `c8e4f1a7b2d9 (head)`，无待生成操作；
- Docker Compose 配置：通过；
- 前端 lint、typecheck 和 build：通过；
- 前端 Vitest：11 files、63 tests passed；
- `git diff --check`：通过。
- 非收费的真实 PostgreSQL/pgvector 发布/下线边界使用 Fake Embedding 复跑：1 passed；
- Docker Compose 中 Backend、Worker 正常运行，PostgreSQL、Redis healthy；HTTP liveness 为
  `live`，readiness 为 `ready`。

Phase 2.4 已经执行过以下真实联调，本次总结不重复调用外部收费 API：

- DeepSeek V4 Pro 对虚构技术文本完成严格结构化判断，Thinking 关闭，Chunk ID 与批次匹配；
- 智谱 `embedding-3` 返回并通过 1024 维校验，向量写入真实 PostgreSQL/pgvector；
- 统一 Job 走通
  `ready_for_review → indexing → ready_to_publish → published → superseded`；
- 发布、当前版本切换和下线完成，Embedding `content_hash` 与 Chunk 一致；
- 联调测试数据已清理，没有遗留孤立 `chunk_embeddings`。

## 13. 当前尚未实现和已知限制

明确未实现：

- Retriever；
- pgvector 相似度检索；
- RAG 答案与引用组装；
- LangGraph；
- Chat、SSE 和多轮对话；
- BM25、RRF、Reranker；
- Web Search；
- PDF、Word、OCR、网页抓取和对象存储。

已知运行限制：

- ARQ Job 当前没有 transactional outbox；API 在 PostgreSQL commit 后、Redis enqueue 前硬崩溃
  可能留下 pending Job，管理员可通过重复请求恢复投递；
- Worker 被硬终止时无法执行 graceful failure cleanup，没有 lease sweeper；
- Markdown Chunking 只识别当前实现支持的 ATX headings 等结构，2,000 字符是语义目标而非
  强行切断所有 fenced block 的绝对上限；
- 文档/版本列表仍是当前 MVP 的全量列表，没有分页、筛选或搜索；
- 已发布知识目前没有任何 Recruiter 检索消费者。

## 14. Phase 2 涵盖的工程知识

后端与数据工程：

- FastAPI 分层、Pydantic 外部边界、SQLAlchemy async Repository/Service；
- Alembic 增量 Migration、数据库 Check/Unique/Foreign Key 与事务锁；
- PostgreSQL 作为事实来源、pgvector 向量持久化和 content hash 身份；
- Redis Session、限流和 ARQ 队列的临时职责；
- 202 Job API、幂等活动任务、Worker 生命周期、超时与有限重试；
- 原子版本发布与旧版本持续可用。

前端工程：

- React Router 管理页面、统一 Fetch Client、Cookie credentials；
- loading/empty/error/success 状态；
- 文档、版本、Job、Chunk 和发布状态展示；
- Vitest 组件/API 隔离测试、TypeScript typecheck 和 Vite build。

AI 工程与安全：

- 规则优先于 LLM；
- 秘密阻断与 PII 脱敏；
- 严格结构化输出与服务器批次 ID 校验；
- Quality 模型与 Embedding 模型职责分离；
- 通用 Provider Protocol、共享异步 Client 和供应商无关错误；
- 自动建议与管理员最终开关分离；
- 向量完成与显式发布分离。

## 15. 停止条件

Phase 2 已完成，下一阶段尚未开始。未经用户新的明确确认，不得实现 Retriever、RAG、
LangGraph、Chat、SSE 或下一阶段的设计。完成本总结不授权 Commit、Tag、Push 或 Merge。
