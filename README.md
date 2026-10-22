# ResumeDoctor · 简历诊断 Web 应用

面向求职者的小组项目：上传简历或通过对话整理经历，输入 1–5 个目标岗位 JD，获得逐岗位匹配评分、差距清单、修改建议和学习行动。

**当前开发入口：PostgreSQL、独立 worker 与真实业务模块，模型为 fake。** INT-02 接入 C 的文件解析/提取校验、D 的确定性评分与 E 的报告服务。登记合成素材、实测范围与待队友复验项见 [INT-02 记录](docs/team/int-02.md)；不代表真实 AI 验收。

## 从这里开始

1. 全员阅读 [需求](docs/01-requirements.md)、[五人分工](docs/04-team-plan.md)。
2. GitHub 新手阅读 [协作上手](docs/team/github-guide.md)。
3. 在项目根目录启动 Claude Code，先读取 [CLAUDE.md](CLAUDE.md)，再阅读自己的模块说明。
4. 先完成 [启动导航](https://github.com/Riverstar123/ResumeDoctor/issues/1) 中自己的协作演练，再从 [任务索引](docs/team/backlog.md) 领取满足依赖的任务。
5. 实现遵循 [API](docs/api/README.md)、[数据字典](docs/03-database.md)、[评分规则](docs/05-scoring.md) 和 [项目基线](docs/00-decisions.md)，以 [验收计划](docs/07-testing.md) 检查结果。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [项目基线](docs/00-decisions.md) | 技术栈、范围、开工规则与变更管理 |
| [需求与验收](docs/01-requirements.md) | 用户流程、MVP 范围、异常行为 |
| [架构与内部接口](docs/02-architecture.md) | 模块之间怎么配合 |
| [数据库](docs/03-database.md) | 表、字段、关系、事务、数据生命周期 |
| [分工与里程碑](docs/04-team-plan.md) | 五个人各交付什么，谁审谁 |
| [评分规则](docs/05-scoring.md) | 可复现的分数与证据解释 |
| [AI 契约](docs/06-ai-contract.md) | 提取、追问、诊断与失败降级 |
| [验收计划](docs/07-testing.md) | 如何证明整条流程可用 |
| [API 说明](docs/api/README.md) / [OpenAPI](docs/api/openapi.json) | 请求、响应、错误与数据结构 |
| [开发与部署约定](docs/08-development.md) | 后续环境准备及集成方式 |
| [技能参考取舍](docs/09-skill-reference.md) | 如何借鉴 hr-resume-screening |
| [GitHub 上手](docs/team/github-guide.md) / [Claude 提示模板](docs/team/claude-prompts.md) | 如何协作而不互相覆盖 |

## 五人模块

| 角色 | GitHub 用户名 | 模块 | 文档 |
|---|---|---|---|
| A | [Riverstar123](https://github.com/Riverstar123) | M2 后端平台、数据库和集成 | [M2](docs/modules/M2-platform.md) |
| B | [junnnh26](https://github.com/junnnh26) | M1 Web 前端全部页面 | [M1](docs/modules/M1-web.md) |
| C | [huih02427-cmyk](https://github.com/huih02427-cmyk) | M3 简历、对话与 JD 结构化 | [M3](docs/modules/M3-intake.md) |
| D | [mysteriesy](https://github.com/mysteriesy) | M4 证据匹配与确定性评分 | [M4](docs/modules/M4-scoring.md) |
| E | [y1324-cyber](https://github.com/y1324-cyber) | M5 AI 报告、模型网关与验收协调 | [M5](docs/modules/M5-report.md) |

账号映射由维护者于 2026-10-12 确认，与 [CLAUDE.md](CLAUDE.md#角色与-github-账号) 同步。认领和请求评审使用真实用户名；账号映射不代表权限或验收状态，历史 PR 身份按实际记录。

角色始终使用 A–E。全员对自己模块的测试和文档负责；A 协调合并与集成。先用 fake 模型联调，E 交付真实模型配置入口后，由组长填写本地配置完成真实 AI 验收。

## 当前仓库状态

**M1 Web 前端**已交付完整输入、档案/JD 确认、任务进度、多岗位报告、模型切换与导出页面；独立演示与 HTTP 联调命令见 [前端运行说明](frontend/README.md)，验证与限制见 [前端交付记录](frontend/DELIVERY.md)。前端由 `frontend/.nvmrc` 固定 Node 24.14.1，与根目录后端工具链的 Node 版本不同，按各自目录的 `.nvmrc` 切换。

- [完整 Issues](https://github.com/Riverstar123/ResumeDoctor/issues) 与 [阶段里程碑](https://github.com/Riverstar123/ResumeDoctor/milestones) 是任务入口。
- 每个任务有负责人、前置依赖、范围、验收和 Claude Code 提示。
- 前端可用明确标记的 mock 独立运行，也可切到 `httpApi` 对接后端；不把 mock 演示等同于真实 AI 验收。
- 后端提供 `GET /healthz` 和全部设计业务路由；`make dev` 与 `make worker` 使用统一的 PostgreSQL/业务装配。`make dev-synthetic` 保留 INT-01 的内存合成链路，`make dev-api-fakes` 保留 API-01 测试替身。
- 仓库使用方式见 [协作指南](docs/team/github-guide.md)；模型切换入口见 [模型配置](docs/10-model-configuration.md)。

## 本地后端开发

在仓库根目录运行。使用 [uv 0.11.15](https://docs.astral.sh/uv/getting-started/installation/)，Python [3.12.13](https://www.python.org/downloads/release/python-31213/) 由 `.python-version` 固定；锁文件位于 `backend/uv.lock`。无需模型密钥；默认联调需要先配置 PostgreSQL（下方步骤）。若只跑无数据库的历史合成演示，使用 `make dev-synthetic`（已有私人 `.env` 时只补模板中的新增配置，不覆盖原文件）：

```sh
uv python install 3.12.13
cp backend/.env.example backend/.env
uv sync --project backend --locked --extra database
# 配置 DATABASE_URL、UPLOAD_DIR 后：
make migrate
make dev
# 另一终端，配置相同：
make worker
```

`make dev` 通过 `app.database:create_app` 启动 `http://127.0.0.1:8000`；`make dev-database` 是相同入口。`/healthz` 仅表示进程存活，不能证明任务成功。独立 worker 必须运行，网页任务才会推进。历史 INT-01 入口改名 `make dev-synthetic`，使用内存存储；API-01 全替身入口为 `make dev-api-fakes`。

```sh
make test
make contracts
make lint
```

这些命令分别执行 pytest、设计 OpenAPI/DTO/合成样例/实际路由比较、Ruff。合成样例检查读取 [docs/examples](docs/examples/README.md)，不写数据库。平台和集成工厂的全部路由均有契约检查；集成测试真实调用 M4，并正常验证两份不同 JD 的独立提取、确认、诊断和模型切换，不再保留该验收的 `xfail`。模块测试不能替代页面复验和队友评审，当前验收状态见各交付记录。装配仅支持 `LLM_MODE=fake`，不会读取真实模型调用入口。

默认入口使用 PostgreSQL 保存版本和结果，API/worker 重启后可继续读取；历史 `make dev-synthetic` 仍会丢失内存资料。浏览器使用同源 `/api/v1` 代理并设置 `credentials: "include"`；写请求的 Origin 必须匹配 `ALLOWED_ORIGINS`，CLI 也需显式带可信 Origin。HTTPS 部署须设置 `SESSION_COOKIE_SECURE=true`。可复制的调用脚本和可控失败示例见 [B 联调说明](docs/team/api-01.md#b-的调用路线)。

实际前后端联调从 [INT-02 运行步骤](docs/team/int-02.md) 开始：前端必须运行 `npm run dev:api`，配置公开的合成处理告知，网页使用默认允许的 `http://localhost:5173`；若改用 127.0.0.1，需显式加入 `ALLOWED_ORIGINS`。`npm run dev` 默认是前端自己的 mock，不构成五模块集成证据。

Node [22.22.0](https://nodejs.org/en/download/archive/v22.22.0) 由 `.nvmrc` 固定，满足 [Vite 的 Node 要求](https://vite.dev/guide/)；前端工程由 B 的 #9 创建。PostgreSQL [17.11](https://www.postgresql.org/docs/17/release-17-11.html) 由 `compose.yaml` 固定。DB-01 使用锁定的驱动与迁移工具：

```sh
uv sync --project backend --locked --extra database
```

需要数据库时，在本地设置 `RD_POSTGRES_PASSWORD` 后运行 `docker compose up -d database`，在私有 `backend/.env` 填写对应 `DATABASE_URL`（PostgreSQL + psycopg），然后执行：

```sh
make migrate
make dev-database
# 另一终端，连接相同 DATABASE_URL 和 UPLOAD_DIR：
make worker
```

`make migrate` 对目标库执行显式 Alembic 升级，首次使用应指向自己创建的空库；不会重置数据库。数据库入口持久化会话、内容版本、幂等键和任务；`make dev` 使用相同持久化装配。持久化任务必须运行独立 worker 才会推进，不能用 queued 状态声称完成提取或报告。worker 用 60 秒租约、15 秒续约、最多两次领取和入队起五分钟截止；Ctrl-C/SIGTERM 停止后，未提交任务等租约过期接管。API 每分钟清理，worker 也执行清理；单次入口为 `make cleanup-db`。真实数据库验收使用独立临时库，设置 `RD_TEST_DATABASE_URL` 后运行 `make test-db`，不可指向未知数据库。迁移与持久化见 [DB-01](docs/team/db-01.md)，启动、恢复、模型映射兼容及结果边界见 [JOB-01](docs/team/job-01.md)。
