# Phase 2.4 最小知识索引与发布设计

## 目标与边界

Phase 2.4 MVP 闭环为：

```text
Chunk → 规则 → DeepSeek 轻量判断 → OpenAI-Compatible Embedding
      → pgvector → 管理员纠偏 → 发布或下线
```

本阶段不实现 Retriever、RAG、LangGraph、Chat、排序或 Web Search。PostgreSQL 继续作为 Chunk、Embedding、版本和发布关系的事实来源；Redis 只承载临时 Session、计数器和 ARQ Job 投递。

## Chunk 质量语义

`document_chunks` 使用以下最小字段：

- `auto_indexable: bool | null`：规则和 DeepSeek 的自动建议；null 表示尚未检查。
- `enabled: bool`：最终索引开关。第一次检查采用 `auto_indexable`，后续重跑保留管理员修改。
- `quality_issues: JSONB`：稳定 issue code，不保存秘密原值。
- `extracted_metadata: JSONB`：只保存 `knowledge_type`、`topics`、`technologies`。
- `quality_checked_at`、`quality_model`、`quality_reason`。

手机号和邮箱为 Warning，发送 DeepSeek 或 Embedding 前脱敏，首次检查默认 `enabled=false`。管理员可纠正为启用，但外发文本仍保持脱敏；Embedding 的 `content_hash` 始终引用原 Chunk hash。疑似秘密为 Hard Block，不发送外部模型、不生成 Embedding，并强制 `enabled=false`。

## DeepSeek 最小职责

DeepSeek 使用共享 OpenAI-compatible 异步 Client，Thinking 关闭、`temperature=0`、JSON Output、显式 timeout、有限重试和有限批次。结果只包含：

```text
chunk_id, is_indexable, issues, knowledge_type, topics, technologies, reason
```

Pydantic 禁止额外字段，并验证当前服务端批次 ID 恰好各出现一次。reasoning content 不读取、不保存。

## 通用 Embedding Provider

MVP 只有一条生产实现路径：

```text
EmbeddingProvider Protocol
        ↓
OpenAICompatibleEmbeddingProvider
```

不得创建智谱、阿里云或 OpenAI 厂商专用 Provider，也不建立多厂商 Factory。通过以下通用配置切换 OpenAI-Compatible 服务：

- `embedding_provider_name`
- `embedding_base_url`
- `embedding_api_key: SecretStr`
- `embedding_model`
- `embedding_dimensions`
- `embedding_send_dimensions`
- `embedding_batch_size`
- `embedding_timeout_seconds`
- `embedding_max_retries`

当前活动配置为智谱 `embedding-3`、1024 维、批大小 10、超时 30 秒、最多重试 2 次；API base URL 为 `https://open.bigmodel.cn/api/paas/v4`。业务层、Worker、Service 和 Job 只依赖 `EmbeddingProvider`，不感知厂商 SDK 或名称。

Provider 创建一个共享 `AsyncOpenAI`，按配置批量调用 `embeddings.create`，可选择是否发送 `dimensions`，按响应 `index` 恢复输入顺序，并验证数量、固定维度和有限数值。Worker shutdown 关闭 Provider 拥有的 Client。Fake 仅用于测试；未配置 Key 时生产使用 `UnconfiguredEmbeddingProvider`，绝不回退 Fake。

统一安全错误码为：

```text
embedding_provider_unavailable
embedding_provider_auth_failed
embedding_provider_rate_limited
embedding_provider_invalid_response
embedding_dimension_mismatch
embedding_timeout
```

错误、日志和 API 不包含供应商原始错误、API Key、Authorization Header 或完整 Chunk 正文。

## 统一 knowledge_indexing Job

沿用 `ingestion_jobs` 和同一 ARQ/Redis Queue，以 `job_type=knowledge_indexing` 区分：

```text
ready_for_review → indexing → ready_to_publish
                           → indexing_failed
```

Job stage 为：

```text
rule_check → llm_quality_check → embedding → saving
```

同一版本同时最多一个活动 Job。完成事务重新锁定 Chunk，并要求所有 enabled Chunk 都有与当前活动配置的 `provider_name + model_name + dimensions + content_hash` 完全匹配的向量，才能进入 `ready_to_publish`。

## pgvector 持久化

`chunk_embeddings` 保存：

```text
id, chunk_id, provider_name, model_name, dimensions,
content_hash, embedding, created_at
```

唯一约束为：

```text
chunk_id + provider_name + model_name + dimensions
```

使用无 typmod 的 pgvector `vector`，以便通用配置切换维度；Provider、Repository 和发布事务共同执行固定维度校验。只对 `enabled=true` 的 Chunk 保存向量。

## 管理员纠偏与发布

管理员可以在未发布版本上启用或禁用 Chunk。任何纠偏都会把版本退回 `ready_for_review`，要求重新运行统一 indexing Job；published、superseded、processing 或 indexing 版本不允许直接修改。

发布事务要求：

- 版本状态为 `ready_to_publish`；
- 至少一个 enabled Chunk；
- 每个 enabled Chunk 都有当前活动配置的有效 Embedding；
- Embedding content hash 与 Chunk 匹配。

发布时新版本变为 `published`，旧当前版本变为 `superseded`，并更新 `knowledge_documents.current_published_version_id`。新版本未准备完成前旧发布版本保持有效。下线会清空当前发布关系，并把原当前版本标记为 `superseded`。

## 前端最小范围

前端只提供：启动 indexing Job、查看规则/DeepSeek 摘要与异常 Chunk、启用或禁用 Chunk、查看 Embedding stage、显示当前通用 Embedding 配置、发布版本、查看当前发布版本和下线文档。前端不得根据 `zhipu` 写死流程，不提供 Prompt、模型参数或多维评分管理。

## 验证与秘密管理

单元测试使用 Fake Client/Fake Provider，不调用真实外部服务。真实联调 Key 只从环境变量注入，不进入 Git、日志或响应。完成后运行 Ruff、完整 pytest、Alembic upgrade/current/check、真实 pgvector 写入验证、前端 lint/typecheck/test/build 和 Compose config。不得自动 Commit、Tag、Push 或 Merge。
