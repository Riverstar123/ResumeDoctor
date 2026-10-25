# JOB-01：数据库 worker、租约恢复与任务截止

对应 [Issue #15](https://github.com/Riverstar123/ResumeDoctor/issues/15)，主责 A；评审 D（`mysteriesy`）、E（`y1324-cyber`），账号来自 [CLAUDE.md](../../CLAUDE.md#角色与-github-账号)。JOB-01 交付当时使用合成提取、真实 M4 确定性评分、E 的 fake 网关；本文当时的实测不代表 #22。当前默认入口已经由 [INT-02](int-02.md) 接入真实 M3/M5 模块，模型仍为 fake。

## 前置核验

2026-10-21 读取 Issue 正文/评论、关联 PR 和评审，HTTPS fetch 刷新 `origin/main`。没有以 CLOSED 或标签代替验收。

| 前置 | 交付 PR / base | 已合入 main / 合并提交 | 验收证据 |
|---|---|---|---|
| #14 DB-01 | [#50](https://github.com/Riverstar123/ResumeDoctor/pull/50) / main | 是；`13f2c98648ff6f10db94c7c64b1b57a5c9b9d7fc` | C 对 `80c4b5c` APPROVED，独立复跑原 HTTP/连接池反例及 377 项测试；A 验证合并树 484 项。[验收记录](https://github.com/Riverstar123/ResumeDoctor/issues/14#issuecomment-6313388061) |
| #13 INT-01 | [#47](https://github.com/Riverstar123/ResumeDoctor/pull/47) / main | 是；`f08cd6989df984b654ce7eadf1f52b8aeb701215` | D 对 `ac5efb3` APPROVED，343 项回归；B 同版独立双 JD 页面、模型切换、失败降级与导出复验通过。范围为 P1 synthetic/fake |

两个实际 squash merge commit 均已用 `git merge-base --is-ancestor` 确认在刷新后的 main 中，并读取 repository、迁移和装配内容。#15 仍 OPEN，无已有交付 PR；独立分支 `codex/job-01` 从上述最新 main `13f2c98` 建立。既存 `.gitignore` 暂存/未暂存修改保留，不混入交付。

## 实现与兼容

- `backend/app/platform/jobs/store.py`：领取、续约、恢复、fencing、原子结果和逐项聚合。使用现有 tasks 的 attempt/lease_token/lease_until/heartbeat_at/deadline_at，不改初始迁移或 HTTP Schema。
- `worker.py`：事务外调用可注入 Intake/Scoring/Reporting 端口；模型等待期间独立心跳；总截止独立于心跳数据库请求。`__main__.py` 提供独立进程、信号停止和轮询入口。
- `repositories/postgres.py`：旧 `commit_profile_task` 必须携带租约 token 并核对冻结输入；公共人工建岗/编辑入口拒绝携带 created_by_task_id 冒充 worker。正常人工编辑不变，真正 worker 通过已 fencing 的事务私有方法原子提交。
- `database.py`：默认改为与 INT-01/worker 相同的 `GatewayCatalog(FakeModelDirectory)`，HTTP 的公开 model_id/DTO 不变。执行前检查 enabled、能力，以及冻结的 provider/model/prompt/config，映射变化以 MODEL_UNAVAILABLE 失败，不换模型。

DB-01 旧默认目录的 `api-01-synthetic-stub/api-01-fake-v1` 与 E 的 `synthetic-fake-v1/fake-gateway-v1` 是不同映射，不能只因 model_id 相同就视为同一个模型。已有旧映射 queued 任务不会被偷偷改写：执行时明确失败；用户要按新目录重新创建新任务并使用新幂等键。仅改 M2 装配，不重写 M3/M4/M5 或真实网关。D/E 需复核此内部装配兼容说明。

## 租约与事务

参数来自 `docs/02-architecture.md`：租约 60 秒、每 15 秒续约、最多两次领取、从入队起总截止五分钟。领取先读取候选，再按 session 共享锁 → task `FOR UPDATE SKIP LOCKED` 顺序锁定并重新检查；避免和撤销的 session → task 锁序相反。领取事务提交后才调用业务。

每个读写事务校验 session、running、token、lease_until、deadline_at；取得资源锁后、事务提交前再次读取时钟，等待父行/item/清理队列跨过有效期时整笔回滚。终态禁止后续修改；旧 worker 即使供应商返回也不能写回。deadline 和尝试耗尽由独立 reap 收敛；后者使用脱敏 INTERNAL_ERROR，deadline 使用 TASK_TIMEOUT。

档案/JD 版本按 created_by_task_id 唯一，消息按 `(task_id,role)` 唯一，与 task 成功状态同事务写入。对话仍比较原 base_version，成功才保存双方消息。诊断复用冻结的已确认版本，逐项先持久化 score 再请求报告；重领复用已有 score 和终态 item，不重算覆盖。全部 item 终态后才聚合 task；全成功 succeeded、有分但非全成功 partial、全无分 failed。报告失败保留评分为 score_only；总超时保留完成项并把未完项收敛为 score_only/failed。

会话撤销/过期后，所有提交被会话条件阻断，清理沿用 DB-01；不增加公开 cancelled 枚举。document 完成/失败与 task 状态在同一事务预约删除；文件 I/O 在线程内用上下文关闭 OS 句柄，端口借用有界内存流，取消不会留下失管文件句柄。

数据库只保证持久结果不重复。进程若在供应商已处理、结果未提交时退出，租约接管可能再次调用供应商并再次计费；fencing 不撤回外部请求，也不承诺供应商 exactly-once。M2 不在异常后自行重试模型：45 秒单次和至多一次共享重试仍由 E 网关管理，整个 worker 执行受剩余 deadline 约束。

## 启动、停止与恢复

```sh
uv sync --project backend --locked --extra database
# 本地私有 backend/.env：DATABASE_URL、UPLOAD_DIR 与 API 保持一致，LLM_MODE=fake。
# 只对自己管理的目标库显式迁移；API/worker 不自动建表或重置数据。
make migrate
make dev-database   # 一个终端运行 API
make worker         # 另一终端运行独立 worker；可再开第二个进程
```

单次运行：`uv run --project backend --frozen --extra database python -m app.platform.jobs --once`。不传 `--once` 时默认每秒检查空队列；可用 `--poll-seconds` 调整技术轮询间隔，租约参数不由 CLI 修改。

Ctrl-C 或 SIGTERM 停止当前编排，不人为写 cancelled/failed；未提交结果等租约过期后由重启进程接管，已提交结果保持。SIGKILL/进程退出同样依靠过期租约；最多两次领取，耗尽则收敛失败/部分成功。执行恢复不依赖 API 进程存活；API 与 worker 必须共享数据库和同一个私有 UPLOAD_DIR。worker 也运行会话/文件清理，API 停机时仍可清理；暂时数据库故障只输出固定错误码并在轮询后重试，不输出连接串或用户内容。数据库不可用时无法保证即时持久化终态，恢复连接后 reap 继续收敛。

JOB-01 当时的文件/对话/JD 提取是 SyntheticIntake。当前 `make dev` / `make dev-database` 与 `make worker` 共享 INT-02 的 GatewayIntake、真实文档解析、ScoringService 与 ReportService；fake 模型只识别登记合成原文，真实模型仍未在本轮启用。当前入口继续拒绝 LLM_MODE=real，历史内存合成链路使用 `make dev-synthetic`。

## 验证记录

2026-10-21，macOS / Python 3.12.13 / uv 0.11.15；SQLAlchemy 2.1.4、Alembic 1.20.0、psycopg 3.3.6 均按现有锁文件安装，无依赖变更。测试环境为 `/private/tmp/rd-job01-env`；未使用损坏的 backend/.venv。

新建容器 `rd-job01-test-20261021`，PostgreSQL 17.11（Debian 17.11-1.pgdg13+2、aarch64），tmpfs、仅绑定 `127.0.0.1:49658`，数据库名 `rd_db01_test`，public 初始 0 表。未连接或重置未知数据库。专用入口 `make test-db` 需显式设置已迁移且名称含 test 的 RD_TEST_DATABASE_URL。

实际 UV 命令使用 `UV_PROJECT_ENVIRONMENT=/private/tmp/rd-job01-env`、`UV_CACHE_DIR=/private/tmp/resumedoctor-int01-uv`、`UV_NO_CONFIG=true`、`UV_NO_SYNC=true`；迁移 RD_DATABASE_URL 和测试 RD_TEST_DATABASE_URL 均指向上述本轮临时库。首次安装使用 `uv sync --project backend --locked --extra database --python <已验证的3.12.13解释器>`，测试没有替换数据库或取消锁定要求。

| 验收条目 | 文件 / 实际命令及过程证据 | 结果 |
|---|---|---|
| 迁移与兼容 | `make migrate` 两次；`alembic -c backend/alembic.ini check` | revision0001，无新增升级差异，无新迁移 |
| T14 独立进程抢单 | `test_t14_two_independent_workers_compete_for_one_task` | 两个 spawn 进程、各自新 Engine；同一 task 只有一个领取，attempt=1，lease=60秒、入队deadline=5分钟 |
| T14 真崩溃接管 | `test_t14_process_crash_reclaim_and_old_fencing_token` | 首进程领取提交后 `os._exit(19)`；推进时钟61秒，第二 spawn 进程实际 Worker.execute→业务端口→事务提交；attempt=2、token变化；旧token/再次提交均拒绝，精确一个job及version |
| 续约与尝试上限 | heartbeat/deadline/max-attempt 测试 | 15秒续约延长到60秒且不超过deadline；过期token不能续约/提交；最多两次领取，耗尽终态；未领取queued也在五分钟后TASK_TIMEOUT |
| 无网络长事务 | `test_model_wait_renews_lease_and_holds_no_database_transaction` | port同步点等待时实际heartbeat更新；观察pg_stat_activity无idle-in-transaction；结果只写一次 |
| T12 状态与部分结果 | 参数化item聚合及reclaim保分测试 | succeeded/mixed/score_only/allfailed均满足公开状态不变量；全无分有error；已成功item不变，已有score复用，超时剩余item分别score_only/failed，task=partial |
| T16 撤销/过期 | session-invalidated、worker-revoke同步点及document测试 | 运行期间撤销/过期后旧结果不写回；无新版本/消息/资源；原件通过持久队列最终删除 |
| 旧版本/消息原子性 | chat-conflict/success及原T04/T15适配 | 手工编辑后后台VERSION_CONFLICT，版本数保持2、消息0；正常一次追加version2和两条消息，重复拒绝；旧无token提交和公共携taskid写入口均拒绝 |
| 取消时序额外反例 | `test_deadline_cancels_model_even_while_heartbeat_waits_on_pg_lock` | 实际持task锁让heartbeat等待，deadline在未解锁前取消port，再做DB收尾；此前“先fail写库再cancel”已被测试复现并修复 |
| 锁后时效与文件句柄 | profile锁跨lease、取消文件读取线程测试 | 等父行锁期间跨过lease，整个版本/消息事务回滚；文件read线程在取消后完成时OS句柄最终closed，无失管句柄 |
| 模型/重试边界 | disabled/mapping-changed、E invalid-json报告测试 | 执行前停用/换映射返回MODEL_UNAVAILABLE且不换模型；E每item至多两次尝试，worker attempt仍1，无M2额外重试 |
| PostgreSQL 专项 | `make test-db` | **61 passed in6.95s，0 skipped**，含原34项及JOB-01新增27项 |
| 完整后端 | `PYTHONUTF8=0 make test contracts lint`，设置RD_TEST_DATABASE_URL | **511 passed in20.56s，0 skipped**；36 Schema、4示例、18业务操作、pending=[]。首次lint仅新包空行格式失败；修正后单独重跑 `make lint`，Ruff check/format 89文件通过 |
| 真HTTP+独立CLI | `/private/tmp/rd-job01-env/bin/python /private/tmp/rd-job01-cli-smoke.py`，本轮临时脚本 | 实际uvicorn HTTP API、`python -m app.platform.jobs --once` 独立进程：双JD提取/确认→66.7与0.0评分→两报告及导出；chat得到version2/两消息、旧诊断完全不变；上传生成profile并删除原件；持续worker收到SIGTERM后exit0。资料和解析为synthetic/fake，不是浏览器或真实文件提取验收 |
| 清理与最终引用 | `make cleanup-db` 与聚合SQL | 清理入口输出sessions_removed=0、files_removed=0（前述CLI已清理其合成会话）；12表最终全部0行；profile.latest、diagnosis.profile、item.job无效引用各0。过程中的非零行数由上述测试直接断言，不用空表充当并发证据 |

未验收：D/E 队友机器、本轮浏览器页面、真实模型/供应商、真实文件端到端、断网/磁盘故障或操作系统级长时间挂起。逻辑租约测试注入时钟，真实进程测试确实独立启动、退出、重连PostgreSQL，不以串行内存替身冒充恢复。

验证和最终聚合检查后，已删除本轮自建 `rd-job01-test-20261021` 容器及 tmpfs 数据；未操作其他数据库/卷。原有 `.gitignore` 的暂存和未暂存修改保持，暂存清单只有既存 `.gitignore`；`git check-ignore -v -- 指南.md` 命中根 `/指南.md`，`git ls-files -- 指南.md` 为空。

## 当前状态

本地实现、实库验证及PR说明完成。维护者已授权提交、推送、创建关联PR并请求D/E评审；待队友复验与评审，未授权本轮合并。#15仍OPEN；最终发布和评审状态以GitHub实时记录为准，不自动启动下一张Issue。
