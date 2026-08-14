# 数据库迁移指南

[English version](database-migrations.md)

**状态：** 已实现

本项目使用 Alembic 对应用拥有的 PostgreSQL 表进行版本管理。当前基线 revision 是 `373c9d3f1e26`（`create application schema`），创建 `app` schema、当前 21 张表、索引、约束、JSONB 默认值和 UTC `timestamptz` 列。

revision `6a1e7f19c482` 将幂等键直接归属到已认证用户：它只清除未使用的预发布幂等记录，再添加非空所有权列和新的唯一键。其 downgrade 有意失败，因为不同用户复用同一不透明键后，恢复全局唯一性会丢失有效记录。

## 范围与归属

| 边界 | 版本管理方 | 说明 |
| --- | --- | --- |
| `app` schema | 本仓库 Alembic revisions | 身份、会话、消息、附件、运行、审计和偏好 |
| `public.alembic_version` | Alembic | 保存已应用的应用 revision |
| `langgraph` schema | LangGraph/PostgresSaver 初始化 | 依赖拥有的检查点状态；不加入应用 metadata 或 Alembic revision |
| MinIO bucket 与生命周期 | 基础设施配置 | 对象字节及 bucket 配置不是 PostgreSQL 迁移 |

Alembic 在读取 `SQLModel.metadata` 前导入 `app.models`，因此每个应用模型必须从 `app/models/__init__.py` 导出。迁移复用服务的类型化 PostgreSQL 配置，无需维护第二个数据库 URL。

## 日常命令

```bash
# 将所有应用迁移应用到当前配置的数据库。
make migrate

# 修改 SQLModel metadata 后生成候选迁移。
make revision message="add conversation summary"

# 查看当前 revision 并比较 metadata 与数据库。
uv run alembic current
uv run alembic check

# 查看 head 与历史。
uv run alembic heads
uv run alembic history
```

`make run` 和 `./start_fastapi.sh` 会在本地开发时自动执行 `alembic upgrade head`。它们适合单个本地进程，不是生产部署机制。

## 创建迁移

1. 修改 `app/models/` 中适当的 SQLModel 模块，确保模型仍由 `app.models` 导入。
2. 为表、约束、索引或类型补充/更新 metadata 测试。
3. 执行 `make revision message="简短的祈使式描述"`。
4. 提交前审核 `alembic/versions/` 下生成的 revision。
5. 分别在空数据库和可升级的数据库副本上应用它。
6. 执行 `uv run alembic check`、`make check` 与相关集成测试。

自动生成只是草稿，不是批准。逐项审核外键、检查约束、部分索引、server default、可空性变更和破坏性语句。Schema 创建/删除也必须显式编写，因为 SQLModel metadata 不能自动推断。

## 审核清单

- 确认 revision 恰有一个父节点，且仓库只有一个 head。
- 保持账户所有权：用户资源使用直接 `user_id` 外键；未经组织设计批准不得引入 tenant/principal 列。
- 持久时间使用 `timestamptz`，应用时间戳使用 UTC。
- PostgreSQL JSON 默认值使用 SQL 表达式，例如 `text("'{}'::jsonb")`，而不是带引号的 Python 字符串。
- 仅为真实的鉴权、历史、留存或 worker 查询建立索引，不添加投机索引。
- 数据迁移须可恢复、有边界；大表采用 expand/backfill/contract，不进行长时间阻塞变更。
- 在 revision 或发布说明中陈述回滚行为；数据已转换/删除后 downgrade 不会天然安全。

## 部署顺序

每次发布在启动或替换 API 副本前只执行一次迁移：

```text
备份 / 验证可恢复 → 部署迁移制品 → alembic upgrade head
→ alembic current + 健康检查 → 启动或滚动 API 副本
```

只允许一个部署 worker 运行 Alembic。API 副本不能在启动时争抢升级 Schema。迁移失败应停止发布、诊断 revision，并从备份恢复或执行经过审核的回滚；不要手改 `alembic_version` 表。

## 本地恢复

对不重要的本地开发数据库，可重建数据库后运行 `make migrate`。若需检查回滚路径但不改历史，使用隔离数据库执行 `uv run alembic downgrade <revision>`，再执行 `uv run alembic upgrade head`。

不要将 downgrade 作为常规生产恢复方案。生产数据迁移、留存清理及已被部署代码消费的变更可能不可逆；当回滚会丢失数据时，从经过测试的备份恢复或交付前向修复。
