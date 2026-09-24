# 后续开发环境与集成约定

**当前没有应用，不运行下列计划命令。** P1 的第一项任务是把实际可执行的命令写进根 README，并锁定依赖。

## 环境提案

前端 React/TypeScript/Vite，npm 管理并提交 package-lock.json；后端 Python/FastAPI，依赖管理方式由 A 在 P1 锁定，不能混用多个工具；数据库 PostgreSQL；SQLAlchemy 模型与 Alembic 迁移；pytest 与前端 Vitest，端到端工具由 B/E 统一。
Node/Python/PostgreSQL 具体版本在 P1 检查团队电脑与部署环境后锁定，所有人使用相同版本。不要简单依赖 latest。

## 将来必须提供的入口

| 入口 | 责任人 | 验收 |
|---|---|---|
| 前端 dev/build/test | B | 干净克隆可按 README 启动 |
| 后端 dev/test | A | 假模型模式无需付费 API key |
| worker 启动 | A | 与 API 共用配置，处理数据库 queued task |
| 数据库初始化/迁移 | A | 空库一次迁移完成，不手工建表 |
| 假数据导入 | 各模块、A 汇总 | 只含合成数据，可重置 |
| 契约与端到端检查 | A/B/E | README 写实际命令和预期输出 |

## 配置设计

DATABASE_URL、SESSION_SECRET、LLM_PROVIDER、LLM_MODEL、LLM_API_KEY、LLM_BASE_URL（如需要）、LLM_MODE=fake/real、UPLOAD_DIR、ALLOWED_ORIGINS、SESSION_TTL_DAYS=7。环境变量只在服务端，前端仅持有公开 API_BASE_URL。
实现时提供 `.env.example` 的空值模板，不提交真实 `.env`。配置中的密钥不进入页面、日志、PR 或截图。

## 开发连接

建议前端开发服务器代理 `/api` 到本地后端，同源 cookie；生产由单一入口提供页面和 `/api`，HTTPS。跨域调试必须固定允许 origin 和 credentials，不能通配 origin。
数据库和 worker 可使用统一容器配置，但需要在 P1 确认每个人的 Docker 可用性；没有容器能力时由 A 写原生替代步骤。

## 部署边界

P3 先保证本地可演示；公网部署需要完善模型告知、限流、HTTPS、cookie 安全、清理任务和运维配置。不会因为文档存在就视为已经部署或已经合规审计。

## 资料来源

- [FastAPI 官方特性](https://fastapi.tiangolo.com/features/)：OpenAPI 与类型声明适合契约协作。
- [Claude Code memory](https://code.claude.com/docs/en/memory)：项目 CLAUDE.md 用于共享上下文，不能替代 Issue 中的具体任务。
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)：短分支与 PR 的协作基础。
