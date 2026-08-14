# Travel Assistant 数据库设计

[English version](database-design.md)

**状态：** 多账户 SQLModel 定义与可重建的初始 Alembic 基线
**最后更新：** 2026-08-11
**数据库：** PostgreSQL 16；MinIO 保存附件字节；LangGraph 拥有自己的检查点表

## 范围

这是一个本地认证的多账户问答应用。不包含组织、工作区、角色、服务主体、API Key 或跨用户共享。`app` schema 由应用拥有；LangGraph 检查点表由依赖自身在独立 `langgraph` schema 中管理。

所有 ID 使用应用生成的 UUIDv7，所有时间戳使用 UTC `timestamptz`。外键使用 PostgreSQL 默认 `RESTRICT` 行为，因此清理 worker 必须按安全顺序显式移除依赖行。

## 核心不变量

- 每个用户拥有的资源都有直接 `user_id → users.id` 外键；无 tenant ID、principal、membership 或组合租户键。
- 会话具有公开 `id` 与不可变、全局唯一的 LangGraph `thread_id`；所有请求都按 `user_id` 鉴权。
- 消息序号在会话内为正且唯一；插入消息、递增 `latest_message_sequence` 与更新 `last_message_at` 必须在一个事务内完成。
- 单个会话最多有一个 `queued`、`running` 或 `interrupted` Agent 运行。
- 软删除是显式的：会话/用户的 `deleted` 状态必须与 `deleted_at` 一致；附件必须与 `upload_status = 'deleted'` 一致。

## 数据表

### 身份与认证

`users` 是唯一账户表：UUIDv7 `id`、`email`/小写 `email_normalized`、Argon2id `password_hash`、状态（`pending_verification`、`active`、`disabled`、`deleted`）、`is_admin` 初始管理员标记、认证生命周期时间戳及常规创建/更新/删除时间。约束保证小写与删除状态规则；部分唯一索引保证每个规范化邮箱只有一个未删除账户，以及只有一个未删除管理员。

- `auth_sessions`：可撤销的刷新令牌族，包含直接 `user_id`、唯一 `token_family_id`、过期/撤销时间和有界设备元数据；索引为未撤销 `(user_id, expires_at)` 和 `expires_at`。
- `refresh_tokens`：每次轮换保存一个哈希，含会话、签发/过期/消费/撤销时间与 `replaced_by_id`；索引按会话签发时间和过期时间。
- `revoked_access_tokens`：JWT `jti`、`user_id`、过期、撤销时间和原因，按过期时间支持清理。
- `auth_one_time_tokens`：邮箱验证或密码重置令牌的哈希、过期/消费时间、请求 IP 哈希和 UA；索引支持用户用途查询与过期清理。

### 会话与消息

`conversations` 包含 `id`、直接 `user_id`、唯一 `thread_id`、标题及来源（`system`、`user` 或空）、状态（`active`、`archived`、`deleted`）、JSONB `metadata`、消息排序字段、乐观锁 `version` 与归档/删除/清理时间。

- 未删除 `(user_id, last_message_at DESC, id DESC)` 支持历史列表和游标分页。
- 未删除 `(status, last_message_at DESC)` 支持日常清理。
- 在已删除记录上的 `purge_after_at` 服务清理 worker。

`messages` 是规范有序转录：`id`、`conversation_id`、正 `sequence`、角色（`user`、`assistant`、`system`、`tool`）、JSONB 内容数组、渲染投影、内容状态、可选 `agent_run_id`、模型来源、token 数与生命周期时间。`UNIQUE (conversation_id, sequence)` 防止重复序号；主查询索引为未删除 `(conversation_id, sequence)`。

`message_citations` 保存答案的已净化来源：消息、非负位置、供应商/来源元数据、URL、有界摘录和获取/发布时间；`(message_id, position)` 唯一。

### Agent 执行

`agent_runs` 表示一次接受的图调用，保存会话、运行状态、请求/解析模型标识、有界请求元数据、trace ID、用量/成本、耗时、脱敏错误、interrupt payload 和创建/更新时间；活跃状态有会话部分唯一索引，并另设历史、监控和终态留存索引。

`tool_calls` 是脱敏的子审计记录，保存 Agent 运行、每运行正序号、工具/供应商 ID、状态、脱敏输入输出摘要、来源 URL、时序、时长与安全错误字段。`(agent_run_id, sequence)` 唯一。

`idempotency_keys` 使变更重试安全：直接 `user_id`、方法、路由、不透明键、请求体指纹、可选产生的会话/运行 ID、状态、响应快照和过期时间。其唯一范围为 `(user_id, http_method, route, idempotency_key)`，一个账户不能阻塞或重放另一账户的请求。

### 附件与偏好

`attachments` 仅保存 MinIO 元数据：直接 `user_id`、不可变对象位置、净化文件名/MIME、大小/哈希、类型、上传/扫描/处理状态及生命周期时间。对象位置唯一；约束和 worker 索引保护正常流程。`message_attachments` 以唯一 `attachment_id` 使附件单次使用，复合主键为 `(message_id, attachment_id)`，并保证每条消息位置唯一。

`travel_preferences` 保存用户管理且已确认的长期值：`id`、直接 `user_id`、类别、JSONB 值、可选来源消息、状态、确认/过期时间与软删除时间。用户每个类别最多存在一条已确认、未删除值。

### 审计与删除

`security_audit_events` 是追加式记录，含 ID、可选 `user_id`、事件类型/结果、请求/设备元数据、脱敏 JSONB 详情和发生时间；按用户、事件、request ID 和时间索引。

`data_deletion_requests` 是可重试的持久化清理队列：请求用户、目标类型（`conversation`、`user`、`attachment`）、目标 ID、原因、状态、计划/执行时间和有界失败详情。显式删除会话会立即写入删除时间，并安排 30 天后物理清理；留存策略可在 180 天无活动后安排清理。

## 留存与迁移策略

业务记录先通过软删除隐藏。Worker 随后取消活跃运行、删除 MinIO 对象、移除引用/附件/工具/消息/运行子项、通过受支持生命周期删除 LangGraph 检查点、删除会话并完成删除请求。失败可重试且可审计。

初始迁移有意重建整个 `app` schema，其 downgrade 使用破坏性的 `DROP SCHEMA ... CASCADE`。模型后续变化必须创建经过审核的新 Alembic revision；基线部署后不得编辑。
