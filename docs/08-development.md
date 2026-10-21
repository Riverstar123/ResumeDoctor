# 开发环境与集成约定

SET-01 已提供后端最小入口、DTO 和验证命令；前端已有 HTTP 模式入口。INT-01 已消费两个独立 JD fixture，装配边界见 [集成记录](team/int-01.md)。DB-01 提供 PostgreSQL 迁移、repository 和独立数据库 API 入口，命令与实测证据见 [DB-01](team/db-01.md)。独立 worker、租约与恢复仍由 JOB-01 交付。

## 环境

前端 React/TypeScript/Vite，npm 管理并提交 package-lock.json；后端 Python/FastAPI，使用 uv 管理并提交 uv.lock；数据库 PostgreSQL；SQLAlchemy 与 Alembic；单元测试 pytest/Vitest，浏览器端到端 Playwright。
SET-01 固定 Node 22.22.0、Python 3.12.13、PostgreSQL 17.11；来源与兼容说明见 [交付记录](team/set-01.md#版本与兼容依据)。团队使用相同版本；依赖更新由负责对应工程的成员提交 PR。

## 必须提供的入口

| 入口 | 负责人 | 验收 |
|---|---|---|
| 前端 dev/build/test | B | 干净克隆可启动、构建和验证 |
| 后端 dev/test | A | fake 模式不需要付费 API key |
| worker 启动 | A | 与 API 共用配置，处理数据库 queued task |
| 数据库迁移 | A | 空库一次迁移完成，不手工建表 |
| 合成数据导入 | 各模块、A 汇总 | 只含合成数据，可重置 |
| 契约与端到端检查 | A/B/E | README 写实际命令与结果 |

## 配置

DATABASE_URL、SESSION_SECRET、LLM_PROVIDER、LLM_MODEL、LLM_API_KEY、LLM_BASE_URL、LLM_MODE=fake/real、UPLOAD_DIR、ALLOWED_ORIGINS、SESSION_TTL_DAYS=7。
服务端配置放 `backend/.env`，模板为 `backend/.env.example`。模型目录和双模型映射见 [模型配置](10-model-configuration.md)。前端仅持有公开 API_BASE_URL；密钥不得进入前端、日志或 Git。

## 联调与运行

前端开发服务器代理 `/api` 到本地后端，使用同源 cookie。跨域调试固定允许 origin 和 credentials，不使用通配 origin。
A 提供统一容器配置和原生启动说明，部署入口包含数据库/API/worker/前端。P1 可以在本地用 fake/test double 独立验证；P2 集成必须使用 PostgreSQL 与 worker。
DB-01 使用 `uv sync --project backend --locked --extra database` 安装锁定的数据库依赖，`make migrate` 显式升级，`make dev-database` 启动持久化 API。数据库入口不会自动建表或启动内存任务执行器，202 后任务保持 queued，等待 JOB-01；`make dev` 仍是原合成链路。API lifespan 每分钟执行会话与文件清理，瞬时失败保留下一轮重试；API 停止时可由运行环境周期执行 `make cleanup-db`。`make test-db` 必须显式提供已迁移、名称含 test 的专用临时 PostgreSQL 的 RD_TEST_DATABASE_URL；缺少配置会失败，不将跳过验收误报通过。

数据库装配将完整同步业务/事务交给 AnyIO worker，独立使用 `CapacityLimiter(8)` 控制数据库 I/O 并发，不占 Starlette 默认线程预算；鉴权、请求清理、周期清理和关闭连接也使用相同入口。`/healthz` 只检查进程存活，保持异步，不等待数据库连接或锁。默认 fake 装配仍在事件循环内运行其内存执行器。真实 HTTP 锁等待、默认连接池 15 路上传及幂等/清理回归位于 `test_postgres_concurrency.py`，随 `make test-db` 执行；这不包含 #15 的 worker 恢复验收。
交付范围是本地可复现课程演示。公网生产部署不在本轮任务中；需要新增发布需求后再实施。

## 官方参考

- [FastAPI](https://fastapi.tiangolo.com/features/)：OpenAPI 与类型契约。
- [Claude Code memory](https://code.claude.com/docs/en/memory)：项目 CLAUDE.md。
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)：短分支与 PR 协作。
