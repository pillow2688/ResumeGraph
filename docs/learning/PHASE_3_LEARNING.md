# Phase 3 学习笔记 — 从发布 Chunk 到单轮 RAG

## 1. 为什么需要 Query Embedding

文档 Chunk 在 Phase 2 已被转换成向量。问题也必须使用同一 provider、model 和 dimensions 转换
成向量，pgvector 才能比较语义距离。`embed_query` 复用现有 Provider 的 HTTP Client、超时、
重试和维度校验；如果另建 Client，配置漂移会让问题向量和文档向量不可比较。

余弦距离越小，方向越接近。本阶段用数据库直接计算距离并升序取 Top-K。排序发生在 SQL，
不是把全库向量搬到 Python。

## 2. 为什么授权必须写进检索 SQL

入口重验证 Session 只能证明“请求开始时 Grant 有效”。在生成问题向量或等待模型时，管理员
可能撤销 Grant。Retriever 因此再次连接 `access_grants` 和 `grant_projects`。这叫纵深防御：
即使客户端伪造 Project UUID，或授权在请求中途改变，未授权行也不会进入 Evidence。

如果先全库检索再让 LLM 判断权限，正文已经离开授权边界；即使模型最终不显示它，也已经构成
数据泄漏风险。

### Profile 与 Project 为什么必须分支后再合并

候选人的教育、简介和技能是跨项目资料，放进任意 Project 会迫使管理员重复授权或制造一个假的
“个人背景项目”。Phase 3 直接复用已经存在的 `document_scope`：已发布 Profile 对每个有效 Grant
可用，Project 仍严格受 `grant_projects` 和本次请求范围限制。两类资料在同一条 SQL 中合并，才能
既让“请介绍教育背景”命中 Profile，又保证项目文档不会跨 Grant 泄漏。

Profile 全局可检索不等于公开可检索。撤销、过期或额度耗尽的 Grant 都不能进入 Retriever；显式
请求未授权 Project 仍会在扣额度前失败，也不会偷偷退回 Profile 结果。

## 3. 当前发布指针为什么重要

只检查 `DocumentVersion.status = published` 不够。历史数据或并发状态变化可能留下多个看似可用
的 Version。`KnowledgeDocument.current_published_version_id` 是唯一当前发布指针，检索必须通过
它连接 Version，再检查 Version 状态。这样替换或下线文档后，旧 Chunk 不会继续被问答使用。

同理，Chunk 必须 enabled，Embedding 身份必须等于活动配置，Embedding 哈希必须与当前 Chunk
哈希一致。这些条件避免返回已禁用、已编辑但未重嵌入或来自旧模型的向量。

## 4. Evidence Handle 解决什么问题

模型不需要知道数据库 UUID。服务端把检索结果编号为 `evidence_1`、`evidence_2`：

```text
数据库事实 → Evidence → 服务端 Handle → 模型 JSON → 服务端再验证 → 公开 Citation
```

模型只能引用本次给出的 Handle。服务端拒绝伪造 Handle，并在返回前重新检查引用对应 Chunk
是否仍然授权、发布和有效。公开响应只包含展示来源所需的项目名、文档名、版本号和标题路径，
不会回传完整 Chunk 或向量。

## 5. 为什么严格 JSON 仍要服务端校验

`response_format=json_object` 只提高格式稳定性，不能证明业务语义正确。Pydantic 继续检查：

- status 是否只有 `answered` / `insufficient_evidence`；
- answered 是否至少一个引用；
- insufficient 是否没有引用；
- 是否有多余字段；
- Handle 是否全部属于本次 Evidence。

连续非法输出只重试一次，防止无界模型调用和成本失控。程序不保存 `reasoning_content` 或
Chain of Thought。

## 6. 证据不足是正常结果

RAG 的目标不是尽量回答，而是在授权资料范围内准确回答。没有 Evidence，或模型判断资料不足，
或生成后引用失效时，都返回统一拒答：

> 我目前提供的资料中没有记录这一点，因此无法给出准确回答。

统一文本便于前端展示、测试和安全审计，也避免模型把通用常识包装成候选人的真实经历。

## 7. 原子额度为什么不能 SELECT 再加一

两个并发请求若都先读取 `request_count=19`，都可能认为还能请求，然后都写回 20，实际执行了
两次。条件 UPDATE 把“检查上限”和“加一”放在 PostgreSQL 同一个原子操作中；只有成功更新的
请求拿到 RETURNING 结果。未更新行表示额度、撤销或过期条件已经不满足。

参数、Session 和项目范围在扣减前校验。合法请求开始后即使无证据或 Provider 暂时失败也不
退款，这让并发语义保持简单且可审计。

## 8. 单轮不等于页面只能显示一条

页面可以在组件内存中累积多条问答，方便面试官阅读；但每个 POST 只发送当前问题和所选项目。
刷新即清空，也不写 localStorage。这保证当前版本没有隐式多轮上下文、历史持久化或跨问题
Prompt 注入面。

## 9. 为什么“已上传”不等于“可回答”

真实浏览器验收第一次上传的 Profile 内容过短，处理后虽然产生了 Chunk，但质量规则把全部 Chunk
禁用，索引任务因此明确返回 `No chunks are enabled for embedding`。这不是发布按钮或 Provider
失效，而是知识流水线在阻止低质量证据进入向量库。

管理员应在页面确认四个事实：处理完成、Chunk 至少一条启用、索引完成、当前版本已发布。补充为
信息完整且可独立理解的段落后，验收资料产生 3 个启用 Chunk，真实智谱索引和发布均成功，教育
背景问题随后命中 Profile Citation。管理页面现在会直接显示中文状态和下一步动作，避免把“上传”
误认为“已经可以被 RAG 检索”。

## 10. 如何验证

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'resumegraph-uv-cache'
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -q

$env:RESUMEGRAPH_RUN_POSTGRES_INTEGRATION = '1'
uv run --no-sync pytest -q tests/test_phase_3_postgres_integration.py

Set-Location frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

真实 Provider 测试必须显式设置 `RESUMEGRAPH_RUN_LIVE_PHASE3=1` 并从环境注入密钥。默认测试
永远使用 Fake Provider，不产生外部请求或费用。

## 11. 外部验收为什么要分层

一次“连不上”可能来自完全不同的层。本轮实际看到的证据链是：

```text
沙箱内 Docker named pipe Access denied
→ PermissionBlocked，不等于 Docker daemon 故障
→ 获批后 Docker Desktop / desktop-linux 正常

Provider DNS 返回 198.18.0.x Clash Fake-IP
→ 说明透明代理/TUN 可能接管流量，不等于网络失败
→ 获批后 TCP 443、TLS、真实 Provider 调用均成功
```

因此诊断要先区分权限、显式代理、透明代理、DNS、TCP、TLS、HTTP 认证和业务 Schema。不能把
一次沙箱拒绝写成永久失败，也不能看到 Fake-IP 就断言 Clash 配置错误。

本地服务使用同一个 `localhost` Host，并在验收命令内临时设置：

```powershell
$env:NO_PROXY = 'localhost,127.0.0.1,::1'
$env:no_proxy = $env:NO_PROXY
```

该设置只影响当前进程，不写入用户系统配置。Compose Frontend 通过 Nginx 同源代理 `/api` 到
Backend，浏览器只面对 `http://localhost:5173`，避免 CORS、Cookie Host 和 SameSite 因混用
`localhost`/`127.0.0.1` 产生差异。

完整容器验收命令是：

```powershell
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml exec -T postgres pg_isready -U resumegraph -d resumegraph
docker compose -f docker-compose.yml exec -T redis redis-cli ping
docker compose -f docker-compose.yml exec -T backend alembic current
docker compose -f docker-compose.yml exec -T backend alembic check
```

容器 running 只表示进程存在，不能替代 Postgres readiness、Redis PING、Backend ready、Worker
队列连接、Frontend HTTP 和真实问答检查。

本轮浏览器最终验收还覆盖了：管理员新增/删除、Profile 资料完整发布、Project 已发布资料、三次
单轮问答、Profile/Project Citation、`request_count` 从 0 原子增加到 3，以及撤销 Grant 后旧
Recruiter Session 立即跳回 `/access` 且不再扣额度。浏览器控制台没有 error 或 warning；一次性
Access Token 只用于 Exchange，没有写入 localStorage。
