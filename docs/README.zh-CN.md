# Travel Assistant

[English documentation](../README.md)

Travel Assistant 是一个用于构建认证式、可持久化旅行助手对话体验的 FastAPI 后端。它提供本地账户认证、PostgreSQL 持久化会话与幂等保障、带 LangGraph 检查点的单 Agent 运行时，以及 JSON 与 Server-Sent Events（SSE）两种响应方式。

## 已实现能力

- 邮箱密码注册、短期 JWT 访问令牌，以及轮换的 HttpOnly 刷新令牌 Cookie。
- 按用户隔离的会话创建、列表、历史记录读取和软删除。
- 基于 OpenAI 兼容模型服务的纯文本 Agent 对话，以及可持久化的历史上下文。
- 每轮 Agent 调用均支持 JSON 响应或有序 SSE 流式响应。
- 由 Alembic 管理的 PostgreSQL 应用表迁移，以及 LangGraph 检查点表初始化。
- PostgreSQL 就绪检查；以 Valkey 为主的速率限制，以及仅限开发/测试环境的内存回退。
- 结构化日志、请求 ID、统一错误响应格式和自动化质量检查。

当前 Agent 只接受文本输入。协议类型已预留图片、文件和函数工具的表示方式，方便后续扩展；但线上会话接口会明确拒绝这些尚未启用的输入。

## 运行要求

- Python 3.12 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Docker 与 Docker Compose（用于项目附带的本地 PostgreSQL 和 Valkey 服务）
- 用于发送 Agent 消息的 OpenAI 兼容 API Key、服务地址和模型名称

## 快速开始

1. 创建本地配置，并填写必要的开发环境参数。至少应替换 `VALKEY_PASSWORD`；在使用会话消息接口前，还必须配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 与 `DEFAULT_LLM_MODEL`。

   ```bash
   cp .env.example .env
   ```

2. 安装 Python 依赖并启动本地基础服务。

   ```bash
   uv sync --all-groups
   docker compose up -d postgres valkey
   ```

3. 启动 API。

   ```bash
   sh start_fastapi.sh
   ```

   该脚本会先执行 Alembic 迁移、创建 LangGraph 检查点表，再通过 `python -m app.main` 启动服务。默认情况下，`APP_DEBUG=true` 会启用 Uvicorn 自动重载，API 监听在 `http://127.0.0.1:8000`。

4. 检查服务是否已启动。

   ```bash
   curl http://127.0.0.1:8000/health/live
   curl http://127.0.0.1:8000/health/ready
   ```

   可在 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) 查看交互式 OpenAPI 文档。

### 端口已被占用

服务从 `.env` 读取 `HOST` 和 `PORT`，默认是 `127.0.0.1:8000`。如果启动时出现 `ERROR: [Errno 98] Address already in use`，表示已有服务在监听此地址。请停止旧实例，或将 `.env` 中的 `PORT` 改为未占用的端口（例如 `PORT=8001`）后重新启动。Linux 下可用以下命令查看监听者：

```bash
ss -ltnp '( sport = :8000 )'
```

## 配置说明

`.env.example` 列出了所有配置项。请勿提交复制生成的 `.env` 文件或任何密钥。最重要的配置分组如下：

| 用途 | 配置项 |
| --- | --- |
| HTTP 服务 | `HOST`、`PORT`、`APP_DEBUG`、`LOG_LEVEL`、`LOG_FORMAT` |
| PostgreSQL | `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DATABASE`、`POSTGRES_USER`、`POSTGRES_PASSWORD` |
| Valkey / 限流 | `REDIS_URL`、`VALKEY_USERNAME`、`VALKEY_PASSWORD`、`ALLOW_IN_MEMORY_RATE_LIMIT` |
| 认证 | `JWT_SECRET_KEY`、`JWT_ISSUER`、`JWT_AUDIENCE`、`ACCESS_TOKEN_MINUTES`、`REFRESH_SESSION_DAYS`、`CORS_ALLOWED_ORIGINS` |
| 初始管理员 | `BOOTSTRAP_ADMIN_EMAIL`、`BOOTSTRAP_ADMIN_PASSWORD` |
| 模型服务 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`DEFAULT_LLM_MODEL`、`FALLBACK_LLM_MODEL` |

服务启动时如发现 `POSTGRES_DATABASE` 不存在，会尝试创建它，因此数据库用户需要拥有创建该数据库的权限。仅当系统不存在未删除的管理员账户时，才会按 `BOOTSTRAP_ADMIN_EMAIL` 和 `BOOTSTRAP_ADMIN_PASSWORD` 创建初始管理员；后续启动不会重置其密码。

在预发布和生产环境中，请使用强且唯一的 `JWT_SECRET_KEY` 与 `PII_HASH_KEY`，配置 `CORS_ALLOWED_ORIGINS`，启用安全刷新 Cookie，并使用带凭据、网络可达的 Valkey。应用会拒绝不安全的生产配置。项目内置的 Compose 文件会发布数据库端口；若不适合暴露端口，请通过主机防火墙限制访问或调整端口绑定。

## API 概览

所有受保护接口均需传递 `Authorization: Bearer <access_token>`。接口错误会使用统一结构，包含 `code`、`message` 和 `request_id`；参数校验错误还会附带安全的字段详情。

| 接口 | 说明 |
| --- | --- |
| `GET /health/live` | 存活探针 |
| `GET /health/ready` | 数据库初始化完成后的就绪探针 |
| `POST /api/v1/auth/register` | 创建本地账户 |
| `POST /api/v1/auth/login` | 返回访问令牌并写入刷新令牌 Cookie |
| `POST /api/v1/auth/refresh` | 轮换刷新 Cookie 并签发新的访问令牌 |
| `POST /api/v1/auth/logout` | 吊销当前会话/令牌并清除 Cookie |
| `GET /api/v1/auth/me` | 获取当前账户 |
| `POST /api/v1/conversations` | 创建空会话 |
| `GET /api/v1/conversations` | 获取当前用户的会话列表 |
| `GET /api/v1/conversations/{id}` | 获取会话和第一页消息 |
| `GET /api/v1/conversations/{id}/messages` | 分页获取消息历史 |
| `POST /api/v1/conversations/{id}/messages` | 提交一轮 Agent 消息，可选 JSON 或 SSE |
| `DELETE /api/v1/conversations/{id}` | 软删除会话 |

会话和消息列表接口支持 `offset`、`limit` 分页参数。`limit` 取值范围为 1–100；会话列表默认值为 20，消息历史默认值为 50。

### 基本调用流程

先注册、登录，再创建会话。以下示例借助 `jq` 提取 JSON 字段，也可以改用其他 JSON 工具。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"traveler@example.com","password":"a-long-local-password"}'

TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"traveler@example.com","password":"a-long-local-password"}' \
  | jq -r '.access_token')

CONVERSATION_ID=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"日本行程"}' \
  | jq -r '.id')
```

提交非流式文本消息。`Idempotency-Key` 为必填项；只有在安全重试同一个请求时才应重复使用同一 Key。

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: 8e8b8b6f-1a79-4d59-88b8-unique-request-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "input": {
      "role": "user",
      "content": [{"type": "input_text", "text": "请规划五天东京行程。"}]
    }
  }'
```

若需流式响应，请在请求体中添加 `"stream": true` 并请求事件流。服务会按顺序发出 `response.created`、`response.output_text.delta`、`response.completed` 等事件；失败时会发出 `response.failed` 和 `error`。

```bash
curl -N -X POST "http://127.0.0.1:8000/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: a-different-unique-request-key' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{
    "stream": true,
    "input": {
      "role": "user",
      "content": [{"type": "input_text", "text": "我应该优先预订什么？"}]
    }
  }'
```

完整的请求/响应契约请参阅[会话 API 与身份契约](conversation-api-design.md)；运行中的 `/docs` 是 API Schema 的最终依据。

## 数据与运行时行为

应用表由 Alembic 管理。LangGraph 的 PostgreSQL 检查点表归 LangGraph 依赖管理，需单独初始化；本地执行 `start_fastapi.sh`、`make migrate` 或 `make run` 时都会完成这两项准备工作。

每一轮会话都会按已认证用户隔离。服务会在 PostgreSQL 中保存消息、Agent 运行状态、幂等记录和图检查点历史。单 Agent 运行时通过 OpenAI 兼容端点调用主模型；当主模型调用失败且配置了 `FALLBACK_LLM_MODEL` 时，会在同一端点上尝试备用模型。

## 开发命令

```bash
make install              # 使用 uv 安装所有依赖组
make up                   # 启动本地 PostgreSQL 和 Valkey
make down                 # 停止本地基础服务
make run                  # 迁移、初始化检查点并以自动重载模式运行
make migrate              # 执行 Alembic 迁移并初始化检查点
make setup-checkpoints    # 初始化 LangGraph 检查点表
make revision message='describe change'  # 生成待审核的 Alembic 迁移
make format               # 使用 Ruff 格式化源码
make lint                 # 运行 Ruff 检查
make typecheck            # 运行 Pyright
make test                 # 运行测试
make check                # 依次运行 lint、类型检查和测试
make pre-commit-install   # 安装本地 Git 钩子
make smoke-admin          # 以初始管理员身份登录并进行交互式对话
```

运行 `make smoke-admin` 前，请先启动 API 并在 `.env` 中设置 `BOOTSTRAP_ADMIN_EMAIL` 和 `BOOTSTRAP_ADMIN_PASSWORD`。该工具会创建一个会话，然后持续渲染流式 token，直到输入 `/exit` 或按下 Ctrl-D。若 API 地址不是默认值，请执行：

```bash
uv run python scripts/admin_conversation_smoke.py --base-url http://host:port
```

集成测试需要 PostgreSQL，并且需要显式开启：

```bash
RUN_POSTGRES_INTEGRATION=1 uv run pytest tests/integration
```

## 延伸文档

- [后端架构设计](architecture-design.zh-CN.md)
- [会话 API 与身份契约](conversation-api-design.zh-CN.md)
- [数据库设计](database-design.zh-CN.md)
- [数据库迁移指南](database-migrations.zh-CN.md)
- [迭代计划](todo-plan.zh-CN.md)
