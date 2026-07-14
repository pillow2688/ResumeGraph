# ResumeGraph Phase 1 总结

本文只总结截至 2026-07-14 已在当前仓库中实现并验证的 Phase 1 能力。它不定义后续阶段，也不把尚未实现的功能写成已完成。

## 1. Phase 1 的目标

Phase 1 建立了管理员和面试官进入 ResumeGraph 的两套独立访问控制路径：

- 管理员先通过 CLI 创建账号，再使用用户名和密码登录管理端。
- 面试官不注册账号，而是使用管理员创建的 Access Grant 所对应的一次性展示访问码换取短期 Recruiter Session。
- 管理员与面试官使用不同的 Cookie、Redis Key 前缀、Principal 和 FastAPI 鉴权依赖，彼此不能替代。
- 面试官的项目范围来自 Grant 与 Project 在 PostgreSQL 中的当前关联，只能看到该 Grant 实际授权的项目。
- FastAPI 负责在请求入口执行鉴权依赖和返回受控错误；PostgreSQL 保存长期业务数据和最终授权事实；Redis 保存短期 Session 与失败限流状态。

权限不交给未来的 LLM 判断。LLM 输入、客户端参数和 Redis 中的项目快照都不能创建、扩大或覆盖授权范围；受保护请求必须先由可信服务端代码完成授权。

## 2. Phase 1.1：数据库模型

Phase 1.1 使用 SQLAlchemy 2.x async 架构定义并通过 Alembic 创建了四张业务表：

- `admin_users`：UUID 主键 `id`、唯一 `username`、`password_hash`、`created_at` 和 `updated_at`。
- `projects`：UUID 主键 `id`、`name`、`description`、`created_at` 和 `updated_at`。
- `access_grants`：UUID 主键 `id`、`name`、唯一索引保护的 `token_hash`、`expires_at`、`max_requests`、`request_count`、可空的 `revoked_at` 和 `created_at`。
- `grant_projects`：以 `(grant_id, project_id)` 为联合主键的关联表，两个外键均使用 `ON DELETE CASCADE`。

`AccessGrant` 与 `Project` 通过 `grant_projects` 形成多对多关系：一个 Grant 可以授权多个项目，一个项目也可以被多个 Grant 授权。ORM 关系设置了与数据库级联删除一致的 `passive_deletes=True`。

密码只存放 Argon2 哈希，Access Token 只存放服务端 HMAC-SHA256 摘要。时间列使用带时区的时间类型；`created_at` 和两个 `updated_at` 列具有数据库默认时间。`updated_at` 的自动刷新主要由 SQLAlchemy `onupdate` 在 ORM 更新时触发，当前没有数据库 Trigger，不能假定所有原生 SQL 更新都会自动刷新它。

Alembic Migration `a5b170c969c4_create_phase_1_1_models.py` 的 `upgrade()` 创建上述表、约束和索引，`downgrade()` 按依赖顺序删除它们。

## 3. Phase 1.2：管理员认证

Phase 1.2 已实现：

- 通过 `app.cli.create_admin` CLI 交互式读取并确认密码，创建规范化后的管理员用户名；CLI 不接受明文密码命令行参数。
- 使用 Argon2 对管理员密码进行哈希和验证；不存在的用户名也执行固定的 dummy Argon2 验证，减少用户枚举时的时序差异。
- `POST /api/v1/admin/auth/login` 管理员登录。
- 登录成功后创建高熵、不透明的 Admin Session Token；Redis Key 使用 Token 的 SHA-256 摘要，不直接包含原始 Token。
- Admin Redis Session 保存管理员 ID、用户名、创建时间和固定过期时间，并设置 TTL。
- Session Token 只通过独立的 HttpOnly、SameSite=Lax 管理员 Cookie 传递；`Secure` 由环境配置控制，生产环境强制开启。
- `get_current_admin` 从管理员 Cookie 读取 Session，查询 Redis 后再按管理员 ID 查询 PostgreSQL，返回独立的 `AdminPrincipal`，不返回 ORM Model。
- `GET /api/v1/admin/auth/me` 返回当前管理员的安全身份信息。
- `POST /api/v1/admin/auth/logout` 删除对应 Admin Redis Session 并清除管理员 Cookie，行为幂等。
- 管理员登录失败限流使用 Redis 固定窗口计数；标识由规范化用户名和 `request.client.host` 组成并经过摘要，不信任客户端自行提交的代理 IP 头。
- PostgreSQL 或 Redis 不可用、依赖超时及未知异常都会转换为脱敏响应，不向客户端暴露 DSN、驱动异常或堆栈。

## 4. Phase 1.3：Recruiter Access Grant

Phase 1.3 已实现：

- 管理员可以创建、列表查看、查看详情和幂等撤销 Access Grant。
- 创建 Grant 时用 `secrets` 生成高熵原始 Access Token；原始 Token 只在创建成功响应中显示一次，丢失后不能恢复，只能撤销并重新创建。
- PostgreSQL 不保存原始 Access Token，只保存 `HMAC-SHA256(raw_token, access_token_pepper)` 摘要；Pepper 来自类型化 `SecretStr` 配置。
- 创建 Grant 和 `grant_projects` 关联在同一个数据库事务中完成；任何项目不存在时不会产生部分 Grant。重复项目 ID 会被去重。
- `POST /api/v1/access/exchange` 接收 JSON 请求体中的 Token，不支持 URL Query Token。
- Exchange 按摘要查询 PostgreSQL，并统一检查 Grant 是否存在、未撤销、未过期、未耗尽且仍有有效项目。
- Exchange 成功后创建独立的 Recruiter Redis Session。Session TTL 是配置 TTL 与 Grant 剩余有效期的较小值，并且不会滑动续期。
- Recruiter Session Token 只进入独立的 HttpOnly Recruiter Cookie；Redis Key 使用 Session Token 摘要，不直接包含原始 Token。
- Redis 中保存 `grant_id`、创建时间、过期时间和 `allowed_project_ids_snapshot`；项目快照只用于辅助信息，不是最终权限来源。
- `get_current_recruiter` 返回独立的 `RecruiterPrincipal`，其中包含 Grant 身份、当前允许项目、Grant 过期时间和剩余额度。
- `GET /api/v1/access/me` 返回当前 Grant 的安全元数据和当前授权项目。
- `POST /api/v1/access/logout` 删除 Recruiter Redis Session 并清除 Recruiter Cookie，不影响 Admin Session。
- Token Exchange 的失败尝试使用 Redis 按 `request.client.host` 限流；失败计数 Key 不包含原始 Access Token，成功交换会清除该 IP 的失败计数。
- 每次受保护访问都根据 Redis Session 中的 `grant_id` 重新查询 PostgreSQL，并重新验证撤销、过期、额度和当前项目关系。
- 因为受保护访问不把 Redis 项目快照当作授权事实，Grant 撤销后旧 Recruiter Session 的下一次访问会立即失败，无需扫描删除全部 Recruiter Session。

Exchange 和 `/access/me` 当前只检查 `request_count < max_requests`，不会增加 `request_count`。

## 5. 当前系统能完成什么

当前系统已经形成以下完整访问控制闭环：

```text
创建管理员
→ 管理员登录
→ 创建 Access Grant
→ 获得一次性 Access Token
→ Recruiter 使用 Token 换取 Session
→ 查看当前授权项目
→ 管理员撤销 Grant
→ 原 Recruiter Session 立即失效
→ 管理员 Session 保持有效
```

创建 Grant 前必须已有 Project 记录。当前没有管理员项目 CRUD；现有测试和本地端到端验证通过测试夹具或安全的本地数据库方式插入虚构 Project。

## 6. 当前真实 API

下表来自当前 `app/api/routes/` 路由代码。未显式设置成功状态码的 FastAPI 路由使用默认的 `200 OK`。

| Method | Path | 用途 | Admin Cookie | Recruiter Cookie | 主要成功状态码 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/v1/health/live` | API 进程存活检查 | 不需要 | 不需要 | 200 |
| GET | `/api/v1/health/ready` | PostgreSQL 与 Redis 就绪检查 | 不需要 | 不需要 | 200 |
| POST | `/api/v1/admin/auth/login` | 管理员用户名和密码登录并设置 Admin Cookie | 不需要 | 不需要 | 200 |
| GET | `/api/v1/admin/auth/me` | 查询当前管理员 | 需要 | 不需要 | 200 |
| POST | `/api/v1/admin/auth/logout` | 删除 Admin Session 并清除 Admin Cookie | 可选；无 Cookie 也幂等 | 不需要 | 204 |
| POST | `/api/v1/admin/access-grants` | 创建 Grant，并唯一一次返回原始 Access Token | 需要 | 不需要 | 201 |
| GET | `/api/v1/admin/access-grants` | 按稳定顺序列出 Grant 安全元数据 | 需要 | 不需要 | 200 |
| GET | `/api/v1/admin/access-grants/{grant_id}` | 查看单个 Grant 安全元数据 | 需要 | 不需要 | 200 |
| POST | `/api/v1/admin/access-grants/{grant_id}/revoke` | 幂等撤销 Grant | 需要 | 不需要 | 200 |
| POST | `/api/v1/access/exchange` | 用 Access Token 换取 Recruiter Cookie | 不需要 | 不需要 | 200 |
| GET | `/api/v1/access/me` | 查询当前 Recruiter Grant 和授权项目 | 不需要 | 需要 | 200 |
| POST | `/api/v1/access/logout` | 删除 Recruiter Session 并清除 Recruiter Cookie | 不需要 | 可选；无 Cookie 也幂等 | 204 |

## 7. 四条核心数据流

### 管理员登录

1. Route 从请求体读取用户名和密码，并使用 `request.client.host` 作为限流来源。
2. Service 规范化用户名，查询 Redis 登录失败计数，再从 PostgreSQL 查询管理员。
3. 密码通过 Argon2 在线程中验证；失败时记录限流计数并返回统一、脱敏错误。
4. 成功时清除失败计数，生成高熵 Session Token，并以 Token 摘要构造 Admin Redis Key。
5. Redis 写入固定 TTL 的管理员 Session，Route 只把原始 Session Token 写入 HttpOnly Admin Cookie。

### Access Grant 创建

1. `get_current_admin` 先验证 Admin Session 和当前 PostgreSQL 管理员身份。
2. Schema 和 Service 校验名称、带时区且晚于当前时间的过期时间、额度上限及项目列表，并去除重复项目 ID。
3. Service 生成原始 Access Token，并使用 Pepper 计算 HMAC-SHA256 摘要。
4. Repository 在一个数据库 Session/事务中确认所有 Project 存在，再创建 `access_grants` 和 `grant_projects`；任一项目不存在时不提交部分数据。
5. 成功响应返回 Grant 安全元数据和唯一一次展示的原始 Token，不返回 `token_hash`。

### Recruiter Token Exchange

1. Route 只从 JSON 请求体读取 Access Token，并把 `request.client.host` 交给失败限流器。
2. Service 先检查 Redis 限流，再验证 Token 格式并计算 HMAC-SHA256 摘要。
3. Repository 按摘要从 PostgreSQL 读取 Grant 及其项目关系；Service 统一验证撤销、过期、额度和项目范围。
4. 验证成功后生成独立 Session Token，按 `min(配置 TTL, Grant 剩余有效期)` 创建 Recruiter Redis Session，并清除该 IP 的失败计数。
5. Route 只把 Session Token写入 HttpOnly Recruiter Cookie；JSON 响应不包含 Session Token。Exchange 不扣减 `request_count`。

### Recruiter `/access/me` 权限重验证

1. `get_current_recruiter` 从独立 Recruiter Cookie 读取 Session Token，并用摘要后的 Redis Key 查找 Session。
2. Service 只采用 Redis Session 中的 `grant_id` 定位授权，不信任 `allowed_project_ids_snapshot` 扩大范围。
3. Repository 重新从 PostgreSQL 加载 Grant 和当前 `grant_projects`/Project 关系。
4. Service 再次检查 Grant 未撤销、未过期、未耗尽且项目范围非空，然后从 PostgreSQL 当前记录构造 `RecruiterPrincipal`。
5. `/access/me` 只序列化该 Principal 中的授权项目；校验失败统一返回 Recruiter 401。

## 8. PostgreSQL 与 Redis 的职责

| 对比项 | PostgreSQL | Redis |
| --- | --- | --- |
| 数据生命周期 | 长期、持久化业务数据 | 短期、可过期状态 |
| 管理员数据 | `admin_users` 身份与密码哈希 | Admin Session |
| Grant 数据 | `access_grants`、Token 摘要、过期/撤销/额度状态 | Recruiter Session 中的 `grant_id` 和调试快照 |
| 项目权限 | `projects` 与 `grant_projects` 当前关系，是最终授权事实 | `allowed_project_ids_snapshot` 不能作为最终授权事实 |
| 限流 | 不保存限流计数 | 管理员登录失败计数、Token Exchange 失败计数 |
| 失效方式 | Grant 撤销、过期、耗尽或项目关系变化 | Session 固定 TTL、显式 Logout 删除 |

Redis 只保存管理员短期 Session、Recruiter 短期 Session、登录失败限流和 Token Exchange 失败限流。Redis 不是最终权限事实来源；即使 Redis Session 仍存在，PostgreSQL 当前授权无效时，请求也必须失败。

## 9. 已实现的安全边界

- 管理员和 Recruiter 使用不同 Cookie 名称和 Cookie 路径。
- 两套 Session Store 使用不同 Redis Key 前缀：`admin_session:` 与 `recruiter_session:`。
- 两类身份分别使用 `AdminPrincipal` 和 `RecruiterPrincipal`。
- 两类鉴权分别使用 `get_current_admin` 和 `get_current_recruiter`。
- Recruiter Cookie 不能通过管理员鉴权，也不能访问管理员 Grant 接口；Admin Cookie 不能通过 Recruiter 鉴权。
- 原始 Access Token 只在 Grant 创建响应中显示一次，数据库只保存 HMAC-SHA256 摘要。
- 原始 Admin/Recruiter Session Token 不直接进入 Redis Key，Key 只包含摘要。
- 管理员密码只以 Argon2 哈希保存；CLI 不通过命令行参数接收密码。
- Token、Cookie、密码和 Pepper 不写入日志，受控错误也不会回显这些输入。
- Redis 中伪造或过期的项目快照不能扩大 PostgreSQL 当前授权范围。
- Grant 被撤销、已过期、额度耗尽或授权项目范围为空时，Exchange 和已有 Recruiter Session 都不能继续访问。
- PostgreSQL 或 Redis 故障返回脱敏的 503；通用错误响应不包含 DSN、堆栈或原始驱动异常。
- 登录与 Exchange 限流标识和 Session Redis Key 都使用摘要，不包含原始 Token 或 Cookie 内容。

## 10. 当前尚未实现的内容

- 管理员项目 CRUD。
- 知识文档管理。
- 文档处理。
- Chunk。
- Embedding。
- pgvector 检索。
- RAG。
- LangGraph。
- Chat。
- SSE。
- 前端。
- 云部署。
- `request_count` 的真实业务扣减。

## 11. 实际验证结果

截至 2026-07-14，已有的真实验证记录如下：

- `uv run ruff check .`：通过，输出 `All checks passed!`。
- `uv run ruff format --check .`：通过，58 个文件已经格式化。
- `uv run pytest -q`：通过，`131 passed in 5.68s`。
- Alembic：在真实 PostgreSQL 容器中成功执行 `upgrade head`；`alembic current` 位于 `a5b170c969c4 (head)`；确认本地数据库无重要数据后成功完成一次 `downgrade base` 再 `upgrade head`；最新 `uv run alembic check` 输出 `No new upgrade operations detected.`。
- `docker compose -f docker-compose.yml config --quiet`：退出码 0，Compose 配置校验通过。
- PostgreSQL、Redis 与 API 端到端验证已真实执行：通过 CLI 创建管理员，插入虚构 Project，管理员登录并创建 Grant，使用唯一一次显示的 Access Token 完成 Exchange，Recruiter Cookie 可访问 `/api/v1/access/me`；管理员撤销 Grant 后，原 Recruiter Cookie 再访问 `/access/me` 失败，而 Admin Cookie 仍然有效；Recruiter Logout 不影响 Admin Session。
- 端到端验证运行了两次，使用的临时管理员、Project、Grant 和 Redis Session 已清理，未留下测试业务数据，验证源脚本也未进入 Git。工作区仍有一个被 `.gitignore` 排除的验证脚本 Python 字节码缓存；它不是业务数据，也不属于提交内容。

以上记录只描述已经实际运行过的检查；本文没有声称执行新的 Phase 2 或后续功能验证。

## 12. Phase 1 涉及的后端知识

- SQLAlchemy Model：把 Python 类型化模型映射为 PostgreSQL 表结构和关系。
- Alembic：以可升级、可回退的 Migration 管理数据库结构。
- Repository / Service / Route：分别承载持久化、业务用例/事务编排和 HTTP 边界。
- Authentication：确认管理员或 Recruiter Session 是否代表有效身份。
- Authorization：根据当前 Grant 和项目关系决定 Recruiter 可以访问什么。
- 密码哈希：使用 Argon2 保存和验证管理员密码，避免明文落库。
- Redis Session：保存可撤销、可过期的服务端短期会话。
- TTL：为 Session 和失败计数设置固定生命周期。
- HttpOnly Cookie：让浏览器携带 Session Token，同时禁止前端脚本读取。
- FastAPI Depends：在进入受保护 Route 前执行独立的管理员或 Recruiter 鉴权。
- 多对多关系：通过 `grant_projects` 表达 Grant 与 Project 的双向授权关系。
- 事务：确保 Grant 和全部项目关联要么一起成功，要么不产生部分数据。
- 限流：使用 Redis 固定窗口计数限制登录和 Exchange 暴力尝试。
- 错误脱敏：把基础设施异常转换为稳定错误码，不暴露秘密和内部实现。
