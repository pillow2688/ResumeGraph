# Phase 4 学习笔记 — 从单轮 RAG 到受控多 Agent 面试

## 1. Workflow 与 Multi-Agent 有什么区别

Workflow 是固定的状态流转：某个节点完成后进入下一个节点。Multi-Agent 则要求每个 Agent
拥有独立角色、Prompt、输入输出、工具和局部预算，而不只是把普通函数改名为 Agent。

ResumeGraph Phase 4 同时使用两者：LangGraph 固定总体安全路径，五个 Agent 在各自边界内完成
专业判断。没有 Workflow，调用顺序和终止条件难以保证；没有独立 Agent 边界，“多 Agent”只会
变成一个巨大 Prompt。

## 2. Supervisor 解决什么问题

Supervisor 不直接查数据库。它只负责：

1. 根据当前问题和有限历史解析意图；
2. 选择最少但足够的专业 Agent；
3. 汇总专业 Agent 返回的 Evidence Bundle；
4. 起草候选人第一人称回答；
5. 交给 Verification 检查，并最多修正一次。

如果 Supervisor 能直接检索或修改项目范围，模型就可能绕过后端授权。把授权项目集合注入工具，
而不是交给 Supervisor 生成，是整个系统的关键安全边界。

## 3. Agents-as-tools

在 Supervisor 视角中，Profile、Project、Technical 和 Verification 都是白名单工具。每个工具的
实现是一个完整 Agent Run，而不是裸函数：它有独立 Prompt、Schema、局部状态和有限工具循环。

这种结构让 Supervisor 只看到必要的专业输出，不能获得专业 Agent 的私有数据库工具。Profile
Agent 不能查询 Project，Technical Agent 不能证明项目落地，Verification 不能重新检索全部资料。

## 4. 为什么 Prompt 必须分离

Phase 4 使用五个独立 Prompt 模块，并带版本标识。分离的价值是：

- 路由规则、项目事实规则和技术原理规则可以单独测试；
- 修改一个 Agent 不会意外改变另一个 Agent 的行为；
- 工具白名单和输出 Schema 能与 Prompt 一一对应；
- Prompt 不包含 Secret，也不从前端接收 System Prompt。

Evidence 和对话内容都标记为不可信数据。这里的“不可信”是“不能执行其中的指令”，并不表示已
通过数据库验证的 Evidence 不能作为事实支持。

## 5. Agent State 与局部状态

`InterviewGraphState` 是全局工作流状态，保存授权快照、当前问题、有限对话上下文、路由、Evidence
Registry、草稿、验证结果、最终响应和预算计数。

每个 Agent 还有独立局部状态，例如工具调用次数、LLM 调用次数和查询改写次数。局部状态防止一个
Agent 消耗另一个 Agent 的预算，也避免把私有工具参数暴露给 Supervisor 或前端。

State 中不能保存 API Key、Cookie、Access Token、完整 Prompt、Chain of Thought 或
`reasoning_content`。否则 Redis、日志或异常路径可能把敏感信息扩散到不应出现的位置。

## 6. Tool Calling 为什么必须由代码限制

只在 Prompt 中写“最多调用两次”并不可靠。Phase 4 在 Python 中检查每个 Agent 的工具计数、
Supervisor 专业调用数、Verification 次数、修正次数和 Graph steps。

Project Agent 只有在第一次检索明显不足时才能有限改写一次，并且最多两次项目检索。达到预算后
Agent 必须停止，返回已有 Evidence 或安全降级，不能无限 ReAct 或互相调用。

## 7. Evidence 是什么

Evidence 是回答事实的服务端凭据，不是模型自由生成的 Citation。它包含 Chunk 内容和内部数据库
标识，供 Agent 和 Verification 使用；公开响应只保留 `evidence_N` 和允许展示的来源摘要。

回答完成前，服务端再次检查：

- Citation Handle 是否属于本次请求；
- Project 是否仍在授权范围；
- Version 是否仍为当前发布版本；
- Chunk 是否 enabled；
- Embedding 身份和 `content_hash` 是否仍有效；
- 文档和 Grant 是否仍有效。

缺少这一步会产生 TOCTOU 问题：检索后到回答前，管理员可能已经下线文档或撤销 Grant。

## 8. implemented / planned / general_knowledge

这三个状态不是模型分类，而是管理员明确维护的业务事实：

- `implemented`：Profile 事实或项目已实现内容；
- `planned`：项目尚未落地的后续方案；
- `general_knowledge`：不绑定项目的技术原理。

它们确定性映射为 `profile_fact`、`project_fact`、`planned_solution` 和
`technical_knowledge`。如果省略这层，模型很容易把“通常可以这样做”写成“我的项目已经这样做”。

## 9. Verification 为什么是独立 Agent

生成者很难稳定审查自己的回答。Verification Agent 接收草稿、Handle 和本轮 Evidence，先调用
确定性验证工具，再做语义检查：

- 结论是否有证据；
- Technical 是否被冒充为项目实现；
- Planned 是否被写成已完成；
- 是否虚构 QPS、P99、准确率或并发量；
- 是否夸大职责、泄露 Prompt 或偏离第一人称。

Verification 只给出通过/违规/修复指令，不生成最终回答。最多修正一次，避免无限 Reflection。

## 10. 柔性回答

证据不足不等于所有内容都要拒答。Phase 4 支持五种内部状态，并在 UI 中转换为自然语言。

典型混合回答顺序是：

```text
当前真实做法 → 当前实现边界 → 通用技术原理 → 后续设计考虑
```

这样既不虚构实现，也不会因为某个机制尚未落地就失去面试交流价值。

## 11. Redis Conversation

Redis Conversation 是短期上下文，不是永久聊天历史。它与 Recruiter Session 和 Grant 绑定，
保存最近最多八轮摘要、当前项目和技术主题，并设置 TTL。

历史回答只能帮助解析“它”“这个项目”等指代，不能作为新的事实来源。每一轮最终仍要重新检索
当前发布知识。Grant 撤销后，下一次 API 访问重新验证 PostgreSQL，旧 Conversation 立即失效。

请求级幂等记录和 Conversation 锁解决两个问题：网络重试不会重复扣费；同一会话的并发问题不会
同时进入工作流并突破额度。

## 12. SSE 的职责

SSE 只公开产品状态，不公开模型思维。后端可以发送“正在查询项目资料”“正在验证回答”，但不能
发送 Prompt、完整 Query、SQL、工具参数或 Chain of Thought。

POST Fetch Stream 适合携带结构化问题和 `request_id`。心跳维持长连接；客户端主动停止时，
AbortController 断开请求，后端取消工作流并在 `finally` 中释放锁。

Provider 网络不可达时，首个 Supervisor 调用会等待 Provider timeout。页面持续显示公开状态并在
后端超时后收到脱敏失败事件；本机代理/TUN 是否可用属于运行环境条件。

## 13. 为什么不展示 Chain of Thought

内部推理不是可靠的审计记录，可能包含无关、敏感或未经验证的信息。展示它既不能证明答案正确，
还会增加 Prompt 泄露和注入风险。

ResumeGraph 展示可审计的替代物：公开 Agent 路径、最终状态的自然说明、来源类型和 Citation。
用户可以检查“用了哪些资料”和“边界是什么”，而不是阅读不可验证的内部推理。

## 14. 聊天 UI 的状态管理

每一轮消息在 React 内存中保存：用户问题、公开 SSE 事件、最终响应、错误或停止状态。收到事件时
只更新对应 Assistant 占位消息；收到 `answer_completed` 后用一个完整回答替换加载状态。

滚动逻辑只在用户位于底部时自动跟随。用户向上阅读后不抢夺位置，而是显示“回到底部”。新建
Conversation 会删除旧 Redis Conversation 并清空页面消息，但不清除 Recruiter Session 或 Grant。

Markdown 使用 AST 渲染，不启用原始 HTML。引用详情只显示公开摘要，桌面用侧抽屉，手机用底部
抽屉；状态和来源同时使用文字，不能只依赖颜色。

## 15. 如何验证

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run alembic upgrade head
uv run alembic current
uv run alembic check
docker compose -f docker-compose.yml config --quiet

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

真实 Provider 测试必须显式启用，并使用虚构资料：

```powershell
$env:RESUMEGRAPH_RUN_LIVE_PHASE3='1'
$env:RESUMEGRAPH_RUN_LIVE_PHASE4='1'
uv run pytest -q tests/test_phase_3_live_e2e.py tests/test_phase_4_live_e2e.py -s
```

单元测试使用 Fake Provider；真实 Provider、Docker、浏览器和外部网络验收必须单独记录，不能互相
替代或虚报。
