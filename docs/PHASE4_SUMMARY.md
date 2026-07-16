# Phase 4 总结 — LangGraph Supervisor 多 Agent 智能面试

日期：2026-07-16

状态：**completed；Phase 5 未开始**

## 交付结果

ResumeGraph 已从 Phase 3 的 Profile + Grant-scoped Project 单轮 RAG，升级为受后端授权、证据和
调用预算约束的多 Agent 面试工作流：

- Technical 技术知识库复用现有知识处理与发布 Pipeline；
- `implemented / planned / general_knowledge` 由管理员明确维护；
- Interview Supervisor、Profile、Project RAG、Technical、Verification 五个 Agent；
- LangGraph `StateGraph` 编排、严格 Schema、独立 Prompt/工具/局部状态和代码预算；
- 项目事实、通用技术原理和后续方案的确定性表达边界；
- `answered_with_boundary`、partial 和自然权限表达；
- Redis 短期 Conversation、有限上下文、幂等和互斥锁；
- Conversation JSON API 与 POST SSE 公开状态；
- GPT/Claude 风格但不复制品牌的桌面/移动聊天 UI；
- Phase 3 `/api/v1/interview/ask` 保持兼容。

## 安全边界

- PostgreSQL 仍是 Grant、项目范围、发布状态和知识的事实源；
- Profile/Technical 对有效 Grant 全局可检索，Project 始终使用请求范围与 Grant 范围交集；
- Supervisor 和 LLM 无权扩大 `allowed_project_ids`；
- Technical 不能证明项目实现，Planned 不能描述为完成；
- Citation Handle、当前发布版本、Chunk、Embedding、文档和 Grant 在回答后重新验证；
- 前端不接收内部 Evidence、数据库 UUID、Prompt、工具参数、SQL 或 Chain of Thought；
- Conversation 历史只用于指代解析，不是事实 Evidence；
- 每个合法问题只原子扣减一次额度。

## 主要文件

- Migration：`alembic/versions/b4f8a1c2d3e5_phase_4_technical_knowledge.py`
- Agent：`app/agent/`
- Redis Conversation：`app/infrastructure/interview_conversation.py`
- Workflow：`app/services/interview_workflow.py`
- Conversation Schema：`app/schemas/interview_conversation.py`
- SSE/API：`app/api/routes/interview.py`
- Technical 管理：`app/api/routes/admin_documents.py`、`frontend/src/pages/TechnicalDocuments.tsx`
- 聊天 UI：`frontend/src/components/interview/`、`frontend/src/pages/Interview.tsx`
- 测试：`tests/test_*agent*`、`tests/test_interview_*`、`tests/test_phase_4_*`

## 验证摘要

- 后端全量：`629 passed, 6 skipped in 76.41s`；
- 前端：`16` 个测试文件、`92 passed`，lint/typecheck/build 通过；
- Alembic：`b4f8a1c2d3e5 (head)`，无待生成迁移；
- Docker Compose：五服务运行，核心服务健康；
- 真实 Phase 3 + Phase 4 E2E：`2 passed in 119.31s`；
- 真实浏览器：桌面/手机、Profile、混合边界、SSE、三类引用、额度和撤销通过；
- 验收虚构数据、Redis Conversation、Session 和 Grant 已清理。

本机 TUN 直连 Provider 在最终验收时异常；真实 Provider 测试和浏览器 Backend 使用宿主机显式
Clash 代理。该代理配置没有写入仓库，结果与环境条件已分开记录。

## 已知限制

- 没有永久聊天历史、Web Search、Hybrid Search、Reranker 或 Phase 5 自动评估；
- Vite 主 bundle 有约 555.89 kB 的非阻断体积警告；
- Provider 错误不退款，网络不可达时在配置超时后返回脱敏错误；
- 只记录脱敏 Agent Run 日志，没有监控 Dashboard。

## Git 检查点

用户授权在 `main` 创建统一 Phase 4 Commit，并创建
`feature/phase4-multi-agent` 分支指向同一 Commit。不会 Push、Merge 或创建额外未授权集成操作。

建议 Commit 信息：

```text
feat: complete phase 4 multi-agent interview workflow
```

## 停止点

Phase 4 在此结束。没有开始 Phase 5、RAG Baseline、Recall@K/MRR/NDCG、Reranker、Hybrid
Search 或生产监控优化。
