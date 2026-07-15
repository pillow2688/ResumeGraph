# Phase 3 外部环境验收计划

> **执行约束：** 在当前 dirty 工作树内逐项验收；不使用子代理，不执行 Git 提交、清理、
> 重置、合并、Tag 或 Push。只有证据确认 `ApplicationBug` 时才做测试先行的最小修复。

**目标：** 真实验证 Provider、Docker Compose、本地前后端、浏览器三问、Citation、额度和 Grant
撤销；全部通过后关闭 Phase 3 检查点。

**架构：** 沿实际依赖顺序从进程代理与网络边界开始，再调用项目现有 Provider，随后验证
Docker daemon 与 Compose，最后通过同源前端完成浏览器验收。每个失败必须归类，不能把权限、
代理、网络、容器和应用错误混为一类。

**技术栈：** PowerShell、Python 3.12、OpenAI-compatible Providers、Docker Compose、FastAPI、
PostgreSQL/pgvector、Redis、ARQ、React/Vite、in-app Browser。

---

### 任务 1：固定基线与安全读取配置

**读取：** `AGENTS.md`、`docs/PRODUCT_SPEC.md`、`docs/RUNTIME_AGENT_HARNESS.md`、
`app/core/config.py`、Provider、Compose、前端 Client、现有 live test 和 Phase 3 状态文档。

- [x] 记录 branch、status、diff stat 和 diff check。
- [x] 读取实际端口、Host、模型、维度、Cookie/CORS 和健康检查，不输出秘密。
- [x] 记录 `.env` 字段是否配置和代理环境的脱敏摘要。

### 任务 2：代理与 Provider 网络诊断

- [x] 检查大小写代理变量、WinHTTP 与 .NET 默认代理。
- [x] 确认 `NO_PROXY` 是否覆盖 localhost、127.0.0.1 和 ::1。
- [x] 对两个 Provider Host 执行 DNS、TCP 443 和 HTTPS/TLS 基础连接。
- [x] 分别用当前代理和单命令直连路径测试，分类 Permission/Proxy/Network/TLS/HTTP。

### 任务 3：真实 Provider Smoke Test

**复用：** `OpenAICompatibleEmbeddingProvider`、`OpenAICompatibleChatProvider`、
`ModelInterviewAnswer` 和 Phase 3 Prompt。

- [x] 真实 Query Embedding：非空、1024 维、全部有限，不输出向量。
- [x] 真实充分证据 Chat：严格 JSON、第一人称、合法 `evidence_1`。
- [x] 真实不足证据 Chat：`insufficient_evidence`、无引用，并由服务层归一为标准拒答。
- [x] 只记录 Host、模型、维度、耗时和脱敏错误类别。

### 任务 4：Docker daemon 与 Compose

- [x] 逐条执行 docker version/info/context/compose version/config。
- [x] daemon 可用后执行 `docker compose -f docker-compose.yml up -d --build`，不删 Volume。
- [x] 验证 postgres readiness、Redis PING、Backend live/ready、Worker 队列连接和 Frontend HTTP。
- [x] 执行 Alembic upgrade head/current/check。
- [x] 若 Compose 缺少 Frontend 被实证为唯一配置缺口，先报告根因、文件和验证方法，再按 TDD/
  构建验证添加最小前端容器配置。

### 任务 5：浏览器真实验收

- [x] 命令行先确认统一 Host 的 Frontend 和 Backend，且 localhost 绕过代理。
- [ ] 管理员登录并创建/确认两项虚构 Project-only 发布资料。
- [ ] 创建同时授权两个 Project 的 Grant；Access Token 只在内存中使用。
- [ ] Recruiter Exchange 后验证 `/interview` 首屏。
- [ ] 教育问题 answered 且只引背景 Project；Redis 问题 answered 且引 ResumeGraph；QPS/P99
  返回标准 insufficient，三次额度正确。
- [ ] 管理员撤销 Grant 后，旧 Recruiter Session 立即失效且不再扣额度。
- [ ] 检查 Network/控制台及请求载荷不泄露密钥、Token、Cookie、完整 Evidence、Prompt 或历史。

### 任务 6：关闭检查点或记录唯一阻断

- [x] 全部通过时更新五份 Phase 3 文档为 completed；否则保持 external acceptance partially
  blocked，并只列实际剩余阻断项。
- [x] 如有代码修复，运行相关测试和完整回归；无代码修复时至少复跑全部外部 Smoke Test。
- [x] 最终重新记录 Git 四项结果和本次实际修改文件，停止等待用户确认。
