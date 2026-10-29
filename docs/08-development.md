# 开发环境与集成约定

SET-01 已提供后端最小入口、DTO 和验证命令；前端已有 HTTP 模式入口。INT-01 已消费两个独立 JD fixture，装配边界见 [集成记录](team/int-01.md)。DB-01 提供 PostgreSQL 迁移、repository 和独立数据库 API 入口，命令与实测证据见 [DB-01](team/db-01.md)；独立 worker、租约和恢复见 [JOB-01](team/job-01.md)。

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
DB-01 使用 `uv sync --project backend --locked --extra database` 安装锁定的数据库依赖，`make migrate` 显式升级，`make dev-database` 启动持久化 API，另一终端 `make worker` 执行入库任务。数据库入口不会自动建表或启动内存任务执行器；`make dev` 现为相同持久化入口，原合成链路改名 `make dev-synthetic`。API lifespan 每分钟执行会话与文件清理，worker 也执行清理，瞬时失败保留下一轮重试；均停止时可周期执行 `make cleanup-db`。`make test-db` 必须显式提供已迁移、名称含 test 的专用临时 PostgreSQL 的 RD_TEST_DATABASE_URL；缺少配置会失败，不将跳过验收误报通过。

数据库装配将完整同步业务/事务交给 AnyIO worker，独立使用 `CapacityLimiter(8)` 控制数据库 I/O 并发，不占 Starlette 默认线程预算；鉴权、请求清理、周期清理和关闭连接也使用相同入口。`/healthz` 只检查进程存活，保持异步，不等待数据库连接或锁。默认 fake 装配仍在事件循环内运行其内存执行器。真实 HTTP 锁等待、默认连接池 15 路上传及幂等/清理回归位于 `test_postgres_concurrency.py`，随 `make test-db` 执行；这不包含 #15 的 worker 恢复验收。

JOB-01 进程与 API 共用 DATABASE_URL、UPLOAD_DIR 和 E 的 fake 模型目录。`python -m app.platform.jobs --once` 只领取至多一个任务；持续运行用 `make worker`，Ctrl-C/SIGTERM 取消当前编排并保留租约等待接管，不写公开 cancelled 状态。真实 PostgreSQL 的进程崩溃接管与旧 token 拒写在 `test_jobs.py`，也由 `make test-db` 运行；当前默认装配已由 INT-02 接入真实业务模块，模型仍为 fake；真实供应商验收属于 AI-03。停止与故障限制见 [JOB-01 说明](team/job-01.md)。
交付范围是本地可复现课程演示。公网生产部署不在本轮任务中；需要新增发布需求后再实施。

## 官方参考

- [FastAPI](https://fastapi.tiangolo.com/features/)：OpenAPI 与类型契约。
- [Claude Code memory](https://code.claude.com/docs/en/memory)：项目 CLAUDE.md。
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)：短分支与 PR 协作。

INT-02 的统一装配、登记素材与网页实测见 [联调记录](team/int-02.md)。前端请使用目录内固定的 Node 24.14.1（根工具链的 Node 22 用于历史 SET-01），运行 `npm run dev:api` 并填写公开的 `VITE_PROCESSING_NOTICE`。API 与 worker 使用相同源码版本、backend/.env、DATABASE_URL 与绝对 UPLOAD_DIR。

QA-03 的假模型端到端入口在 `frontend/` 执行 `npm run test:e2e:qa03`：Playwright 配置 `playwright.qa03.config.ts` 自动启动四个 `tests.e2e.serve --variant …` 后端（端口 8010–8013，INT-01 合成装配，fake 模型与服务端确定性故障注入）和四个 http 模式 Vite 实例（5180–5183，经 `API_PROXY_TARGET` 同源代理），不需要 Docker、PostgreSQL 或任何供应商凭证；失败截图与 trace 写入 `frontend/test-results/qa03/`。手工启动单个变体可用 `backend/.venv/Scripts/python -m tests.e2e.serve --variant success --port 8010 --origin http://127.0.0.1:5180`（变体：success/partial/fail/slow，开关只来自服务端环境变量）。该套件只覆盖 INT-01 适配层与 HTTP/UI 契约，不覆盖真实文件解析和数据库 worker。

QA-03 正式栈端到端（INT-02 交付栈）执行 `npm run test:e2e:qa03:db`（等价 `make test-e2e-qa03-db`），配置 `playwright.qa03-db.config.ts`：启动器 `tests.e2e.serve_real --variant {success,partial,revoke}` 自动初始化并复用一个一次性本地 PostgreSQL 集群（运行期根目录默认 `%TEMP%/rd-qa03`，只监听 127.0.0.1、不注册系统服务），按变体创建并迁移 `rd_qa03_<variant>_test` 三个数据库，各自拉起**独立 worker 进程**（`tests.e2e.worker_real`），再启动 `app.database` 正式装配（8020–8022）与 http 模式 Vite（5190–5192）；真 PDF/DOCX 由配置加载时运行 `python -m tests.platform.int02_fixtures --output …` 生成，失败截图与 trace 写入 `frontend/test-results/qa03-db/`。前置条件：从 [EDB 便携版页面](https://www.enterprisedb.com/download-postgresql-binaries)下载解压 PostgreSQL binaries 到英文路径，并设置 `RD_QA03_PG_HOME` 指向其 `pgsql` 目录（需含 `bin/initdb`；可选 `RD_QA03_PYTHON` 覆盖后端解释器——命令字符串已对解释器路径加引号，含空格的用户目录路径可直接使用）。运行期根目录可用 `RD_QA03_RUNTIME_ROOT` 覆盖；若 pgdata 被系统临时目录清理损坏，启动器会自动重建集群与变体库。该套件同样只使用登记合成素材与 fake 模型，故障/同步开关只来自服务端环境变量；手工停掉自管集群可用 `python -m tests.e2e.serve_real --stop-cluster --pg-home "%RD_QA03_PG_HOME%"`。覆盖范围、T 编号映射与实测结果见 [QA-03 记录](team/qa-03.md)。
