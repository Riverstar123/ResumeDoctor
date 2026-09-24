# 开发环境与集成约定

工程及实际命令由 SET-01、WEB-01 交付；未实现的启动入口不得描述为可运行。

## 环境

前端 React/TypeScript/Vite，npm 管理并提交 package-lock.json；后端 Python/FastAPI，使用 uv 管理并提交 uv.lock；数据库 PostgreSQL；SQLAlchemy 与 Alembic；单元测试 pytest/Vitest，浏览器端到端 Playwright。
SET-01 锁定 Node/Python/PostgreSQL 版本并在 README 记录。团队使用相同版本；依赖更新由负责对应工程的成员提交 PR。

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
交付范围是本地可复现课程演示。公网生产部署不在本轮任务中；需要新增发布需求后再实施。

## 官方参考

- [FastAPI](https://fastapi.tiangolo.com/features/)：OpenAPI 与类型契约。
- [Claude Code memory](https://code.claude.com/docs/en/memory)：项目 CLAUDE.md。
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)：短分支与 PR 协作。
