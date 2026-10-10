# SET-01 本地交付与消费说明

对应 [Issue #7](https://github.com/Riverstar123/ResumeDoctor/issues/7)，负责人 A，评审 C、E，内部端口需 C/D/E 核对。本轮用户明确授权提前在本地完成并 commit，要求待其他成员完成演练后再通知推送。因此本记录是本地工程验证证据，不代表远程验收或合并。

## 前置核验

2026-10-10 通过 `gh issue view`、`gh pr view`、PR 行内评论 API 及更新后的 `origin/main` 核验。分支 `codex/set-01` 起点为 `eff9b96150f22409315f200c183780e27966ea85`。下列合并提交均为该 main 的祖先，A/C 文件已通过 `git show origin/main:路径` 回读。

| 前置 / owner | 交付 PR / base | main 与合并提交 | 可定位验收证据 / 缺口 |
|---|---|---|---|
| 规划 #31 / A | [PR #31](https://github.com/Riverstar123/ResumeDoctor/pull/31) / main | 已合并，`a91a52f555885ab0763b1beb135f38cf9ea2b920` | PR 正文记录 OpenAPI、4 份样例、评分及文档检查；规划资料已到 main，无需重复提交 |
| [#2](https://github.com/Riverstar123/ResumeDoctor/issues/2) / A | [PR #32](https://github.com/Riverstar123/ResumeDoctor/pull/32) / main | 已合并，`bd025798a322dec830acf5f0339475e3c0f07ee2`；Issue 已关闭 | [A.md](onboarding/A.md)；PR 正文列出契约、链接及隐私检查；C `huih02427-cmyk` 实际 APPROVED，但评审正文为空、无行内评论，有内容的评审证据仍缺 |
| [#3](https://github.com/Riverstar123/ResumeDoctor/issues/3) / B | 未找到交付 PR / 不适用 | Issue OPEN，未核实任何合并提交 | B 演练交付与验收缺失 |
| [#4](https://github.com/Riverstar123/ResumeDoctor/issues/4) / C | [PR #33](https://github.com/Riverstar123/ResumeDoctor/pull/33) / main | 已合并，`eff9b96150f22409315f200c183780e27966ea85`；Issue 已关闭 | [C.md](onboarding/C.md)；PR 正文记录文件范围及契约核对；Riverstar123 APPROVED“完成演练”，无行内评论；没有可核实的 D 角色评审记录 |
| [#5](https://github.com/Riverstar123/ResumeDoctor/issues/5) / D | 未找到交付 PR / 不适用 | Issue OPEN，未核实任何合并提交 | D 演练交付与验收缺失 |
| [#6](https://github.com/Riverstar123/ResumeDoctor/issues/6) / E | 未找到交付 PR / 不适用 | Issue OPEN，未核实任何合并提交 | E 演练交付与验收缺失 |

正常远程开工前置尚未全部满足。本地提前准备按用户本轮授权执行，不修改 Issue 状态，也不代表其他人完成演练。以后推送前重新核验 main 和前置，必要时处理实际变更。C 的账号由用户确认；D/E 账号未确认，不猜测或代发评审。

## 版本与兼容依据

| 配置 | 固定版本 / 来源 | 判断与验证边界 |
|---|---|---|
| [.python-version](../../.python-version) | [Python 3.12.13 官方发布](https://www.python.org/downloads/release/python-31213/) | 后端限定 Python 3.12 系列；实际隔离安装与测试使用 3.12.13 |
| [backend/pyproject.toml](../../backend/pyproject.toml)、[uv.lock](../../backend/uv.lock) | uv 0.11.15；FastAPI 0.143.0、Pydantic 2.14.0、pydantic-settings 2.15.0、Uvicorn 0.54.0 | [FastAPI 官方发布说明](https://fastapi.tiangolo.com/release-notes/)支持 Python 3.12/Pydantic 2；[PyPI 固定版本元数据](https://pypi.org/project/fastapi/0.143.0/)与各依赖 `Requires-Python` 核对；实际按锁文件安装测试通过 |
| 数据库可选依赖 | [SQLAlchemy 2.1.4](https://pypi.org/project/sqlalchemy/2.1.4/)、[Alembic 1.20.0](https://pypi.org/project/alembic/1.20.0/)、[psycopg 3.3.6](https://pypi.org/project/psycopg/3.3.6/) | 预留统一安装组 `database`；[SQLAlchemy PostgreSQL 方言](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html)与 [psycopg 安装说明](https://www.psycopg.org/psycopg3/docs/basic/install.html)用于兼容核对，未交付数据库业务 |
| [.nvmrc](../../.nvmrc) | [Node 22.22.0](https://nodejs.org/en/download/archive/v22.22.0) | 满足 [Vite 官方要求](https://vite.dev/guide/)的 22.12+；本轮未创建或运行前端，#9 仍需锁前端依赖 |
| [compose.yaml](../../compose.yaml) | [PostgreSQL 17.11](https://www.postgresql.org/docs/17/release-17-11.html) | 仅 DB 配置，密码由本地环境注入；Compose 配置校验通过，未运行数据库容器 |

全部 Python 直接依赖精确固定，传递依赖与数据库可选组一同锁定；测试/lint/build 工具版本见 pyproject 和锁文件。[uv 官方同步说明](https://docs.astral.sh/uv/concepts/projects/sync/)是 `--locked` / `--frozen` 命令依据。原生命令及配置复制步骤见 [README](../../README.md#本地后端开发)。环境私有镜像不可用时，本轮临时使用官方 PyPI 与官方 Python 下载源，未修改全局配置或锁文件源来适配私有机器。

## 内部端口消费

```python
from app.contracts import ProfileContent, JobContent, ScoreResult, ReportContent
from app.contracts.ports import IntakePort, ScoringPort, ReportingPort, ModelGateway, TaskContext
```

使用 README 安装得到的环境执行 `uv run --project backend --frozen python`，各模块即可使用上述导入。实现类按 Protocol 签名提供方法，由后续 M2 编排显式接收实现实例；没有全局数据库连接或模型客户端。Protocol 的运行时检查只检查方法存在，不代替类型检查或消费者评审。

| 消费者 | 协议及方法 | 约定 |
|---|---|---|
| C / M3 | `IntakePort`：extract_document、build_profile、advance_conversation、extract_job | async；借用文件句柄由 M2 负责关闭；结果为内部 dataclass 或共享 ProfileContent/JobContent，历史轮次由 M2 只传用户消息 |
| D / M4 | `ScoringPort`：assess_requirements、calculate_score | sync，无数据库/模型访问；使用共享 RequirementAssessment/ScoreResult；版本参数由编排传入 |
| E / M5 | `ReportingPort`：generate_report、export_markdown | 报告 async，导出 sync；读取已冻结 Profile/Job 与已存 DiagnosisItem，不创建资源版本 |
| C/E → E 网关 | `ModelGateway.generate_structured` | async；返回 JSON 映射及共享 ModelMetadata；接收输出 Schema、超时、任务名和经裁剪的上下文 |

所有模型 I/O 方法显式接收 `context=TaskContext(model_id=...)`，由 M2 传任务冻结的公开选择；实际凭证与 provider 映射由 E 的后续适配器处理。`StructuredResult`、文档页段及对话结果 dataclass 仅用于内部返回值，不扩展 HTTP 契约。签名忠于 [架构端口表](../02-architecture.md#内部端口)，这些 async/context 细节仍待 C/D/E 实际评审。

DTO 保留 required、允许 null 的必填字段、枚举、额外字段禁止、嵌套边界、uniqueItems、UUID/date-time 格式和数字范围。JSON 整数兼容 `1.0`，拒绝布尔/字符串伪整数；线上的 UUID/date-time 保留字符串形式。Schema 校验不能证明证据是来源子串、引用存在、同一资源不同版本不重复、资源已确认或属于会话，也不能验证状态机、事务和模型元信息对应性：C/D/E 负责各自语义校验，M2 负责权限、版本、事务与任务编排，仍按 [API 说明](../api/README.md) 与 [数据库文档](../03-database.md) 实施。

## 契约差异与最小修正

[验收矩阵 T07](../07-testing.md) 原字段 `unknown_ratio` 与 [OpenAPI ScoreResult](../api/openapi.json)、[评分规则](../05-scoring.md)及 [diagnosis-item.json](../examples/diagnosis-item.json) 的 `unknown_weight_ratio` 冲突。本次仅更正 T07 字段名；保留手算样例 66.7 / 0.1667 和类别 60/100，不把这些数值描述成所有输入的结果。D/E 的验收脚本与 B 的展示应读取 `unknown_weight_ratio`。没有改 HTTP 设计、数据库文档或评分算法。

## 本地验收证据

工程复制到全新临时目录，未复制已有 `.venv`、私人指南或真实配置；从空密钥模板创建 `.env`，按锁文件创建新的 Python 3.12.13 虚拟环境。使用已有官方包缓存离线安装，且重新构建本地可编辑包。执行 README 对应命令时临时设置 `UV_NO_CONFIG=true` / `UV_OFFLINE=true` 与独立缓存路径，避免本机失效镜像影响可复现结果；这些机器路径不进入工程配置。

| 验收条目 | 文件 / 命令证据 | 本地结果 |
|---|---|---|
| 锁定安装 | `make setup` → `uv sync --project backend --locked` | 干净临时目录新建 `.venv` 成功；Python 3.12.13，uv 0.11.15 |
| 最小启动 | `make dev`；`curl --fail http://127.0.0.1:8000/healthz`；读取 `/openapi.json` | 服务实际启动，HTTP 200 `{"status":"ok"}`；实际 paths 仅 `/healthz`；已停止测试服务 |
| 有效/非法输入与无凭证导入 | `make test`；[tests](../../backend/tests/test_contracts.py)、[导入检查](../../backend/tests/test_settings_and_imports.py)、[消费者 test double](../../backend/tests/test_ports.py) | 28 passed，无 warning；有效样例、缺 required、非法枚举、额外字段、嵌套限制、nullable、uniqueItems、导入禁网络与坏配置隔离检查通过 |
| 设计与实现比较 | `make contracts`；[检查入口](../../backend/app/tools/check_contracts.py) | OpenAPI 3.1 与本地引用通过；36 个命名 Schema 及内联 SessionCreate 与 DTO 语义一致；4 份合成样例通过且往返仍符合设计；18 个业务操作明确 pending |
| 比较器能抓差异 | [test_routes.py](../../backend/tests/test_routes.py)、test_contracts.py | required、响应码、安全要求、参数及未计划路由的故意变异均被拒绝；忽略展示描述与引用名差异，保留验证限制 |
| 代码格式与基本静态检查 | `make lint` | Ruff check 与 format --check 通过 |
| DB 配置基线 | `RD_POSTGRES_PASSWORD=synthetic-config-only docker compose config --quiet` | 配置校验通过，未启动 PostgreSQL，未运行迁移 |
| 数据库依赖兼容 | `uv sync --project backend --locked --extra database`；导入 SQLAlchemy/Alembic/psycopg 并创建未连接的 `postgresql+psycopg` engine | 安装及导入成功，版本 2.1.4 / 1.20.0 / 3.3.6；没有打开数据库连接 |

测试结果用于 SET-01 工程与契约验收，不是 T01–T21 业务流程通过证据。没有真实简历、模型调用、M3/M4/M5 业务实现或前端测试。消费者评审、反馈处理、远程 PR、合并及 Issue 关闭均待完成；本地提交后等待用户通知，再核验前置并推送。
