# Phase 2 — 知识库构建与发布

本文是 Phase 2 的高层开发地图，用于固定各小节的目标、先后边界和全局约束，不是各小节的详细开发任务书。任何小节开始前仍须由用户明确确认范围；计划中的能力在对应小节完成并通过真实验证前，不得视为已经实现。

## 1. Phase 2 的目标

Phase 2 负责建立以下知识库生产与发布流程：

```text
管理员维护项目
→ 创建项目知识文档
→ 管理文档版本
→ 异步清洗和切分 Chunk
→ 人工审核 Chunk
→ 生成 Embedding
→ 保存到 PostgreSQL + pgvector
→ 显式发布知识版本
```

Phase 2 完成后，系统应具备可管理、可审核、可版本化、可向量化、可发布的知识库。Phase 2 尚不实现面试官问答、RAG Answer Generation 或 LangGraph。

## 2. 技术职责

| 组件 | Phase 2 职责 |
| --- | --- |
| PostgreSQL | 保存项目、逻辑文档、文档版本、Chunk、持久化任务和发布状态，是这些业务数据的事实来源。 |
| pgvector | 保存 Chunk Embedding，并与 PostgreSQL 中权威的 Chunk 和版本元数据保持关联。 |
| Redis | 可用于任务队列或临时任务协调，不保存唯一的文档事实或发布事实。 |
| FastAPI | 提供受管理员认证保护的项目、文档、审核和发布 API。 |
| Worker | 在 API 请求之外执行清洗、切分和 Embedding 等耗时处理。 |
| Embedding Provider | 将审核通过且启用的 Chunk 转换为向量。 |

具体 Worker 框架、Embedding 服务、模型和运行参数必须在对应小节开始前由用户确认，本高层规划不预先固定这些选择。

## 3. Phase 2 小节

### Phase 2.1 — Project management

目标：

- 实现管理员 Project CRUD。
- 复用 Phase 1 已有的 `Project` Model。
- Project 被 Access Grant 引用时禁止删除，不能通过删除项目静默改变已有 Grant 的授权范围。
- 验证项目管理行为与 Phase 1 的管理员认证、Grant 关系和权限重验证兼容。

本小节不得实现文档、Chunk、Embedding、RAG 或 LangGraph。

### Phase 2.2 — Knowledge documents and versions

目标：

- 建立逻辑文档与文档版本。
- 第一版只支持 Markdown 文本和 `.md` 文件。
- 只保存通过最小安全校验的原始 Markdown；标准化内容留到 Phase 2.3。
- 支持同一逻辑文档的多个版本。
- 所有版本在本小节都固定为 `draft`，不建立发布状态或当前发布版本。
- 提供管理员 FastAPI API 和 React 管理页面，用于创建、列表、详情、改标题、
  新建版本和安全预览原始 Markdown。

本小节不得实现 Job、Worker、异步处理、文本清洗、PDF、OCR、Chunk、Embedding、
pgvector 或发布。

### Phase 2.3 — Asynchronous cleaning and chunking

目标：

- 建立持久化 Job。
- 长任务 API 使用 `202 Accepted + job_id`。
- Worker 执行确定性的文本清洗。
- 按 Markdown 标题和段落切分 Chunk。
- 处理完成后进入 `ready_for_review`。
- API 进程不承担长时间文档处理。

本小节不得调用 LLM，不得生成 Embedding，不得自动发布。具体 Worker 框架必须在本小节开始前由用户确认。

### Phase 2.4 — Chunk review and freeze

目标：

- 延续 Phase 2.3 已有的只读 Chunk 预览。
- 管理员可以禁用错误、隐私或无意义 Chunk。
- 审核确认后冻结待向量化版本。
- 原始内容有误时通过新文档版本修正，不直接随意篡改 Chunk。

本小节不得实现向量检索或 RAG。

### Phase 2.5 — Embedding and pgvector

目标：

- 启用并使用 pgvector。
- 封装 Embedding Provider 边界。
- 对 enabled Chunk 批量生成向量。
- 保存模型名称、向量维度和 content hash。
- 支持失败状态和安全重试。
- 验证所有可用 Chunk 都具有匹配向量。

具体 Embedding 服务、模型、维度和批量大小必须在本小节开始前由用户确认。本小节不得实现面试官查询、RAG Answer Generation 或 LangGraph。

### Phase 2.6 — Publication and version switching

目标：

- 只有审核和向量化均完成的版本才能发布。
- 同一逻辑文档只能有一个当前发布版本。
- 发布新版本时，旧发布版本变为 `superseded`。
- 新版本未准备完成前，旧发布版本继续可用。
- 支持下线文档。
- 为未来检索建立明确的数据库过滤条件。

本小节不得实现实际 RAG 查询接口。

## 4. Phase 2 最终验收流程

Phase 2 整体预期验收流程如下；只有对应小节真实完成并验证后，步骤才可被标记为已实现：

```text
管理员登录
→ 创建项目
→ 创建知识文档
→ 上传 Markdown v1
→ 获得 job_id
→ Worker 清洗和切分
→ 管理员审核 Chunk
→ 生成 Embedding
→ 发布 v1
→ 上传 v2
→ v1 继续有效
→ 审核并向量化 v2
→ 发布 v2
→ v1 变为 superseded
→ 下线文档
```

## 5. Phase 2 全局硬约束

- 不实现面试官问答。
- 不实现 RAG Answer Generation。
- 不实现 LangGraph。
- 不实现 Chat 或 SSE。
- 不实现面试官问答前端；管理员前端只按已明确确认的小节范围实现。
- 不支持 PDF、Word、OCR 和网页抓取。
- 不使用 LLM 清洗内容或决定发布状态。
- 所有管理接口必须使用 Phase 1 已有的 `get_current_admin`。
- Recruiter 不得创建、修改、审核、发布或删除任何项目知识资料。
- PostgreSQL 是文档、版本、Chunk、任务和发布状态的事实来源。
- Redis 不是文档或发布状态的事实来源。
- 未发布资料不得进入未来 Recruiter 检索范围。
- 不得提前实现尚未获得用户确认的小节。
- 任何规划变更必须先获得用户确认。

## 6. 小节状态检查点规则

每完成一个 Phase 2 小节，必须执行以下流程：

```text
运行真实测试和检查
→ 生成 docs/status/PHASE_2_X_STATUS.md
→ 更新 AGENTS.md 当前简要状态
→ 展示 Git 状态和 Diff
→ 停止等待用户确认
```

状态文档至少必须包含：

- 本节目标。
- 实际完成内容。
- 新增和修改的主要文件。
- 当前系统新增的可用能力。
- 当前尚未实现的内容。
- 实际执行的测试和检查结果。
- 已知限制和非阻断问题。
- 当前 Git 分支、工作区状态和 Diff 摘要。
- 下一小节允许范围与明确禁止提前实现的范围。

状态记录必须来自实际代码和真实命令结果，不能依据计划猜测。状态文档生成后不得自动进入下一小节，也不得因此自动 Commit 或 Tag；必须停止并等待用户明确确认。
