# Phase 2.4 Architecture — Knowledge indexing and publication

Date: 2026-07-15
Scope: implemented Phase 2.4 only; no Retriever, RAG, LangGraph, Chat, or SSE

## 1. 总体架构

```mermaid
flowchart LR
    Admin["管理员浏览器<br/>React"]
    API["FastAPI<br/>管理员 API"]
    PG[("PostgreSQL<br/>业务事实 + pgvector")]
    Redis[("Redis<br/>Session / ARQ Queue")]
    Worker["ARQ Worker<br/>长任务执行"]
    Rules["Deterministic<br/>Rule Check"]
    DeepSeek["DeepSeek V4 Pro<br/>结构化索引判断"]
    Embed["OpenAI-Compatible<br/>Embedding API"]

    Admin -->|"HttpOnly Cookie + JSON"| API
    API -->|"短事务：创建 Job / 查询 / 发布"| PG
    API -->|"投递 Job UUID"| Redis
    Redis -->|"领取 Job UUID"| Worker
    Worker -->|"读取输入、写入阶段和结果"| PG
    Worker --> Rules
    Rules -->|"仅允许外发的脱敏文本"| DeepSeek
    DeepSeek -->|"严格 JSON 判断"| Worker
    Worker -->|"仅 enabled 文本"| Embed
    Embed -->|"固定 1024 维向量"| Worker
```

PostgreSQL 保存耐久事实；Redis 只协调临时状态和队列；FastAPI 请求不执行长时间模型调用；
Worker 共享并在关闭时释放异步外部 Client。

## 2. knowledge_indexing Job 流程

```mermaid
flowchart TD
    Start["POST /document-versions/{id}/index"]
    Create["创建或复用唯一活动<br/>knowledge_indexing Job"]
    Queue["Redis/ARQ 投递 Job UUID"]
    Begin["Worker 锁定 Job 与 Version<br/>ready_for_review → indexing"]
    Rule["stage: rule_check<br/>秘密阻断、PII 脱敏、重复/长度检查"]
    LLM["stage: llm_quality_check<br/>DeepSeek 严格结构化判断"]
    SaveQuality["保存 auto_indexable、enabled、<br/>issues、metadata、reason"]
    Vector["stage: embedding<br/>只处理 enabled=true Chunk"]
    SaveVector["stage: saving<br/>写入 chunk_embeddings"]
    Integrity{"全部 enabled Chunk 是否具有<br/>当前配置且 hash 匹配的向量？"}
    Ready["Job completed<br/>Version → ready_to_publish"]
    Failed["Job failed<br/>Version → indexing_failed"]

    Start --> Create --> Queue --> Begin --> Rule
    Rule -->|"Hard Secret 不外发"| SaveQuality
    Rule -->|"可外发的脱敏文本"| LLM --> SaveQuality
    SaveQuality --> Vector --> SaveVector --> Integrity
    Integrity -->|"是"| Ready
    Integrity -->|"否"| Failed
    Rule -->|"不可恢复错误"| Failed
    LLM -->|"有限重试后失败"| Failed
    Vector -->|"有限重试后失败"| Failed
```

Job 的 durable `status`、`stage`、`progress` 和安全错误摘要都保存在 PostgreSQL。ARQ 自身不保存
唯一业务结果。

## 3. Rule Check、DeepSeek 与 Embedding 的分工

```mermaid
flowchart LR
    Chunk["原始 Chunk"]
    Rule["Rule Check<br/>确定性、安全优先"]
    Block["Hard block<br/>auto_indexable=false<br/>enabled=false"]
    Redacted["允许外发的脱敏文本"]
    Judge["DeepSeek V4 Pro<br/>is_indexable + metadata + reason"]
    Decision["自动建议<br/>auto_indexable"]
    Admin["管理员最终开关<br/>enabled"]
    Provider["EmbeddingProvider<br/>厂商无关业务边界"]
    Vector["OpenAI-Compatible API<br/>embedding-3 / 1024"]

    Chunk --> Rule
    Rule -->|"Secret / duplicate"| Block
    Rule -->|"通过或 PII 已脱敏"| Redacted
    Redacted --> Judge --> Decision
    Decision -->|"首次默认值"| Admin
    Admin -->|"enabled=true"| Provider --> Vector
```

Rule Check 决定能否外发；DeepSeek 只提供结构化建议；管理员控制最终 `enabled`；Embedding 模型
只生成向量。四者不能相互替代，也都不能创建授权范围。

## 4. Project、Document、Version、Chunk 与 Embedding 关系

```mermaid
erDiagram
    PROJECT ||--o{ KNOWLEDGE_DOCUMENT : contains
    KNOWLEDGE_DOCUMENT ||--o{ DOCUMENT_VERSION : versions
    KNOWLEDGE_DOCUMENT o|--o| DOCUMENT_VERSION : current_published_version
    DOCUMENT_VERSION ||--o{ INGESTION_JOB : jobs
    DOCUMENT_VERSION ||--o{ DOCUMENT_CHUNK : chunks
    DOCUMENT_CHUNK ||--o{ CHUNK_EMBEDDING : embeddings

    PROJECT {
        uuid id PK
        string name
    }
    KNOWLEDGE_DOCUMENT {
        uuid id PK
        uuid project_id FK
        uuid current_published_version_id FK
        string title
    }
    DOCUMENT_VERSION {
        uuid id PK
        uuid document_id FK
        int version_number
        text raw_content
        string content_hash
        string status
    }
    INGESTION_JOB {
        uuid id PK
        uuid document_version_id FK
        string job_type
        string status
        string stage
        int progress
    }
    DOCUMENT_CHUNK {
        uuid id PK
        uuid document_version_id FK
        int chunk_index
        text content
        string content_hash
        boolean auto_indexable
        boolean enabled
        jsonb quality_issues
        jsonb extracted_metadata
    }
    CHUNK_EMBEDDING {
        uuid id PK
        uuid chunk_id FK
        vector embedding
        string provider_name
        string model_name
        int dimensions
        string content_hash
    }
```

`chunk_embeddings` 的唯一约束是
`(chunk_id, provider_name, model_name, dimensions)`。发布完整性还要求向量长度有效、数值有限且
Embedding 的 `content_hash` 与 Chunk 一致。

## 5. 发布、版本切换与下线

```mermaid
stateDiagram-v2
    [*] --> ready_for_review: Phase 2.3 完成
    ready_for_review --> indexing: 创建 knowledge_indexing Job
    indexing --> indexing_failed: 规则/模型/向量/持久化失败
    indexing_failed --> indexing: 管理员重新启动索引
    indexing --> ready_to_publish: 完整性校验通过
    ready_to_publish --> indexing: 管理员修改 enabled 后重新索引
    ready_to_publish --> published: 管理员显式发布
    published --> superseded: 新版本原子替换或文档下线
```

版本切换过程：

```mermaid
sequenceDiagram
    actor Admin as 管理员
    participant API as Publication API
    participant PG as PostgreSQL

    Note over PG: v1 = current published<br/>v2 = ready_to_publish
    Admin->>API: publish(v2)
    API->>PG: BEGIN + lock document/version
    PG-->>API: v2 enabled Chunks + current-config Embeddings
    API->>API: 验证 provider/model/dimensions/content_hash
    API->>PG: v1 → superseded
    API->>PG: v2 → published
    API->>PG: current_published_version_id = v2
    API->>PG: COMMIT
    Note over PG: 切换前 v1 始终有效

    Admin->>API: unpublish(document)
    API->>PG: v2 → superseded
    API->>PG: current_published_version_id = NULL
```

Phase 2.4 只建立发布关系和完整性，不提供任何面试官检索入口。
