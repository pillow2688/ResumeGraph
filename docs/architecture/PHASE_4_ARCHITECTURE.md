# Phase 4 架构 — 受授权约束的 LangGraph 多 Agent 面试

## 1. Phase 4 总体架构

```mermaid
flowchart LR
    R[Recruiter Browser] --> F[React Chat UI]
    F -->|POST SSE / JSON| API[FastAPI Interview API]
    API --> AUTH[Session + Grant Revalidation]
    AUTH --> WF[InterviewWorkflowService]
    WF --> G[LangGraph InterviewGraph]
    G --> A[Five Agents]
    A --> RET[RetrievalService]
    RET --> PG[(PostgreSQL + pgvector)]
    WF --> REDIS[(Redis Conversation / Lock / Idempotency)]
    A --> CHAT[DeepSeek ChatProvider]
    RET --> EMB[Zhipu EmbeddingProvider]
    API -->|public events only| F
```

PostgreSQL 是授权和发布知识的事实源；Redis 只保存短期会话与并发控制；LLM 无权创建或扩大项目
范围。

## 2. Supervisor 与四个专业 Agent

```mermaid
flowchart TD
    Q[Question + limited context] --> S[Interview Supervisor]
    S -->|ask_profile_agent| P[Profile Agent]
    S -->|ask_project_agent| J[Project RAG Agent]
    S -->|ask_technical_agent| T[Technical Agent]
    P --> B[Evidence Bundles]
    J --> B
    T --> B
    B --> S
    S --> D[Draft]
    D -->|ask_verification_agent| V[Verification Agent]
    V -->|pass| FINAL[Final Answer]
    V -->|repair instruction, once| S
```

Supervisor 只能把专业 Agent 当作工具，不能直接访问数据库、Embedding 或管理员接口。

## 3. Agent 工具权限

```mermaid
flowchart LR
    P[Profile Agent] --> PO[get_profile_overview]
    P --> PS[search_profile_knowledge]

    J[Project Agent] --> JL[list_authorized_projects]
    J --> JO[get_project_overview]
    J --> JS[search_project_knowledge]

    T[Technical Agent] --> TO[get_technical_topic_overview]
    T --> TS[search_technical_knowledge]

    V[Verification Agent] --> VH[validate_citation_handles]
    V --> VE[revalidate_evidence]
    V --> VS[check_evidence_scope]
    V --> VG[check_access_grant_scope]
```

工具由 Python 白名单绑定；Agent 不能按名称构造未知工具，也不能访问其他 Agent 的私有工具。

## 4. Profile / Project / Technical Retrieval

```mermaid
flowchart TD
    QUERY[Query Embedding] --> BASE[Shared RetrievalRepository]
    BASE --> PUB{Current published Version?}
    PUB -->|yes| CH{Chunk enabled and hash valid?}
    CH -->|yes| ID{Embedding identity valid?}
    ID -->|yes| SCOPE{Scope filter}
    SCOPE -->|profile| PROFILE[Global published Profile]
    SCOPE -->|technical| TECH[Global published Technical / general]
    SCOPE -->|project| INTERSECT[requested IDs ∩ allowed IDs]
    INTERSECT --> PROJECT[Authorized published Project only]
    PROFILE --> TOPK[Unified Evidence]
    TECH --> TOPK
    PROJECT --> TOPK
```

Project 空交集返回受控范围错误，不回退到全部项目。

## 5. 混合问题回答

```mermaid
flowchart LR
    Q[How did your project solve cache avalanche?] --> PA[Project Agent]
    Q --> TA[Technical Agent]
    PA --> I[project_fact: current Redis usage]
    PA --> P[planned_solution: future cache plan]
    TA --> K[technical_knowledge: avalanche principles]
    I --> M[Supervisor synthesis]
    P --> M
    K --> M
    M --> O[current practice → boundary → principle → future plan]
```

`technical_knowledge` 不能变成“项目已经实现”，`planned_solution` 不能使用完成时表达。

## 6. Verification 与一次修正

```mermaid
stateDiagram-v2
    [*] --> DeterministicChecks
    DeterministicChecks --> SemanticCheck: handles/scope/publication valid
    DeterministicChecks --> FinalizeSafe: invalid evidence
    SemanticCheck --> Finalize: passed
    SemanticCheck --> Repair: failed and budget remains
    Repair --> DeterministicChecks: verify once more
    SemanticCheck --> FinalizeSafe: no repair budget
    Finalize --> [*]
    FinalizeSafe --> [*]
```

确定性检查重新读取数据库；语义检查识别无证据结论、实现边界混淆、虚构指标和 Prompt 泄露。

## 7. Redis Conversation

```mermaid
flowchart TD
    CREATE[Create Conversation] --> C[(interview_conversation:UUID)]
    C --> OWN[Session fingerprint + Grant ID]
    C --> CTX[Recent summaries / active topics]
    C --> TTL[TTL]
    ASK[Ask with request_id] --> LOCK[(Conversation lock)]
    ASK --> IDEM[(Idempotency record)]
    LOCK --> RUN[One graph run]
    RUN --> SAVE[Save final summaries]
    SAVE --> C
    TTL --> EXPIRE[Automatic expiry]
```

Conversation 不是事实 Evidence，也不创建永久 Message 表。

## 8. SSE 公开状态

```mermaid
sequenceDiagram
    participant UI as React UI
    participant API as FastAPI SSE
    participant WF as Workflow
    participant G as LangGraph
    UI->>API: POST ask/stream
    API->>WF: validated question + event sink
    WF->>G: run authorized state
    G-->>API: question_received / routing_started
    G-->>API: specialist search events
    G-->>API: drafting / verification events
    API-->>UI: heartbeat when idle
    G-->>API: answer_completed payload
    API-->>UI: final public response
```

SSE 不发送 Chain of Thought、Prompt、SQL、完整 Evidence 或工具原始参数。

## 9. request_count

```mermaid
flowchart TD
    REQ[Incoming ask] --> VALID[Validate input/session/grant/scope/ownership]
    VALID -->|invalid| NOBILL[Return without billing]
    VALID -->|valid| ATOMIC[Atomic UPDATE request_count + 1 RETURNING]
    ATOMIC -->|quota available| GRAPH[Run all selected Agents]
    ATOMIC -->|exhausted| LIMIT[Quota error]
    GRAPH --> RESULT[answered / partial / insufficient / provider error]
    RESULT --> ONCE[No second charge and no automatic refund]
```

同一 `request_id` 的幂等重放返回缓存结果或受控失败，不再次扣费。

## 10. Grant 撤销

```mermaid
sequenceDiagram
    participant Admin
    participant PG as PostgreSQL
    participant UI as Recruiter UI
    participant API
    participant Redis
    Admin->>PG: set revoked_at
    UI->>API: next conversation request
    API->>PG: revalidate Session Grant
    PG-->>API: revoked
    API-->>UI: sanitized authentication failure
    UI->>UI: clear messages and conversation ID
    UI->>UI: navigate /access
    Redis-->>Redis: conversation expires or is explicitly deleted
```

Redis 中旧 Session/Conversation 不能覆盖 PostgreSQL 撤销事实。

## 11. 前端聊天请求链路

```mermaid
flowchart TD
    W[Welcome suggestions] -->|fill only| COMPOSER[ChatComposer]
    COMPOSER --> USER[Right-aligned user message]
    USER --> PLACEHOLDER[Left AI placeholder]
    PLACEHOLDER --> STREAM[Fetch POST SSE parser]
    STREAM --> PROGRESS[AgentProgress public events]
    STREAM --> ANSWER[AssistantMessage Markdown]
    ANSWER --> CITES[CitationList]
    CITES -->|desktop| RIGHT[Right Citation Drawer]
    CITES -->|mobile| BOTTOM[Bottom Citation Drawer]
    ANSWER --> CONTEXT[Project / topic / turn context]
    STREAM -->|error| INLINE[Inline recoverable error]
```

React 只保存当前页面消息；新建对话删除旧 Redis Conversation，清空消息和主题，但保留有效
Recruiter Session 与 Access Grant。
