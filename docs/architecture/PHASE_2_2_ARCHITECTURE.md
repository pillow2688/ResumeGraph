# Phase 2.2 架构图：知识文档与版本管理

本文只描述 Phase 2.2 已实现的系统。虚线“未来边界”仅表示知识版本可被后续能力消费，不表示 Job、Worker、Chunk、Embedding、RAG、LangGraph 或 Chat 已实现。

## 1. 当前系统架构图

```mermaid
flowchart LR
    Admin[管理员浏览器]

    subgraph Frontend[React + TypeScript 管理端]
        Projects[项目管理页]
        ProjectDocs[项目知识文档页]
        DocDetail[文档详情与版本历史]
        ApiClient[Typed API Client<br/>credentials include]
    end

    subgraph FastAPI[FastAPI 应用]
        Auth[get_current_admin]
        Routes[Admin Document Routes<br/>JSON + multipart]
        Service[KnowledgeDocumentService<br/>验证、SHA-256、业务规则]
        Repo[KnowledgeDocumentRepository<br/>查询、事务、行锁]
    end

    subgraph Data[基础设施]
        Redis[(Redis<br/>Admin Session)]
        ProjectsTable[(projects)]
        DocsTable[(knowledge_documents)]
        VersionsTable[(document_versions)]
    end

    Future[未来处理与检索边界<br/>当前未实现]

    Admin --> Projects
    Projects --> ProjectDocs
    ProjectDocs --> DocDetail
    Projects --> ApiClient
    ProjectDocs --> ApiClient
    DocDetail --> ApiClient
    ApiClient --> Routes
    Routes --> Auth
    Auth --> Redis
    Routes --> Service
    Service --> Repo
    Repo --> ProjectsTable
    Repo --> DocsTable
    Repo --> VersionsTable
    ProjectsTable -->|1 对多| DocsTable
    DocsTable -->|1 对多| VersionsTable
    VersionsTable -. 原始 draft 版本 .-> Future
```

关键边界：

- Admin 与 Recruiter 的 Cookie/Session 仍然分离；文档接口只接受 Admin；
- Route 不执行 SQL，Service 不依赖 FastAPI Request/Response，Repository 不返回 HTTP 对象；
- PostgreSQL 保存文档事实，Redis 不保存文档内容；
- 前端只通过安全响应访问内容，不读取 HttpOnly Cookie；
- `document_versions.raw_content` 是原始事实，列表接口不返回完整内容。

## 2. 文档创建流程图

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 管理员
    participant UI as React 文档页
    participant Route as FastAPI Route
    participant Auth as get_current_admin
    participant Service as KnowledgeDocumentService
    participant Repo as KnowledgeDocumentRepository
    participant DB as PostgreSQL

    Admin->>UI: 输入标题并粘贴 Markdown 或选择 .md
    UI->>Route: POST documents 或 documents/upload
    Route->>Auth: 校验 Admin Cookie 和 Redis Session
    Auth-->>Route: AdminPrincipal
    Note over Route: 上传最多读取 markdown_max_bytes + 1
    Route->>Service: project_id、title、content、可选 filename
    Service->>Service: 标题清理、UTF-8/BOM、空白/NUL/大小校验
    Service->>Service: 安全 basename、source_type、SHA-256
    Service->>Repo: create_document_with_initial_version
    Repo->>DB: BEGIN
    Repo->>DB: 锁定并校验 Project
    alt Project 不存在
        DB-->>Repo: 无记录
        Repo->>DB: ROLLBACK
        Repo-->>Service: project not found
        Service-->>Route: ProjectNotFoundError
        Route-->>UI: 404 project_not_found
    else Project 存在
        Repo->>DB: INSERT KnowledgeDocument
        Repo->>DB: INSERT DocumentVersion v1 draft
        Repo->>DB: COMMIT
        DB-->>Repo: 文档和 v1
        Repo-->>Service: KnowledgeDocumentRecord
        Service-->>Route: KnowledgeDocumentDetail
        Route-->>UI: 201 文档详情和 v1 摘要
        UI-->>Admin: 展示文档详情或刷新列表
    end
```

文档和 v1 共用同一个事务。任何数据库失败都会回滚，不会留下没有初始版本的逻辑文档。

## 3. 文档版本流程图

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 管理员
    participant UI as React 文档详情页
    participant Route as FastAPI Route
    participant Service as KnowledgeDocumentService
    participant Repo as KnowledgeDocumentRepository
    participant DB as PostgreSQL

    Admin->>UI: 粘贴新 Markdown 或上传新 .md
    UI->>Route: POST versions 或 versions/upload
    Note over Route: get_current_admin 已验证管理员
    Route->>Service: document_id、content、可选 filename
    Service->>Service: 最小安全校验并计算 SHA-256
    Service->>Repo: create_version
    Repo->>DB: BEGIN
    Repo->>DB: SELECT KnowledgeDocument FOR UPDATE
    alt 文档不存在
        DB-->>Repo: 无记录
        Repo->>DB: ROLLBACK
        Route-->>UI: 404 document_not_found
    else 文档存在
        Repo->>DB: 查询相同 content_hash
        alt 内容重复
            DB-->>Repo: 已有版本
            Repo->>DB: ROLLBACK
            Route-->>UI: 409 duplicate_document_version
        else 内容不同
            Repo->>DB: SELECT max(version_number)
            Repo->>DB: INSERT next version，status draft
            Repo->>DB: UPDATE document.updated_at
            Note over DB: 唯一约束保护版本号和内容哈希
            Repo->>DB: COMMIT
            DB-->>Repo: 新版本记录
            Repo-->>Service: DocumentVersionRecord
            Service-->>Route: DocumentVersion
            Route-->>UI: 201 新版本及原始 Markdown
            UI-->>Admin: 刷新历史并默认选中新版本
        end
    end
```

同一 Knowledge Document 的并发版本创建通过行锁串行分配版本号；数据库唯一约束承担最终一致性保护。旧版本不会被更新或覆盖。

## 4. 当前数据关系

```mermaid
erDiagram
    PROJECTS ||--o{ KNOWLEDGE_DOCUMENTS : contains
    KNOWLEDGE_DOCUMENTS ||--|{ DOCUMENT_VERSIONS : has

    PROJECTS {
        uuid id PK
        varchar name
        text description
    }

    KNOWLEDGE_DOCUMENTS {
        uuid id PK
        uuid project_id FK
        varchar title
        timestamptz created_at
        timestamptz updated_at
    }

    DOCUMENT_VERSIONS {
        uuid id PK
        uuid document_id FK
        int version_number UK
        varchar source_type
        varchar original_filename
        text raw_content
        varchar content_hash UK
        varchar status
        timestamptz created_at
    }
```

`version_number` 与 `content_hash` 都是在同一个 `document_id` 范围内唯一。所有版本当前均为 `draft`，且没有级联删除、文档删除或版本删除 API。

## 5. 停止边界

本架构文档没有进入 Phase 2.3。当前不存在 Job、Worker、Chunk、Embedding、pgvector、发布、RAG、LangGraph 或 Chat 实现；这些能力只有在用户明确确认相应阶段后才能设计和实现。

