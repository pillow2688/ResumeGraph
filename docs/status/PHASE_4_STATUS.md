# Phase 4 状态 — 基于 LangGraph Supervisor 的多 Agent 智能面试工作流

日期：2026-07-16

状态：**Phase 4 — Multi-agent interview workflow: completed**

Phase 5：**未开始**

## Phase 3 继承能力

Phase 4 没有重写 Phase 3 已通过真实验收的能力，而是直接复用：

- Profile 全局资料与 Grant 授权 Project 资料的 pgvector 检索；
- 当前发布 Version、enabled Chunk、Embedding provider/model/dimensions 和 `content_hash` 校验；
- 后端生成 Citation Handle、回答后的数据库重验证和最小公开 Citation；
- Recruiter Session、Access Grant、项目范围交集和 PostgreSQL 原子额度扣减；
- Profile/Project 文档上传、版本、处理、Chunk 审核、索引、发布和下线流程；
- `POST /api/v1/interview/ask` 单轮兼容接口。

## 实际数据模型调整

新增 Migration：`b4f8a1c2d3e5_phase_4_technical_knowledge.py`，上游 Revision 为
`e1b7c9d4a2f6`。

- `document_scope` 扩展为 `profile | project | technical`；
- `knowledge_documents.knowledge_status` 为非空字段：
  `implemented | planned | general_knowledge`；
- 现有 Profile/Project 文档默认保持 `implemented`；
- 数据库 Check Constraint 固定合法组合：
  - Profile：无 `project_id`，状态为 `implemented`；
  - Project：有 `project_id`，状态为 `implemented` 或 `planned`；
  - Technical：无 `project_id`，状态为 `general_knowledge`。

Downgrade 不会静默删除 Technical 或把 planned 改写为 implemented。数据库中若仍存在
Phase 3 无法表达的数据，Migration 会明确拒绝降级；管理员必须先显式清理相应业务数据。

## Technical Knowledge

Technical 资料复用完整知识处理 Pipeline：

```text
Document → Version → Cleaning → Markdown-aware Chunking
→ Quality Check → Chunk Review → Embedding → Publish
```

新增 `/api/v1/admin/technical-documents` 管理入口和 `/admin/technical-documents` 页面。
管理员可以创建或上传 Technical Markdown、查看流程状态、审核 Chunk、索引、发布、下线和
安全删除。Technical 不绑定 Project，不自动抓取网络内容，也不会由模型自动发布。

Project 文档创建时由管理员明确选择“已实现内容”或“后续规划”；LLM 无权判断实现状态。

## 统一 Evidence 与检索边界

同一个 `RetrievalRepository` / `RetrievalService` 增加三个内部受控入口：

- `search_profile_knowledge`：只检索发布的 Profile；
- `search_project_knowledge`：只检索 `requested ∩ allowed` 中的 Project；
- `search_technical_knowledge`：只检索发布的 Technical/general knowledge。

Evidence 根据 Scope/Status 确定性映射：

| Scope | Status | Knowledge Type |
| --- | --- | --- |
| profile | implemented | profile_fact |
| project | implemented | project_fact |
| project | planned | planned_solution |
| technical | general_knowledge | technical_knowledge |

Technical Evidence 只能解释通用原理，不能证明项目已实现；空 Project 交集不会回退到全部项目。
公开响应不返回内部 Chunk、数据库 UUID、向量、SQL、Prompt 或未授权项目名称。

## 五个 Agent

| Agent | 独立工具边界 | 代码强制预算 |
| --- | --- | --- |
| Interview Supervisor | 仅调用 Profile/Project/Technical/Verification Agent | 专业 Agent 最多 4 次 |
| Profile Agent | Profile overview/search | 工具最多 2 次 |
| Project RAG Agent | 授权 Project list/overview/search | 检索最多 2 次 |
| Technical Agent | Technical overview/search | 工具最多 2 次 |
| Verification Agent | Handle/Evidence/Scope/Grant 验证 | 最多 2 次 |

每个 Agent 都有独立版本化 System Prompt、严格 Pydantic 输入输出、独立局部状态、工具白名单、
有限调用循环和终止条件。结构化输出失败最多重试一次；原始模型输出不返回前端。

## LangGraph 工作流

使用 `langgraph` 1.2.x 的 `StateGraph` API：

```text
START → routing → specialists → drafting → verification
      → [repair once → verification] → finalize → END
```

类型化 `InterviewGraphState` 保存授权快照、有限对话上下文、路由、Agent 结果、Evidence Registry、
草稿、验证结果、公开状态和预算计数，不保存 Cookie、Token、Secret、完整 Prompt、Chain of
Thought 或 `reasoning_content`。

默认代码预算：Graph 12 steps、Run 90 秒、修正 1 次、最近 8 轮、Conversation TTL 1 小时。
达到预算后停止继续调用，并基于已有证据安全降级。

## 柔性回答与事实边界

内部状态为：

- `answered`；
- `answered_with_boundary`；
- `partial_answer`；
- `insufficient_evidence`；
- `access_restricted`。

前端不显示内部枚举，而是显示自然辅助说明。混合问题按“当前真实做法 → 当前边界 → 技术原理
→ 后续方案”组织；planned 不写成已完成，technical 不写成项目落地，未知指标不补全。

Verification 先执行确定性 Handle、Grant、Project Scope、当前发布版本、Chunk、Embedding 和文档
状态重验证，再执行 LLM 语义边界检查。回答最多修正一次，不重新扩大检索范围。

## Redis 有限多轮

没有创建永久 Conversation/Message 表。Redis Conversation 保存：

- Conversation ID、Recruiter Session 指纹和 Grant ID；
- 最近最多 8 轮问题/最终回答摘要；
- Conversation Summary；
- 当前项目、技术主题、轮数和过期时间。

每轮重新验证 Session、Grant 和项目范围。历史只用于指代解析，不是事实 Evidence。请求级
`request_id`、Conversation 互斥锁和 Redis 幂等记录防止重复提交；内部多个 Agent 只扣一次额度。
Grant 撤销后旧 Conversation 在下一次访问时立即失效。

## API 与 SSE

新增：

- `POST /api/v1/interview/conversations`；
- `POST /api/v1/interview/conversations/{conversation_id}/ask`；
- `POST /api/v1/interview/conversations/{conversation_id}/ask/stream`；
- `DELETE /api/v1/interview/conversations/{conversation_id}`。

SSE 使用 POST Fetch Stream 和 Starlette `StreamingResponse`，只输出白名单公开事件。心跳维持连接；
客户端断开会取消工作流并释放 Conversation 锁。失败响应脱敏，不返回 Provider 原始错误。

## 聊天式 UI

`/interview` 已升级为现代聊天界面：

- 桌面端：左侧会话栏、中间聊天区、右侧引用抽屉；
- 移动端：会话侧栏抽屉和引用底部抽屉；
- 面试官消息右侧、AI 候选人回答左侧；
- 固定多行输入框、Enter/Shift+Enter、输入法组合保护、防重复提交和停止生成；
- SSE 公开 Agent 状态、引用、复制回答、当前项目/技术主题/轮数；
- 安全 Markdown：`react-markdown` + `remark-gfm`，禁用原始 HTML；
- 消息仅在当前 React 内存和 Redis 短期 Conversation 中，不写 `localStorage`。

主要组件位于 `frontend/src/components/interview/`。

## 自动化验证结果

本轮最终检查点前的新鲜结果：

| 检查 | 实际结果 |
| --- | --- |
| `uv run pytest -q` | `629 passed, 6 skipped in 76.41s` |
| 前端 test | `16` files，`92 passed` |
| 前端 lint/typecheck/build | 全部 exit 0 |
| Vite production build | 成功；315 modules transformed |
| `uv run alembic current` | `b4f8a1c2d3e5 (head)` |
| `uv run alembic check` | `No new upgrade operations detected.` |
| `docker compose config --quiet` | exit 0 |
| Compose 服务 | PostgreSQL/Redis/Backend/Frontend healthy；Worker running |
| Phase 3 + Phase 4 live E2E | `2 passed in 119.31s` |

真实 live E2E 使用虚构资料，覆盖 Profile、Project implemented、Project planned、Technical、
QPS/P99 不虚构、三轮指代、未授权项目、单轮计费、Grant 撤销和数据清理。

## 真实浏览器验收

- 1440×900 桌面结构、欢迎状态、示例问题只填充不提交：PASS；
- Profile 问题：Profile Agent、第一人称、Profile Citation：PASS；
- 项目缓存雪崩混合问题：Project + Technical + Verification、三类引用、自然边界：PASS；
- SSE 公开状态和最终 Agent 路径：PASS；
- 390×844 移动端引用底部抽屉：PASS；
- 浏览器控制台：0 条 error/warning；
- 两轮额度 `20 → 19 → 18`，单轮仅扣一次：PASS；
- Grant 撤销后 `/interview` 重载跳转 `/access`，计数保持 2：PASS；
- 虚构 PostgreSQL、Redis Conversation、Session、Grant 和临时文件已清理。

验收时本机 TUN 直连 Provider 异常；真实 E2E 与浏览器 Backend 使用宿主机显式 Clash 代理。
这是本机网络条件，未写入仓库配置。一次临时虚构 Token 曾被浏览器工具快照显示，随后立即轮换，
并在验收结束时删除整个临时 Grant；旧 Token 已失效。

## 已知限制

- Vite 提示主 JS bundle 约 555.89 kB，属于非阻断性能优化项；
- 本阶段没有永久聊天历史、Web Search、Hybrid Search、Reranker 或自动评估平台；
- Provider 不可达时会在超时后返回脱敏错误，不退款；本机代理/TUN 配置不属于仓库；
- 未建设监控 Dashboard，只记录脱敏结构化 Agent Run 日志。

## Git 与停止状态

Phase 4 在 `main` 上完成。用户已授权创建统一 Commit，并创建
`feature/phase4-multi-agent` 快照分支，使两个分支指向同一个完成检查点。未执行 Push、Merge、
Reset、Clean、Restore 或 Rebase；`.idea/` 和无关本地文件未纳入 Phase 4。

Phase 5 未开始。后续任何评估、Hybrid Search 或 Reranker 工作都需要新的明确任务。
