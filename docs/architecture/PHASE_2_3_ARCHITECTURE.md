# Phase 2.3 架构图：异步文档处理与 Chunk 切分

本文只描述 Phase 2.3 已实现的文档处理边界：管理员创建持久化 Job，独立 ARQ Worker 执行确定性 Cleaning 和 Markdown-aware Chunking，PostgreSQL 保存权威状态与 Chunk。本文不表示 Chunk 审核、发布、Embedding、pgvector、Retriever、RAG、LangGraph、Chat 或 SSE 已实现。

## 1. 文档处理整体架构

```mermaid
flowchart LR
    Admin[管理员浏览器]

    subgraph Frontend[React + TypeScript 管理端]
        Detail[文档版本详情<br/>开始处理]
        JobPage[Job 状态页]
        ChunkPage[只读 Chunk 页]
        Client[Typed API Client]
    end

    subgraph API[FastAPI 进程]
        Auth[get_current_admin]
        Routes[Admin Ingestion Routes]
        Service[IngestionService]
        QueueAdapter[ArqJobQueue]
        ApiRepo[IngestionRepository]
    end

    subgraph Queue[临时任务通道]
        RedisQueue[(Redis ARQ Queue<br/>仅 Job UUID)]
    end

    subgraph WorkerProcess[独立 ARQ Worker 进程]
        Worker[IngestionWorker]
        Cleaning[Deterministic Cleaning]
        Chunking[Markdown-aware Chunking]
        WorkerRepo[IngestionRepository]
    end

    subgraph PostgreSQL[PostgreSQL 权威数据]
        Versions[(document_versions)]
        Jobs[(ingestion_jobs)]
        Chunks[(document_chunks)]
    end

    Admin --> Detail
    Detail --> Client
    JobPage --> Client
    ChunkPage --> Client
    Client --> Routes
    Routes --> Auth
    Routes --> Service
    Service --> ApiRepo
    ApiRepo --> Versions
    ApiRepo --> Jobs
    Service --> QueueAdapter
    QueueAdapter --> RedisQueue
    RedisQueue --> Worker
    Worker --> WorkerRepo
    WorkerRepo --> Jobs
    WorkerRepo --> Versions
    WorkerRepo -->|读取 raw_content| Versions
    Worker --> Cleaning
    Cleaning --> Chunking
    Chunking --> WorkerRepo
    WorkerRepo --> Chunks
```

关键边界：

- FastAPI 只认证管理员、创建 Job、投递 Job UUID、查询 PostgreSQL 状态；
- Worker 与 FastAPI 是独立进程，并拥有自己的数据库连接池和生命周期；
- Redis 只负责临时任务投递，不是 Job、版本或 Chunk 的事实来源；
- PostgreSQL 保存 `DocumentVersion`、Job 状态机和最终 Chunk；
- 队列载荷不包含原始 Markdown、Cookie、Token 或管理员身份；
- 所有三个管理 API 都依赖 `get_current_admin`，Recruiter Session 不能访问。

## 2. 文档处理流程图

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 管理员
    participant UI as React 文档页
    participant API as FastAPI
    participant Auth as get_current_admin
    participant Service as IngestionService
    participant DB as PostgreSQL
    participant Redis as Redis ARQ Queue
    participant Worker as ARQ Worker
    participant Pipeline as Cleaning + Chunking

    Admin->>UI: 选择 draft 文档版本并点击开始处理
    UI->>API: POST /document-versions/{version_id}/process
    API->>Auth: 校验 Admin Cookie 与 Session
    Auth-->>API: AdminPrincipal
    API->>Service: create_job(version_id)
    Service->>DB: BEGIN + SELECT DocumentVersion FOR UPDATE

    alt 已有 pending Job
        DB-->>Service: 返回同一 active Job
        Service->>Redis: 重新确认入队 job_id
    else 已有 processing Job
        DB-->>Service: 返回同一 active Job
        Note over Service,Redis: 不重复入队
    else 可创建新 Job
        Service->>DB: INSERT ingestion_job pending
        Service->>DB: UPDATE version status = processing
        Service->>DB: COMMIT
        Service->>Redis: enqueue job_id
    end

    Service-->>API: job_id + status
    API-->>UI: 202 Accepted
    UI->>API: GET /admin/jobs/{job_id}
    API->>DB: 查询持久化 Job 状态
    DB-->>API: status + stage + progress
    API-->>UI: 状态响应

    Redis-->>Worker: process_document_version_job(job_id)
    Worker->>DB: begin_job，读取 raw_content
    Worker->>DB: processing / reading / 5
    Worker->>DB: cleaning / 25
    Worker->>Pipeline: clean_markdown(raw_content)
    Worker->>DB: chunking / 55
    Worker->>Pipeline: split_markdown(cleaned_content)
    Worker->>DB: saving / 85
    Worker->>DB: BEGIN
    Worker->>DB: DELETE 旧 version Chunks
    Worker->>DB: INSERT 新 document_chunks
    Worker->>DB: Job completed / saving / 100
    Worker->>DB: Version ready_for_review
    Worker->>DB: COMMIT

    Admin->>UI: 查看完成状态与 Chunk
    UI->>API: GET /document-versions/{version_id}/chunks
    API->>DB: ORDER BY chunk_index
    DB-->>API: 只读 Chunk 列表
    API-->>UI: heading_path + content + metadata
```

失败边界：

- 入队失败：Job 写为 `failed`，版本恢复 `draft`，API 返回脱敏 503；
- 清洗后为空或处理异常：Worker 写入固定安全错误，Job 进入 `failed`，版本恢复 `draft`；
- Worker 取消或超时：尽力持久化 `failed` 后重新抛出取消；
- PostgreSQL 错误：Service/API 只暴露统一脱敏错误，不返回驱动异常。

## 3. Job 状态流转图

```mermaid
stateDiagram-v2
    [*] --> pending: 创建持久化 Job
    pending --> processing: Worker begin_job
    pending --> failed: Redis 入队失败
    processing --> completed: Chunk 原子保存成功
    processing --> failed: 空文档、异常、取消或超时
    completed --> [*]
    failed --> [*]

    state processing {
        [*] --> reading
        reading --> cleaning
        cleaning --> chunking
        chunking --> saving
        saving --> [*]
    }
```

`status` 与 `stage` 分离：

- `status` 表示 Job 生命周期：`pending | processing | completed | failed`；
- `stage` 表示 Pipeline 位置：`reading | cleaning | chunking | saving`；
- `progress` 当前按 `0 → 5 → 25 → 55 → 85 → 100` 更新；
- PostgreSQL partial unique index 保证一个版本最多一个 active Job。

## 4. Chunk 数据关系图

```mermaid
erDiagram
    KNOWLEDGE_DOCUMENTS ||--|{ DOCUMENT_VERSIONS : has
    DOCUMENT_VERSIONS ||--o{ INGESTION_JOBS : processed_by
    DOCUMENT_VERSIONS ||--o{ DOCUMENT_CHUNKS : produces

    KNOWLEDGE_DOCUMENTS {
        uuid id PK
        uuid project_id FK
        varchar title
    }

    DOCUMENT_VERSIONS {
        uuid id PK
        uuid document_id FK
        int version_number
        text raw_content
        varchar content_hash
        varchar status
    }

    INGESTION_JOBS {
        uuid id PK
        uuid document_version_id FK
        varchar status
        varchar stage
        int progress
        text error_message
        timestamptz created_at
        timestamptz started_at
        timestamptz finished_at
    }

    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_version_id FK
        int chunk_index
        json heading_path
        text content
        varchar content_hash
        int character_count
        boolean enabled
        timestamptz created_at
    }
```

数据约束：

- `ingestion_jobs.document_version_id` 和 `document_chunks.document_version_id` 删除时随版本级联；
- `(document_version_id, chunk_index)` 唯一且 `chunk_index >= 0`；
- `enabled` 默认 `true`，本阶段没有修改它的 API；
- Chunk 不包含 Embedding、vector、similarity 或 score；
- `ready_for_review` 只表示确定性处理完成，不表示已审核或已发布。

## 5. 处理 Pipeline 组件图

```mermaid
flowchart TD
    Raw[DocumentVersion.raw_content]
    BOM[删除开头 UTF-8 BOM]
    NUL[删除 NUL]
    Newline[统一 CRLF / CR 为 LF]
    Trim[清理行尾与全文边界空白]
    Blank[压缩连续空行]
    Empty{清洗后为空?}
    Hash[计算 cleaned content SHA-256]
    Heading[识别 fenced code 外的 ATX 标题]
    Section[按标题形成 Section 与 heading_path]
    Paragraph[过长 Section 按段落二次切分]
    Stable[稳定生成 chunk_index]
    ChunkHash[计算 Chunk SHA-256 与 character_count]
    Save[原子保存 document_chunks]
    Fail[Job failed + Version draft]
    Ready[Job completed + Version ready_for_review]

    Raw --> BOM --> NUL --> Newline --> Trim --> Blank --> Empty
    Empty -->|是| Fail
    Empty -->|否| Hash --> Heading --> Section --> Paragraph --> Stable --> ChunkHash --> Save --> Ready
```

## 6. 当前架构边界

当前终点是持久化的、只读可查看的 `document_chunks` 和版本状态 `ready_for_review`。未实现 Chunk 审核、发布流程、Embedding、pgvector、Retriever、RAG、LangGraph、Chat 或 SSE；这些能力不能从本图推断为已经存在。
