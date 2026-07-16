# Phase 4.5 学习笔记 — 如何安全地做 Public Demo

## 为什么 Public Demo 不是新的权限系统

公开首页只是让访问者免于手工输入一次性 Access Token。它不能因此获得新的授权规则。
正确做法是把“选择哪个现有 Grant”存成服务器端配置，然后调用同一个
`AccessGrantService` 创建 Recruiter Session。

如果 Public Demo 自己判断有效期、撤销和额度，两个入口迟早会产生不同规则；如果前端拿到
Grant ID 或 Token 再拼接 URL，则授权元数据会泄漏，并把安全决定推给不可信客户端。

## 为什么需要单例表

配置不是业务记录列表，而是整个站点当前的公开入口开关。固定 `id = 1` 比“查询第一条 Enabled
记录”更明确：数据库本身拒绝第二条配置，代码不需要猜测哪条生效。

外键保证所选 Grant 确实存在。Migration 不自动选择 Grant，因为不同开发环境的数据不同，
自动绑定“第一条”会形成隐蔽且危险的权限扩大。

## 为什么 Session 创建不扣额度

创建 Session 只证明当前 Grant 可以开始访问；真正的成本和知识访问发生在 Interview 请求。
如果打开页面就扣额度，刷新或重复打开会无意义消耗配额。Phase 4 的原子额度扣减位置保持不变，
因此 Public Demo 与手工 Access Token 入口拥有相同计费语义。

## 为什么 `min-h-0` 能修复聊天滚动

Flex 子元素默认可能拒绝缩小到内容高度以下。即使 Message Area 写了 `overflow-y-auto`，它仍可能
把父容器撑高，导致页面底部超出视口、输入框覆盖消息。完整链路需要同时满足：

1. 页面高度固定为 `100vh/100dvh` 并隐藏外层溢出；
2. 中间 Flex 容器和 ChatWindow 设置 `min-h-0`；
3. Message Area 使用 `flex-1` 与 `overflow-y-auto`；
4. Header 和 Composer 使用 `shrink-0`。

这样浏览器才会把剩余高度分配给消息区，并让滚动发生在正确元素上。

## 如何验证

后端测试分别覆盖配置状态、Grant 状态、Session Cookie 和公开响应最小化。前端测试连续发送
11 轮消息，确认消息区域存在独立 `overflow-y-auto`、Composer 不收缩且自动滚动被调用。
这比只截图两轮聊天更容易捕获原始高度错误。
