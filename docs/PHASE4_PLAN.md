# ResumeGraph Phase 4 实施计划

## 1. 阶段目标

Phase 4 在已经通过真实验收的 Phase 3 基线上，将单轮 Profile + Project RAG 面试问答升级为受权限约束、可验证、有限多轮的 LangGraph 多 Agent 工作流，并将 `/interview` 升级为现代聊天界面。

本阶段作为一个完整阶段交付，不拆分为 4.1、4.2 等子阶段。实现期间可以按可运行的纵向切片推进，但只有后端、前端、测试、真实验收和阶段文档全部完成后，才形成一个 Phase 4 检查点。

Phase 4 直接在 `main` 上开发。完成后是否创建 Commit、Tag 和快照分支由用户确认；实施过程不自动执行 Git 集成操作。

## 2. 已确认基线与事实差异

Phase 4 直接复用以下 Phase 3 能力：

- Profile 全局资料与 Project Grant 范围资料的同一条受控 pgvector 检索；
- 当前发布版本、启用 Chunk、Embedding 身份与 `content_hash` 一致性过滤；
- Citation Handle、回答后数据库重验证与原子 `request_count` 扣减；
- Recruiter Session、Access Grant、管理员文档处理和发布工作流；
- 现有 `/api/v1/interview/ask` 兼容接口及前端认证边界。

当前代码只有 `profile` 和 `project` 两种 `document_scope`。现有 Chunk 质量元数据中的 `knowledge_type` 是模型生成的内容分类，不能可靠表达某项能力是否已经在项目中实现。Phase 4 因此增加最小的管理员控制字段 `knowledge_status`，不使用 LLM 判断实现状态。

旧版产品文档中“单 Agent”或“助手不使用第一人称”的描述与当前 Phase 3 实现及本阶段明确需求不一致。本阶段以当前代码、数据库、测试、最新阶段文档和本计划为准，同时继续遵守不冒充真人、不虚构经历、只使用授权证据等安全边界。界面会明确标识这是 AI 候选人助手。

## 3. 范围边界

本阶段实现：

- Technical 技术知识库；
- `implemented`、`planned`、`general_knowledge` 的确定性知识状态；
- Interview Supervisor、Profile、Project RAG、Technical、Verification 五个 Agent；
- LangGraph 有限状态工作流、工具白名单、调用预算和一次回答修正；
- 柔性回答状态与事实/原理/规划表达边界；
- Redis 短期 Conversation、请求幂等与有限上下文；
- POST SSE 公共进度事件；
- 桌面和移动端聊天式 `/interview`；
- 自动化验证、真实环境验收和 Phase 4 文档。

本阶段不实现 Phase 5、自动检索评估、BM25、Hybrid Search、Reranker、Web Search、任意 SQL/Shell/Python/浏览器工具、无限 ReAct/Reflection、永久聊天历史、语音、监控 Dashboard 或未来阶段空模块。

## 4. 数据模型与 Migration

创建新的 Alembic Migration，不修改既有 Migration：

1. `knowledge_documents.document_scope` 扩展为 `profile | project | technical`。
2. 新增非空 `knowledge_status`：`implemented | planned | general_knowledge`。
3. 现有 Profile 和 Project 文档迁移为 `implemented`，保持现有数据语义。
4. 数据库约束固定合法组合：
   - Profile：`project_id IS NULL` 且 `knowledge_status = implemented`；
   - Project：`project_id IS NOT NULL` 且状态为 `implemented` 或 `planned`；
   - Technical：`project_id IS NULL` 且 `knowledge_status = general_knowledge`。
5. downgrade 恢复 Phase 3 约束；降级前删除 Phase 4 Technical 文档并将 Project planned 状态恢复为 implemented，避免产生 Phase 3 无法表达的数据。

`knowledge_type` 不作为单独持久化真相，而由服务端确定性映射：

| Scope | Status | Evidence 类型 |
| --- | --- | --- |
| profile | implemented | profile_fact |
| project | implemented | project_fact |
| project | planned | planned_solution |
| technical | general_knowledge | technical_knowledge |

## 5. Technical 文档管理

扩展当前 Knowledge Document 服务、Repository、Schema、管理员路由和前端页面，不创建第二套版本、Chunk、Embedding、Job 或发布流程。

- Profile 创建固定为 `implemented`；
- Project 创建时管理员明确选择 `implemented` 或 `planned`；
- Technical 创建固定并验证为 `general_knowledge`；
- Technical 支持 Markdown 粘贴、上传、处理、Chunk 审核、索引、发布、下线和安全删除；
- Document Detail、Chunk 审核和工作流状态展示 Scope 与知识状态；
- Technical 不绑定 Project，不自动联网抓取，也不由模型自动生成后发布。

## 6. 检索与统一 Evidence

扩展现有 `RetrievalRepository` 和 `RetrievalService`，保留 Phase 3 联合检索行为及 SQL 权限条件，并提供内部受控入口：

- `search_profile_knowledge`：只查发布的 Profile；
- `search_project_knowledge`：只查 `requested_project_ids ∩ allowed_project_ids` 内的 Project；
- `search_technical_knowledge`：只查发布的 Technical/general knowledge。

三个入口共享当前发布版本、Chunk enabled、Embedding provider/model/dimensions/hash、文档状态、去重和回答后重验证条件。空项目交集不回退到全部项目。Technical 只能解释原理，不能证明项目已经落地。

扩展现有 Evidence/Citation，增加 `knowledge_type` 和 `knowledge_status`。内部保留数据库标识以便验证，公开响应只返回 Citation Handle 和允许展示的来源摘要，绝不返回数据库 UUID、完整 Chunk、向量、SQL、未授权项目或私有 Agent 状态。

## 7. LangGraph 与五个 Agent

仅增加一个兼容当前 Python 版本的 LangGraph 依赖，使用当前稳定的低级 `StateGraph` API，不引入第二套 Agent 框架或废弃 API。

使用类型化 `InterviewGraphState` 保存运行标识、授权快照、有限对话上下文、路由结果、Agent 结果、Evidence Registry、草稿、验证结果、最终响应和代码预算计数。State 不保存 Secret、Cookie、Token、完整 Prompt、Chain of Thought 或 `reasoning_content`。

每个 Agent 拥有独立版本化 System Prompt、输入/输出 Pydantic Schema、局部状态、工具白名单、代码强制调用上限和明确终止条件：

- Supervisor：只可调用四个专业 Agent 工具，负责有限路由、拆分、汇总、起草和一次修正；
- Profile Agent：只可调用 Profile overview/search，最多两次工具调用；
- Project Agent：只可调用授权项目 list/overview/search，最多两次检索和一次查询改写；
- Technical Agent：只可调用 Technical overview/search，最多两次工具调用，并明确通用原理边界；
- Verification Agent：只可调用 Handle、Evidence、Scope、Grant 验证工具，最多执行两次，不生成最终回答。

模型通过严格 JSON 动作 Schema 选择白名单工具或结束；未知字段、工具、状态、Agent 名称和项目 ID 均拒绝。结构化输出失败最多重试一次，仍失败则安全降级。工具结果作为不可信数据注入 Prompt，文档指令不得覆盖系统规则。

LangGraph 主链路：

```text
START
→ 接收并解析上下文
→ Supervisor 路由
→ 有限调用 Profile / Project / Technical Agent
→ Supervisor 起草
→ Verification
→ 条件式修正一次
→ 必要时第二次 Verification
→ 最终化
→ END
```

Settings 强制 Supervisor 专业 Agent 调用数、各 Agent 工具数、Verification 次数、修正次数、Graph steps、总超时、Conversation turns/TTL/摘要长度。达到预算时停止并根据已有 Evidence 返回部分回答或安全拒答。

## 8. 柔性回答与 Verification

最终内部状态为 `answered`、`answered_with_boundary`、`partial_answer`、`insufficient_evidence` 或 `access_restricted`。前端不直接展示枚举，而转换为自然说明。

回答严格按证据类型表达：

- `profile_fact` 可陈述个人经历；
- `project_fact` 可陈述项目已实现内容；
- `technical_knowledge` 只能作为通用原理；
- `planned_solution` 必须明确尚未落地或属于后续考虑；
- 未知内容不得补全。

Verification 先执行确定性 Handle、Grant、Project Scope、发布版本、Chunk、Embedding 和文档状态检查，再执行 LLM 语义检查，识别无证据结论、实现/规划边界混淆、虚构指标、职责夸大、提示词泄漏等问题。修正不得扩大权限或重新检索全部资料。

## 9. Redis Conversation、幂等与额度

不创建 Conversation/Message 数据库表。Redis 只保存短期 Conversation：所有者 Session 指纹、Grant、最近有限轮次摘要、会话摘要、当前项目/技术主题和 TTL。

每轮通过 Recruiter 依赖重新验证 Session 和 Grant，并重新计算项目范围。Conversation 所有权不匹配、TTL 到期或 Grant 撤销立即失效；历史仅用于指代解析，不能作为事实 Evidence。

每个问题携带客户端生成的 `request_id`。Redis 幂等记录和 Conversation 级互斥锁防止重复提交及并发越额：

- 参数、Session、Grant、Conversation 所有权和项目范围错误不扣额度；
- 合法问题进入工作流前调用现有 PostgreSQL 原子扣减一次；
- 内部多个 Agent、部分回答或证据不足不重复扣减；
- Provider 错误不退款；同一 `request_id` 重试不再次扣减；
- 锁与幂等状态在取消、异常和 SSE 断开时由 `finally` 安全释放或记录。

## 10. API 与 SSE

保留 Phase 3 `POST /api/v1/interview/ask` 的请求和响应契约，新增：

- `POST /api/v1/interview/conversations`；
- `POST /api/v1/interview/conversations/{conversation_id}/ask`；
- `POST /api/v1/interview/conversations/{conversation_id}/ask/stream`；
- `DELETE /api/v1/interview/conversations/{conversation_id}`。

SSE 使用 FastAPI/Starlette `StreamingResponse` 和异步队列实现 POST Fetch Stream，不增加重型流式依赖。仅输出白名单公共事件、时间、进度、自然状态文案和最终公开响应；心跳不携带私有状态。客户端断开时取消后续无意义工作并释放资源。

## 11. 聊天式前端

将现有单文件表单页面重构为职责清晰的聊天组件：

- `InterviewLayout`、`ConversationSidebar`、`InterviewHeader`；
- `ChatMessageList`、`UserMessageBubble`、`AssistantMessage`；
- `AgentProgress`、`CitationList`、`CitationDrawer`；
- `ChatComposer`、`WelcomeSuggestions`、`ScrollToBottomButton`。

桌面端为左侧会话栏、中间聊天区和按需引用抽屉；移动端侧栏与引用改为抽屉。用户消息右侧，AI 候选人回答左侧，底部固定自适应输入框，支持 Enter/Shift+Enter/输入法组合、防重复发送、停止生成、平滑滚动和回到底部。

前端在内存保存当前页面消息，不使用 `localStorage`，不伪装永久历史。新建 Conversation 会删除旧 Redis Conversation 并清除页面上下文，但不清除 Recruiter Session 或 Grant。

Markdown 只通过安全解析器渲染允许的结构，不启用原始 HTML。引用以紧凑标记和安全摘要呈现，桌面右侧抽屉、移动端底部抽屉。公开 Agent 路径只显示“查询项目资料”等自然步骤，不展示 Prompt、内部消息、查询参数或推理过程。

## 12. 测试先行实施顺序

所有纵向切片遵循“先写失败测试，再实现，再重构”：

1. 数据模型、Migration、Schema 和 Technical 文档管理；
2. Technical/Profile/Project 检索隔离及统一 Evidence；
3. 独立 Prompt、Agent Schema、工具白名单和调用预算；
4. LangGraph 路由、混合问题、Verification、修正和柔性回答；
5. Redis Conversation、所有权、TTL、撤销、幂等与单次计费；
6. Conversation API、SSE 顺序、脱敏、取消和错误恢复；
7. 前端 API、流解析、聊天组件、引用、滚动、移动端和可访问性；
8. Phase 0～3 回归、真实 PostgreSQL/pgvector/Redis/Provider/Docker/浏览器验收；
9. Phase 4 状态、学习、架构、总结文档及 AGENTS.md 完成标记。

单元测试使用确定性 Fake，不调用真实 Provider。真实集成和端到端验收单独执行、单独记录，外部环境阻断时不得虚报通过。

## 13. 验证与交付记录

完成前至少执行仓库实际支持的以下命令：

```text
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run alembic upgrade head
uv run alembic current
uv run alembic check
docker compose -f docker-compose.yml config --quiet
npm run lint
npm run typecheck
npm run test
npm run build
git diff --check
```

还需记录真实 PostgreSQL/pgvector、Redis Conversation、LangGraph、SSE、Provider、桌面浏览器和手机尺寸验收结果。虚构验收资料必须与真实候选人资料隔离，并在验收后清理。

完成后生成：

- `docs/status/PHASE_4_STATUS.md`；
- `docs/learning/PHASE_4_LEARNING.md`；
- `docs/architecture/PHASE_4_ARCHITECTURE.md`；
- `docs/PHASE4_SUMMARY.md`；
- 更新 `AGENTS.md` 为 Phase 4 已完成并链接上述文档。

最终报告数据模型、Technical、五个 Agent、LangGraph、权限边界、柔性回答、Redis 多轮、SSE、聊天 UI、自动化测试、真实验收和 Git 状态，并明确 Phase 5 未开始。随后停止等待用户确认 Git Commit、Tag 和快照分支。
