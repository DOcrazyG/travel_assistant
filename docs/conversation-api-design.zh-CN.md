# 会话 API 与身份契约

[English version](conversation-api-design.md)

**状态：** 已批准契约；P2 单 Agent JSON 与 SSE 执行已实现
**最后更新：** 2026-08-10
**适用范围：** 已认证的对话调用、会话所有权与 LangGraph 状态恢复

## 1. 意图与范围

服务提供一个让 LLM 调用者感到熟悉、但会话状态始终由服务端拥有的响应调用接口。它采纳稳定 OpenAI Responses 约定中的 `model`、`input`、`stream` 字段，含 `id`、`object`、`created_at`、`status`、`output`、`usage` 的响应对象，以及 `response.output_text.delta` 有序文本增量事件。

这是**受启发的契约**，不承诺未修改的 OpenAI Python SDK 或每个 OpenAI 请求选项都可用。服务额外提供持久化的 `conversation` 引用。协议 DTO 定义文本、图片、文件和函数调用记录；公开会话请求仅接受一条用户输入，当前单 Agent 运行时只启用文本输入/输出。首期只支持已认证用户，不提供匿名或访客会话。

## 2. 标识符与所有权模型

| 标识符 | 创建者 | 可见性 | 用途 |
| --- | --- | --- | --- |
| `user_id` | 身份层 | 仅请求上下文 | 已认证本地用户 |
| `conversation_id` | 应用 | 返回给调用方 | 一个会话的不可猜测公开标识符 |
| `thread_id` | 应用 | 仅内部 | 该会话稳定的 LangGraph 检查点序列 |
| `run_id` | 应用 | 返回给调用方 | 一次 Agent 图调用 |
| `request_id` | 中间件 | 响应、日志、事件 | 跨服务关联一次 HTTP 请求 |

`conversation_id` 与 `thread_id` 是一对一且不可变的映射。API 只有在所有权检查通过后才把公开 ID 解析为内部 ID；`thread_id` 始终传给 LangGraph 的持久化 PostgreSQL checkpointer，既不是用户身份也不是浏览器登录会话 ID。`conversation_id` 必须是高熵不透明标识符（如 UUIDv7），不得使用自增主键、JWT claim 或客户端自选 ID。

## 3. 认证与凭据

### 用户访问

所有用户请求使用 `Authorization: Bearer <access-token>`。访问令牌是短期 JWT（建议 15 分钟），服务至少校验 `iss`、`aud`、`exp`、`iat`、`sub`、`jti`，再将 `sub` 解析为活跃本地用户。刷新会话必须持久化、可轮换和可撤销；有 HttpOnly Cookie 流程时，刷新令牌不发送给 Agent、不存入会话，也不暴露给浏览器 JavaScript。

首期产品自行实现注册、登录、邮箱验证、密码重置和刷新令牌轮换；密码以 Argon2id 哈希，绝不记录或返回。未来 OIDC 集成可在相同用户契约后替换签发方。

### 机器访问与授权规则

本版本不支持 API Key 集成；唯一支持的凭据是本地用户 JWT 及其轮换刷新令牌。每个携带 `conversation_id` 的请求（含流）都必须遵循：

```text
已认证凭据 → 活跃用户 → 会话 user_id 匹配 → thread 查询 → 执行
```

缺失、无效、过期或被撤销的凭据返回 `401`；用户不拥有该会话时返回 `404`，避免确认资源存在。

## 4. 响应调用契约

### 接口与幂等

```text
POST /api/v1/conversations/{conversation_id}/messages
Authorization: Bearer <access-token>
Idempotency-Key: <客户端生成的不透明键>  # 消息提交必填
Content-Type: application/json
```

`Idempotency-Key` 在单个认证用户的同一方法和路由内，结合请求体指纹唯一。相同 Key 与相同请求体会重放原始结果/运行；相同 Key 但不同请求体返回 `409`。Key 的保留期由幂等存储配置。

### 请求

```json
{
  "model": "travel-assistant",
  "input": {"type":"message","role":"user","content":[{"type":"input_text","text":"请安排上海三日游"}]},
  "stream": false,
  "metadata": {"locale":"zh-CN","timezone":"Asia/Shanghai"}
}
```

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `model` | 是 | 应用模型别名，不一定等于供应商模型名 |
| `input` | 是 | 本轮的一条新用户消息；内容是非空 `input_text`、`input_image` 或 `input_file` 列表。图片/文件有类型定义，但在多模态适配器交付前返回 `input_content_not_supported` |
| `stream` | 否 | 默认 `false`；`true` 返回 `text/event-stream` |
| `metadata` | 否 | locale/timezone 等小型、受校验的上下文；不是授权通道，不得包含密钥或无界个人数据 |

调用方只发送当前轮的新输入，不重传完整历史。服务使用映射的 `thread_id` 载入规范历史和检查点，只追加一次输入，并自行控制系统提示词。未来工具轮次使用 `function_call` 输出项及匹配的 `function_call_output` 输入项；这些是协议记录，工具选择和执行仍由服务端拥有。

### 类型归属、非流式与流式响应

`app.schemas.responses` 是宽泛的 Responses 风格协议类型系统；`app.schemas.conversation_requests` 是该接口的窄请求边界；`app.schemas.messages` 是独立的持久化转录 Schema。此区分防止未来协议能力在没有鉴权、执行和持久化规则时就成为公开能力。

非流式响应的 `id` 是应用 Agent-run ID，每个输出项的 `id` 是持久化助手消息 ID；供应商可提供计量时才填充 `usage`。

流使用 SSE 与 Responses 事件命名；每个 payload 有 `type` 和严格递增的 `sequence_number`，项/内容事件还带稳定的助手 `item_id`：

| SSE 事件 | 含义 |
| --- | --- |
| `response.created` / `response.in_progress` | 响应包络与活动生命周期 |
| `response.output_item.added` | 持久化中的助手消息项 |
| `response.content_part.added` | 为消息创建空 `output_text` 部分 |
| `response.output_text.delta` | 渐进渲染文本 |
| `response.output_text.done`、`response.content_part.done`、`response.output_item.done` | 完结嵌套内容和输出项 |
| `response.completed` | 含完整输出的最终响应 |
| `response.failed` | 最终失败响应 |
| `error` | 安全的 Problem Details 风格错误 |

浏览器客户端应使用基于 `fetch` 的流读取器以发送 Bearer 头；原生 `EventSource` 没有合适的标准方式设置此头。

## 5. 会话管理接口

| 方法 | 路径 | 含义 |
| --- | --- | --- |
| `POST` | `/api/v1/conversations` | 显式创建空会话 |
| `GET` | `/api/v1/conversations` | 仅列出已认证用户自己的会话 |
| `GET` | `/api/v1/conversations/{conversation_id}` | 通过所有权验证后返回会话与分页消息 |
| `DELETE` | `/api/v1/conversations/{conversation_id}` | 立即不可访问，并安排符合留存策略的消息/检查点清理 |

聊天接口和资源接口调用同一会话服务，不得各自实现不同的历史、鉴权或持久化规则。

## 6. 并发、重试与生命周期

一个 `conversation_id` 最多允许一个活跃 Agent 运行。运行期间第二个非幂等消息返回包含 `conversation_busy` 和活动 `run_id` 的 `409`；客户端应等待流完成后用新幂等键重试，避免两次运行从相同检查点读写出分叉状态。

运行状态为 `queued`、`running`、`completed`、`failed`、`cancelled`。重试 HTTP 请求不等于发起第二次运行。所有可观测写入（消息、运行、工具审计、图持久化边界）均须按幂等设计；首期旅行建议禁止外部副作用。

## 7. 留存与删除

服务最小化个人数据存储。会话消息、检查点、运行/工具审计和已确认偏好各有留存类别；删除会话必须按类别包含映射检查点和派生摘要。API 删除会立即令会话不可用，后台清理移除符合条件的数据并保留最小删除审计；备份按独立且有界的周期管理。

默认留存：会话、消息、检查点、运行/工具审计在最后活动后 180 天；安全审计 365 天；幂等记录 24 小时；备份 35 天。显式删除立即生效，并在 30 天内物理清除（受备份生命周期约束）。首期不持久化身份证件、联系方式或精确位置。

## 8. 错误与可观测契约

非流式错误及 SSE `error` 使用安全的 Problem Details 风格 payload，例如：

```json
{"code":"conversation_busy","message":"A response is already being generated for this conversation.","request_id":"req_01J...","details":{"run_id":"run_01J..."}}
```

API 永不返回供应商凭据、原始堆栈、未脱敏工具输入或私有标识符。日志与 trace 关联 `request_id`、脱敏 `user_id`、`conversation_id`、`thread_id` 和 `run_id`。

## 9. 已记录决策

- 仅已认证用户；无访客/匿名会话。
- 使用短期 JWT、轮换刷新会话和撤销状态。
- 自建 Argon2id 密码认证，未来可兼容 OIDC。
- 会话在消息提交前显式创建。
- 采用 Responses 风格请求、响应与流事件，但不承诺 SDK 即插即用兼容。
- 每会话一个活跃运行，提交受幂等保护。
- 留存期：会话/检查点/运行 180 天、安全审计 365 天、幂等记录 24 小时、备份 35 天；显式删除立即不可用并在 30 天内清除。
