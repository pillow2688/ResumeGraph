# Phase 2.4 学习笔记 — 从 Chunk 到可发布向量知识

Date: 2026-07-15
Scope: Rule Check、DeepSeek 判断、Embedding、pgvector 与发布；不讲 Retriever 或 RAG

## 1. Phase 2.4 解决了什么问题

Phase 2.3 已经能把 Markdown 清洗并切成 Chunks，但“有 Chunk”并不等于“这些内容适合进入
知识索引”。Phase 2.4 在中间增加了安全检查、自动判断、向量化和显式发布：

```text
ready_for_review Chunk
→ 确定性规则
→ DeepSeek 最小判断
→ 管理员最终 enabled 开关
→ Embedding
→ pgvector
→ ready_to_publish
→ 管理员显式发布
```

这条链路把“处理成功”“向量化成功”和“对外发布”分成三个不同事实，避免程序把中间
技术状态误当成产品授权。

## 2. 为什么 Rule Check 必须在 LLM 之前

LLM 是外部、非确定性的服务。很多安全和格式问题不需要模型推理，例如：

- 文本疑似包含 API Key、私钥或 Authorization 内容；
- Chunk 与本批次其他 Chunk 完全重复；
- 文本含手机号或邮箱；
- Chunk 明显过短、异常字符过多或超出预期长度。

这些问题用普通代码检查更快、更便宜，也更容易测试。更重要的是，规则可以在网络请求
发生前决定“这段正文是否允许外发”。如果把 Rule Check 放在 LLM 之后，秘密可能已经离开
服务器，之后再拒绝也无法撤回。

当前顺序是：

1. 对所有 Chunk 执行确定性规则；
2. Hard Secret 和重复内容直接阻断，不发送给 DeepSeek；
3. 手机号、邮箱保留为 PII Warning，并先脱敏；
4. 只把允许外发的脱敏文本交给 DeepSeek；
5. `too_long` 只作为普通 Warning，帮助发现 Chunking 回归。

## 3. 为什么秘密内容不能进入外部模型

外部模型调用会跨越 ResumeGraph 的本地信任边界。即使供应商提供隐私承诺，应用仍应遵循
最小披露原则：不需要发送的数据就不发送。

Hard Secret 的处理不是“让模型判断它是不是秘密”，而是服务器先阻断。这样做可以：

- 防止 API Key、私钥或认证头出现在第三方请求中；
- 防止秘密进入第三方日志、计费或诊断系统；
- 让单元测试在不访问网络的情况下验证安全边界；
- 避免把安全决定交给 Prompt 或模型概率。

手机号和邮箱属于 PII，但当前产品允许管理员之后纠正误判，因此它们不是永久硬阻断。
系统在外发前脱敏，并把 `auto_indexable` 默认设为 `false`；管理员仍可以通过最终
`enabled` 开关决定是否重新索引。

## 4. DeepSeek 实际负责什么

DeepSeek V4 Pro 在本阶段是“轻量结构化判断器”，不是内容作者，也不是权限系统。每个
Chunk 只返回：

- 服务器提供的 `chunk_id`；
- `is_indexable` 自动建议；
- 简单 `issues`；
- `knowledge_type`；
- `topics`；
- `technologies`；
- 简短 `reason`。

服务端使用严格 Pydantic Schema 校验 JSON，并检查返回 ID 与当前批次完全一致。缺失、额外、
重复或批次外 ID 都会失败。Thinking 默认关闭，`temperature=0`，不保存 Chain of Thought。

DeepSeek 不修改 Chunk 正文、不补写候选人经历、不创建权限字段，也不直接把版本设为 published。

## 5. 为什么 DeepSeek 不生成 Embedding

“判断一段内容是否适合索引”和“把文本转换为数值向量”是两种不同模型能力：

- DeepSeek V4 Pro 是本阶段选择的结构化质量判断模型；
- 智谱 `embedding-3` 是当前选择的文本 Embedding 模型。

不能因为两个服务都使用 OpenAI-compatible HTTP 形式，就认为它们是同一种模型。业务代码通过
两个独立边界表达这种差别：Quality Provider 返回结构化判断，Embedding Provider 返回固定维度
的浮点向量。

## 6. OpenAI-Compatible Embedding Provider 的作用

业务层只依赖 `EmbeddingProvider` Protocol，不知道供应商 SDK 或专用类。当前唯一真实实现
`OpenAICompatibleEmbeddingProvider` 由以下配置决定行为：

- `base_url`；
- API Key；
- model；
- dimensions；
- 是否发送 dimensions；
- batch size、timeout 和 max retries。

这使当前智谱配置可以工作，同时避免创建 `ZhipuEmbeddingProvider`、
`OpenAIEmbeddingProvider` 等重复类。Provider 长期持有一个共享 Async Client，Worker 关闭时
再释放；每次请求都新建 Client 会浪费连接并增加延迟。

Provider 还负责把供应商响应收敛为稳定业务边界：

- 根据 `response.data[index]` 恢复输入顺序；
- 检查返回数量；
- 检查每个向量都是配置维度；
- 拒绝 NaN 和 Infinity；
- 对超时、429 和 5xx 做有限重试；
- 把错误转换为供应商无关且不泄漏正文或秘密的错误码。

`FakeEmbeddingProvider` 只用于确定性测试；生产配置缺失时使用
`UnconfiguredEmbeddingProvider` 明确失败，绝不静默回退 Fake。

## 7. 为什么 Chunk 和 Embedding 需要 content_hash

向量只代表生成它时的那段文本。如果 Chunk 文本改变，但数据库仍保留旧向量，二者就不再
对应。仅检查 `chunk_id` 不能发现这种情况，因为记录 ID 可能没变。

系统为 Chunk 保存 SHA-256 `content_hash`，生成 Embedding 时把同一哈希写入
`chunk_embeddings`。进入 `ready_to_publish` 和发布前都要求：

```text
embedding.content_hash == chunk.content_hash
```

同时还要匹配当前 `provider_name`、`model_name` 和 `dimensions`。因此，切换模型、维度或修改
Chunk 开关后，旧向量不能伪装成当前有效向量。

## 8. pgvector 的作用

pgvector 是 PostgreSQL 扩展，允许向量与普通关系数据保存在同一个数据库中。本阶段创建
`chunk_embeddings`，保存：

- `chunk_id`；
- 向量值；
- provider、model 和 dimensions；
- Chunk `content_hash`；
- 创建时间。

这样向量仍然连接到 PostgreSQL 中权威的 Project、Document、Version 和 Chunk。Phase 2.4
只完成扩展启用、写入和发布完整性检查，没有实现相似度查询。

## 9. auto_indexable 与 enabled 的区别

`auto_indexable` 是系统自动建议：

- `null`：尚未检查；
- `true`：规则和 DeepSeek 建议可以索引；
- `false`：自动建议不进入索引。

`enabled` 是管理员最终开关。第一次质量任务完成时，它默认采用 `auto_indexable`；之后管理员
可以纠正误判。重跑自动判断不会机械覆盖已经存在的管理员选择，Hard Secret 除外。

如果只保留一个字段，就无法区分“系统如何判断”和“管理员最终决定”。如果再增加另一个
`is_indexable`，又会制造重复语义。因此两个字段刚好表达自动建议与最终开关。

## 10. 为什么向量化完成不等于发布

Embedding 是技术处理结果，发布是管理员授权行为。自动向量化不能替管理员决定资料是否
对未来 Recruiter 可用。

版本只有满足以下条件才能发布：

- 状态为 `ready_to_publish`；
- 至少有一个 `enabled=true` Chunk；
- 每个 enabled Chunk 都有匹配当前 provider、model、dimensions 的 Embedding；
- 每个 Embedding 的 `content_hash` 与 Chunk 一致。

满足这些条件仍只代表“可以发布”。管理员调用发布操作后，它才成为当前 published 版本。

## 11. 新版本如何替换旧发布版本

`knowledge_documents.current_published_version_id` 指向当前发布版本。新版本在清洗、判断和
向量化期间不会修改这个指针，所以旧版本继续有效。

发布新版本时在同一数据库事务内：

1. 锁定文档和相关版本；
2. 再次验证新版本完整性；
3. 把旧当前版本设为 `superseded`；
4. 把新版本设为 `published`；
5. 更新 `current_published_version_id`。

下线时将该指针设为 `NULL`，原当前版本变为 `superseded`。原子事务避免系统在切换过程中出现
两个“当前版本”或没有明确当前版本的中间状态。

## 12. PostgreSQL、Redis 与 Worker 的分工

| 组件 | 职责 | 如果省略或混用会怎样 |
| --- | --- | --- |
| PostgreSQL | 保存文档、版本、Job、Chunk、Embedding 身份和发布事实 | 重启后状态可能丢失，无法做事务完整性和发布校验。 |
| Redis | 保存临时 Session、限流计数和 ARQ 队列消息 | 如果把发布事实只放 Redis，缓存过期会破坏业务状态。 |
| Worker | 在 HTTP 请求之外执行清洗、判断和向量化 | 如果在 API 请求内执行，连接会长时间占用，超时和重试边界难以控制。 |

API 创建 Job 并返回 UUID；Redis 只投递 UUID；Worker 从 PostgreSQL 读取权威输入并把阶段、失败
和结果写回 PostgreSQL。

## 13. 本阶段没有做什么

Phase 2.4 到“可发布向量知识”为止。它没有实现：

- pgvector 相似度检索；
- Retriever 或混合检索；
- RAG 答案生成和引用；
- LangGraph；
- Chat、SSE 或多轮对话；
- 面试官问题处理。

这些内容不能从现有向量表自动推断为已完成，也不应在本学习笔记中扩展成高级 RAG 教程。
