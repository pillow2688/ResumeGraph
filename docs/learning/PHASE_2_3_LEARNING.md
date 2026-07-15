# Phase 2.3 开发者学习笔记：异步文档处理与 Chunk 切分

## 1. 这一阶段解决了什么问题

Phase 2.2 已经能够保存不可变的 Markdown `DocumentVersion`，但原始文档还不是适合后续检索消费的结构化数据。Phase 2.3 建立了第一条可追踪的派生数据链：管理员为指定版本创建持久化 Job，独立 Worker 读取原文，执行确定性清洗和 Markdown-aware 切分，再把结果保存为 `document_chunks`。

```text
DocumentVersion.raw_content
→ IngestionJob
→ Worker
→ Cleaning
→ Chunking
→ DocumentChunk
```

这条链只把原始 Markdown 转换成可检查的 Chunk。它没有生成 Embedding，也没有让 Chunk 进入公开检索。

## 2. 为什么需要异步任务

文档处理和普通 CRUD 不同。它可能包含较多文本扫描、分段、哈希计算以及多次数据库写入，未来还可能连接更慢的外部处理步骤。把这些工作建模为异步任务有四个直接价值：

- **HTTP 请求及时结束**：API 创建 Job 后返回 `202 Accepted + job_id`，管理员不必一直占用上传请求等待处理完成；
- **处理过程可观察**：`status`、`stage`、`progress`、开始时间、结束时间和安全错误信息都持久化在 PostgreSQL；
- **失败可以被记录**：Worker 失败不等同于浏览器连接断开，Job 仍能留下明确的终态；
- **运行资源可以隔离**：API 和 Worker 是独立进程，Worker 的并发数、超时和关闭宽限可以单独限制。

如果没有 Job，调用方只能知道“请求成功或失败”，无法判断任务是否排队、正在清洗、正在保存，还是已经在后台失败。

## 3. FastAPI 为什么不能直接执行文档处理

FastAPI 的职责是处理 HTTP 边界：认证管理员、验证路径参数、调用用例、返回状态码和安全响应。它不适合在请求处理函数里完成整条文档 Pipeline。

直接处理会带来以下问题：

1. 请求持续时间与文档大小绑定，容易触发浏览器、反向代理或服务器超时；
2. 即使代码写成 `async def`，同步的文本扫描和哈希也不会自动变成非阻塞工作；
3. API 进程重启或连接中断时，处理状态很难恢复和解释；
4. Web 请求并发与文档处理并发互相争抢资源；
5. Route 会同时承担认证、HTTP、业务流程和重计算，难以测试和维护。

因此当前 Route 只调用 `IngestionService.create_job()`，真正的 `clean_markdown()` 和 `split_markdown()` 只在独立 Worker 中执行。`BackgroundTasks` 也没有被用作队列替代品，因为它没有提供持久化 Job、独立 Worker 和跨 API 重启的任务记录。

## 4. API 和 Worker 如何解耦

API 与 Worker 的最小共享契约只有 `job_id`：

1. API 事务创建 `ingestion_jobs`，并把 `DocumentVersion.status` 设为 `processing`；
2. API 只把 Job UUID 写入 ARQ 的 Redis 队列；
3. Worker 从队列得到 UUID 后，再从 PostgreSQL 加载 Job、版本和 `raw_content`；
4. Worker 逐阶段更新 Job，并在同一个完成事务中替换 Chunk、完成 Job、更新版本状态。

队列消息不携带完整文档、管理员 Cookie 或授权信息。这样可以避免队列成为第二份业务数据源，也减少敏感内容出现在 Redis 的机会。

分层职责保持清晰：

- `app/api/routes/admin_ingestion.py`：管理员认证和 HTTP 契约；
- `app/services/ingestion.py`：创建 Job、入队、查询状态和错误翻译；
- `app/infrastructure/job_queue.py`：ARQ/Redis 适配；
- `app/worker.py`：Worker 进程生命周期和执行限制；
- `app/services/ingestion_worker.py`：文档处理用例；
- `app/repositories/ingestion.py`：SQLAlchemy 查询、锁和事务。

## 5. Redis 在任务系统中的作用

Redis 在 Phase 2.3 中是**临时任务投递通道**，不是任务状态的事实来源。

它负责：

- 保存 ARQ 待消费消息；
- 通知独立 Worker 有哪个 `job_id` 需要执行；
- 提供短期队列协调和 Worker 健康键。

它不负责：

- 唯一保存 Job 状态；
- 保存权威文档版本或 Chunk；
- 决定某个版本是否处理完成；
- 承担管理员授权判断。

持久化状态必须查询 PostgreSQL。即使 API 重启，已创建的 Job 记录仍然存在。若 API 在数据库提交后、Redis 入队前硬中断，管理员重复调用 process 接口会重新入队仍为 `pending` 的同一个 Job。

## 6. Job 状态机设计

当前 Job 有四种状态：

```text
pending → processing → completed
                   ↘ failed
pending ───────────→ failed
```

- `pending`：Job 已经持久化，等待 Worker 开始；
- `processing`：Worker 已领取并正在执行 Pipeline；
- `completed`：Chunk 已经原子保存，版本进入 `ready_for_review`；
- `failed`：入队或处理失败，保存安全错误信息，版本恢复为 `draft`。

数据库 partial unique index 保证同一 `document_version_id` 最多只有一个 active Job（`pending` 或 `processing`）。重复请求会复用 active Job；已经进入 `processing` 的 Job 不会被重复入队。

状态机的价值是限制非法组合。如果没有明确终态，系统可能出现“Chunk 已保存但 Job 仍 processing”或“Job completed 但版本仍 draft”等难以解释的状态。当前保存 Chunk、完成 Job 和更新版本在同一个 PostgreSQL 事务中完成。

## 7. `status` 和 `stage` 的区别

`status` 回答“任务整体处于什么生命周期”，`stage` 回答“处理中的当前步骤是什么”。二者不能混为一个字段。

例如：

```text
status = processing
stage = chunking
progress = 55
```

这表示任务尚未完成，当前正在切分。当前 stage 为：

- `reading`；
- `cleaning`；
- `chunking`；
- `saving`。

如果把它们合并成 `cleaning`、`chunking`、`completed` 等一个枚举，调用方必须自己猜哪些值是进行中、哪些值是终态；失败发生在哪个阶段也更难表达。分离后，前端可以稳定展示总体状态，同时把 stage 本地化为“读取、清洗、切分、保存”。

## 8. 文档清洗为什么影响未来 RAG

RAG 的检索对象不是抽象的“文档含义”，而是具体字符串产生的 Chunk 和向量。不可控的文本差异会改变段落边界、哈希和未来向量输入。

Phase 2.3 只做确定性清洗：

- 删除开头 UTF-8 BOM；
- 删除 NUL；
- 将 CRLF/CR 统一为 LF；
- 清理行尾空格和 Tab；
- 压缩连续空行；
- 去除全文首尾空白；
- 拒绝清洗后为空的文档；
- 计算清洗结果 SHA-256。

这些规则让同样输入得到同样输出，使 Chunk 顺序和内容哈希可复现。若跳过清洗，隐藏控制字符和换行差异可能造成无意义的重复 Chunk、错误段落边界和不稳定的缓存键。若使用 LLM“清洗”，则可能改写候选人的事实，因此本阶段明确禁止。

## 9. Chunk 为什么影响检索质量

未来检索的基本单位是 Chunk。Chunk 太大和太小都会损害质量：

- **太大**：一个向量混合多个主题，命中后携带大量无关上下文；
- **太小**：职责、原因和结果被拆散，单个片段缺少回答问题所需的语义；
- **边界错误**：标题属于上一段、正文属于下一段，检索结果即使相似也难以解释；
- **顺序不稳定**：重新处理后索引和引用难以对照。

当前实现先按标题形成 Section，再在超出目标长度时按段落二次切分。`chunk_index` 从 0 开始按源文顺序稳定生成；每个 Chunk 保存独立哈希和字符数。配置的 2,000 字符是段落感知的切分目标，不是破坏语义的硬上限。

## 10. Markdown-aware chunking 为什么优于固定切割

固定“每 N 个字符切一刀”不了解 Markdown 结构，可能在以下位置断开：

- 标题与其正文之间；
- 一句话或一个技术决策中间；
- fenced code block 中间；
- 问题、取舍和结果之间。

Markdown-aware 策略利用作者已经写出的结构：ATX 标题定义主题层级，空行定义段落，fenced code 被视为不可随意拆开的块。第一版优先保证语义完整，再控制长度；单个超长段落或代码块会原样保留，而不是硬切。

当前实现只结构化识别 ATX 标题。这是明确的第一版限制，不应把它描述为完整 CommonMark 解析器。

## 11. `heading_path` metadata 为什么重要

`heading_path` 保存 Chunk 所处的标题链，例如：

```json
["技术架构", "Worker"]
```

它有三类价值：

1. **恢复上下文**：即使 Chunk 内容很短，也知道它属于哪个主题和子主题；
2. **可解释展示**：管理员页面可以展示来源路径，而不是只显示一段孤立文本；
3. **未来检索元数据**：后续系统可以把标题路径与正文共同用于检索、排序和引用展示。

第一个一级标题被视作文档标题，不进入 `heading_path`，但标题文本仍保留在对应 Chunk 内容中。二次按段落拆分时，Section 标题会重复写入每个子 Chunk，以保留局部语义。

## 12. Phase 2.3 与未来 RAG 的关系

Phase 2.3 建立的是 RAG 之前的**可追溯文本派生层**：

```text
权威 DocumentVersion
→ 可复现清洗
→ 有结构的 DocumentChunk
→ 保留 document_version_id、heading_path、hash 和顺序
```

这使未来组件可以消费明确、稳定、可回溯的文本单元，而不必直接解析原始上传内容。但当前 Chunk 仍是未发布的管理员数据；系统没有 Embedding、pgvector、Retriever、RAG、LangGraph、Chat 或 SSE，公开 Recruiter 路径也不能读取这些 Chunk。

最重要的安全边界保持不变：未来任何检索都必须在可信服务端执行授权和发布状态过滤，模型不能根据文本内容扩大项目范围，也不能把未发布 Chunk 变成公开证据。

## 13. 如何运行和验证

启动本地依赖、API 与独立 Worker：

```powershell
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

在另一个终端启动 Worker：

```powershell
uv run arq app.worker.WorkerSettings
```

核心验证命令：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

Set-Location frontend
npm run lint
npm run typecheck
npm test
npm run build
```

学习时建议依次阅读：

1. `app/services/ingestion.py`；
2. `app/infrastructure/job_queue.py`；
3. `app/worker.py`；
4. `app/services/ingestion_worker.py`；
5. `app/ingestion/cleaning.py`；
6. `app/ingestion/chunking.py`；
7. `app/repositories/ingestion.py`。
