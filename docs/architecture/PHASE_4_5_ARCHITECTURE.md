# Phase 4.5 架构 — Public Demo 垂直切片

## 组件边界

```text
Browser /
  │ GET /api/v1/public/demo
  │ POST /api/v1/public/demo/session
  ▼
Public Demo API ──────────────── only public status + redirect
  ▼
PublicDemoService
  ├─ PublicDemoRepository ───── public_demo_config (singleton id=1)
  └─ AccessGrantService ─────── existing Grant validation
                               + Recruiter Session creation
                                      │
                                      ▼ HttpOnly Recruiter Cookie
Browser /interview
  ▼
Existing Interview API → RAG → LangGraph Agents
```

Public Demo 的职责在 Interview 之前结束。它不依赖或调用 Retrieval、RAG、Agent、Evidence 工具，
也不改变请求额度的扣减位置。

管理员路径独立：

```text
/admin/public-demo
  → existing Admin Cookie authentication
  → Admin Public Demo API
  → PublicDemoService
  → singleton configuration upsert
```

## 安全不变量

- PostgreSQL Access Grant 仍是授权事实来源；
- Redis Recruiter Session 仍是临时凭证容器；
- Public Demo 只引用 Grant ID，不保存、恢复或返回原始 Access Token；
- Session Cookie 复用现有名称、Path、Secure、HttpOnly、SameSite 和 TTL 规则；
- Grant 撤销、过期、额度用尽或项目范围为空时不能创建新公开 Session；
- 已创建 Session 的每次 Interview 请求仍执行既有 PostgreSQL 重验证；
- 管理员和 Recruiter Cookie/Depends 边界保持分离；
- 公开状态响应不包含 Grant、项目范围、权限元数据或内部错误。

## 数据一致性

`public_demo_config.id = 1` 同时由主键和 Check Constraint 约束。Repository upsert 在更新已有
记录时加行锁；首次并发创建由主键/Check Constraint 最终保护。配置只绑定已有 Access Grant，
外键阻止悬空引用。

管理员开启配置前调用 `validate_grant_for_session`。关闭配置时仍要求 Grant 存在，但允许管理员
先保存一个当前不可用于公开 Session 的 Grant；再次开启时必须通过完整校验。

## 前端布局

```text
InterviewLayout (100dvh, overflow hidden)
├─ ConversationSidebar
└─ Main column (min-height: 0)
   ├─ InterviewHeader (shrink: 0)
   └─ ChatWindow (min-height: 0, flex: 1)
      ├─ ChatMessageList (overflow-y: auto)
      └─ ChatComposer (sticky bottom, shrink: 0)
```

只有 `ChatMessageList` 承担垂直滚动，Header 和 Composer 始终可见。`MessageBubble` 统一消息方向，
`CitationCard` 只展示后端已允许公开的 Citation 字段。
