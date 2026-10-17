# INT-01 本地装配与验收记录

关联 [Issue #13](https://github.com/Riverstar123/ResumeDoctor/issues/13)、[PR #47](https://github.com/Riverstar123/ResumeDoctor/pull/47)。负责人 A；指定评审 E（`y1324-cyber`）、B（`junnnh26`），账号映射来自根 README / CLAUDE.md。初轮记录日期为 2026-10-15，本轮更新为 2026-10-17（Asia/Shanghai）。

**状态：已同步最新 main，独立双 JD 正常测试和本地真实 HTTP 页面复核通过；修复版仍待 B 复验和队友评审。** C 的双 fixture 缺口已由 #48 解决，本轮不再把它列为待 C 开发。B 已复现旧提交 `ec07858`，但其记录明确第二份 JD 失败、不代表同意合并；本地技术验证不能代替 B 对修复版的复验。未合并 PR、未关闭 Issue，也未自行撤销 D 的修改请求。

## 前置实核与同步

本轮实时读取 PR、reviews、B 评论及关联 Issue，并 `git fetch origin`。核查 `origin/main=8c0c9ac1c5e8ec313821aa71a90821ccf7b5aa85`；下列实际 merge commit 均通过 `git merge-base --is-ancestor <commit> origin/main`，交付文件实际存在。没有因 Issue CLOSED 或源分支提交不在祖先链上判断交付状态。

| Issue / owner | 交付 PR / base / 状态 | main 中实际 merge commit | 验收证据 |
|---|---|---|---|
| [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) / A | [#42](https://github.com/Riverstar123/ResumeDoctor/pull/42) / main / MERGED | `b99c037b1c09590bed7723d3df3bf60644e38b77` | D 对 `d64e5a1` APPROVED；fake API、平台回归、契约及 lint |
| [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9) / B | [#37](https://github.com/Riverstar123/ResumeDoctor/pull/37) / main / MERGED | `b318d202916e612aaad46fc9da97749bd0b469c7` | A 对 `1900c8b` APPROVED；前端构建、组件及 mock/HTTP stub 浏览器测试 |
| [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) / C | [#44](https://github.com/Riverstar123/ResumeDoctor/pull/44) / main / MERGED | `b024b993dd42373043f876879987ed4acb1cb563` | D、A 对 `58d6592` APPROVED；纯校验与初版固定合成端口 |
| [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11) / D | [#39](https://github.com/Riverstar123/ResumeDoctor/pull/39) / main / MERGED | `7ae105a78e5bf85e0de3d6e1e52f131fb795cf20` | A 对 `4a9b41c` APPROVED；手算、舍入、空分母、顺序及不可变输入 |
| [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12) / E | [#46](https://github.com/Riverstar123/ResumeDoctor/pull/46) / main / MERGED | `ce142a13572ceb2d20848731d058f72cb26e95ad` | A 对 `c1ddd49` APPROVED；冻结 Schema 与跨 M3 素材一致性 |
| 双 JD 修复 / C、A | [#48](https://github.com/Riverstar123/ResumeDoctor/pull/48) / main / MERGED | `8c0c9ac1c5e8ec313821aa71a90821ccf7b5aa85` | D 对 `afba39a` APPROVED；双 fixture 及事实/证据边界修复 |

[#18 / PR #40](https://github.com/Riverstar123/ResumeDoctor/pull/40) 已交付真实 matcher-v1，实际合并提交 `c7c39d1bf225a11f07f1736d82de14f93c2df3d3`；本装配使用真实函数，不把匹配伪装为集成层的固定数字。正式报告模块未装配，继续使用明确标记的 P1 fake 报告。

沿用 #47 的 `codex/int-01`，从 `ec07858` 合并最新 main，同步提交为 `130257e`。同步前保存 `.gitignore` 的暂存与工作区内容，合并提交排除私人改动，同步后逐字节恢复。未修改其他任务工作树。业务变更仅为集成测试、运行/验收说明与安全证据。

## 导出与装配边界

| 模块 | 实际入口 | 装配方式与限制 |
|---|---|---|
| M1 / B | `frontend/src/api/index.ts` 的 ApiClient；`npm run dev:api` | Vite 同源 `/api` 代理与 cookie；模型目录来自 `GET /models`，不修改前端实现 |
| M2 / A | `app.main.create_app(settings, *, repository, executor, catalog, intake, scoring, reporting)` | 复用路由、版本/确认、幂等、内存 repository 和进程内执行器 |
| M3 / C | SyntheticIntake 的异步对话/提取端口 | 合成档案固定，两份已知 JD 按原文选择各自 fixture；不推断任意材料。本装配未切换为 GatewayIntake 或真实文件解析 |
| M4 / D | ScoringService 的同步 assess_requirements / calculate_score | 真实 matcher-v1 / coverage-v1；原有 spy 检查每岗位确实调用，不在页面或编排层写死分数 |
| M5 / E | FakeModelDirectory / FakeModelGateway | 共享目录实例，提供明确 fake 模型和合成报告 |
| P1 报告 / A | GatewayReporting.generate_report | 将冻结快照与 M4 ScoreResult 传给 E 网关；复用 API-01 合成 Markdown 格式器，不是 #19 正式报告交付 |

`make dev` 使用 `app.integration:create_app`；`make dev-api-fakes` 保留 API-01 全替身基准。导入组合根不读配置、不联网，factory 拒绝 real 模式。OpenAPI、共享 DTO/端口、依赖锁文件、数据库与 B/C/D/E 源码不在本轮修改范围。

M2 在边界映射网关安全错误码，校对实际模型元信息与入队冻结映射。不可用模型入队前返回 422；执行前停用则 task failed，不换模型。报告失败时保留真实评分：item 为 score_only、聚合 task/diagnosis 为 partial；无任何评分时为 failed。

## 运行与独立双 JD 复现

后端版本以 `.python-version`、`backend/pyproject.toml`、`backend/uv.lock` 为准；前端以 `frontend/.nvmrc` 和 package.json 为准。本轮实际 Python 3.12.13、uv 0.11.15、Node 24.14.1、npm 11.11.0。使用合成资料，无需模型密钥或数据库，不覆盖私人配置。

在根目录启动：

```sh
uv python install 3.12.13
make setup
LLM_MODE=fake ALLOWED_ORIGINS='["http://127.0.0.1:5173"]' make dev
```

另开终端，在 frontend 目录使用该目录指定的 Node/npm：

```sh
npm ci
VITE_API_MODE=http VITE_PROCESSING_NOTICE='P1 演示数据：合成提取及 fake 模型，不向外部供应商传输资料；评分由 coverage-v1 计算。' npm run dev:api
```

打开 `http://127.0.0.1:5173`，接受告知，选择「对话整理」，提交以下规范合成经历，等待成功并确认档案最新版本：

```text
使用 Python 完成课程数据清洗项目。
了解 SQL 基本语法。
已获得计算机相关专业本科学位。
```

在岗位页分别提交并确认下面两份原文；不通过编辑第一份岗位伪造第二份提取成功。

第一份：

```text
必须有 Python 项目应用经验。
必须具备 SQL 应用能力。
熟悉 Docker 优先。
本科及以上学历优先。
```

第二份：

```text
平台运维合成岗位：必须具备 Kubernetes 应用能力。
```

两次提取均应 succeeded，产生不同 Job ID，各自 quote 属于各自原文，确认各自版本后同时选择两个岗位。通过后端目录选择 demo-model-b，开始诊断并读取分项结果：

- 第一岗位 score=66.7、unknown_weight_ratio=0.1667、skill=60、education=100，来源为 `docs/05-scoring.md` 的手算金标准。
- 第二岗位只有 Kubernetes 要求，档案没有相应证据，状态 unknown、score=0、unknown_weight_ratio=1；不能把它写成用户明确不具备。
- 两岗位均含局部要求 ID r1，但第一份 r1 为 Python / met / e1，第二份为 Kubernetes / unknown / 无证据。检查目标、状态和证据，不能仅按局部 r1 判断没有串用。
- 切换岗位显示各自要求和报告；切换为 demo-model-a 创建新诊断，评分不变，旧诊断的模型/版本/结果不变。导出为明确演示格式，包含每岗位 ID/版本、评分、规则、模型信息；P1 格式不承诺岗位标题。

原有手工把第二岗位改成 Docker 单要求的用例继续保留，覆盖用户编辑后确认版本；它与上述独立双输入验收分开，不再充当替代证据。

## 可控失败

停止自己启动的正常后端，再使用同一 Origin 配置启动失败工厂（重启清空内存，需要新建会话和合成资源）：

```sh
LLM_MODE=fake ALLOWED_ORIGINS='["http://127.0.0.1:5173"]' uv run --project backend --frozen uvicorn app.integration:create_report_failure_app --factory --host 127.0.0.1 --port 8000
```

该工厂在服务端注入 E 网关 invalid_json，用户输入不能激活故障开关。重新按双 JD 路线操作，应保留两个真实评分，报告为 score_only / MODEL_OUTPUT_INVALID，聚合 partial，错误可见且可导出。成功、partial、failed 都应停止页面任务轮询；离开页面也清理轮询。未知合成原文应到 failed，不新增或覆盖已有岗位。当前 C 的 IntakeError 在 M2 被泛化为安全的 INTERNAL_ERROR，页面显示通用失败提示；不能声称 UNKNOWN_SYNTHETIC_INPUT 已透传。此处验证终态、错误可见和不写半成品；正式提取接入时由 A/C 协调来源与错误映射，不为 P1 新增 HTTP 契约。超时、供应商不可用、单项评分失败和全评分失败另由集成测试注入验证。

## 验收条目 → 文件/证据 → 结果

本轮从同步提交的 tracked 源码导出全新目录，再叠加本轮具名测试补丁，不带 `.env`、私人指南或旧 venv。创建新 venv，按锁定依赖执行 make setup；前端在该目录以固定 Node/npm 和已准备缓存执行 npm ci。旧 Node 缓存的 npm 入口不完整，故在任务临时目录安装固定 npm 11.11.0，未改变全局安装或仓库依赖。

| 条目 | 文件/步骤 | 本轮结果 |
|---|---|---|
| 同步后先复现 | 原集成测试、main 含 #48，尚未修改 xfail | 6 passed / 1 failed，失败为 XPASS(strict)，与 D 指出的问题一致 |
| 独立双 JD、真实评分、模型/资源隔离与降级 | `backend/tests/platform/test_integration.py` | 8 passed，无 xfail。保留原手工编辑、真实 M4 spy、网关错误、单项/全项评分失败、模型停用覆盖；新增独立双 JD 全流程与未知输入失败 |
| 干净环境后端完整检查 | `PYTHONUTF8=0 make test contracts lint`；[clean-recheck.json](evidence/int-01/clean-recheck.json) | 343 passed；36 Schema / 4 样例 / 18 业务操作，pending=[]；Ruff check / format 通过（67 文件） |
| 干净环境前端检查 | frontend 下 `npm run types:check`、`npm run build`、`npm test` | 类型、构建通过；4 文件 / 29 tests passed；未改 B 源码或前端依赖 |
| 真实 HTTP 页面与目录来源 | clean-source 中实际 make dev / npm run dev:api；[browser-summary.json](evidence/int-01/browser-summary.json)、[models.json](evidence/int-01/models.json) | Playwright 操作对话、确认两份独立原文、模型选择及逐岗位报告；Vite 真实 HTTP 请求与后端日志对应，无 route stub，fake 标识可见 |
| 两岗位成功与换模型 | [two-jd-task.json](evidence/int-01/two-jd-task.json)、[two-jd-diagnosis.json](evidence/int-01/two-jd-diagnosis.json)、[two-jd-model-a-diagnosis.json](evidence/int-01/two-jd-model-a-diagnosis.json) | succeeded，66.7 / 0.0；Python r1=met/e1，Kubernetes r1=unknown/无证据；B→A 完整 ScoreResult 不变，实际下载 Markdown |
| 服务端可控报告失败 | [two-jd-report-failed-task.json](evidence/int-01/two-jd-report-failed-task.json)、[two-jd-report-failed-diagnosis.json](evidence/int-01/two-jd-report-failed-diagnosis.json) | 两 item 均 score_only / MODEL_OUTPUT_INVALID，task/diagnosis partial，保留两评分；错误可见且实际导出下载成功 |
| 未知合成 JD 失败 | [unknown-jd-task.json](evidence/int-01/unknown-jd-task.json)；页面显示处理失败 | failed / INTERNAL_ERROR、result=null；代码映射边界如上节，不声称支持任意 JD |
| 页面终态停止轮询 | browser-summary 的 terminal_polling；默认页面间隔 2 秒，原始请求列表仅留本机 | succeeded 隔 14.100 秒 GET 总数 3→3；partial 隔 11.547 秒 3→3；failed 隔 9.130 秒 2→2。计数含 StrictMode 已取消请求，已完成 200 请求也无增加；三个观察均超过两个轮询间隔 |
| 独立子代理复核 | 只读检查最终集成测试差异与实现入口；未改源码或发布外部内容 | 未发现实质问题，指出并纠正了新增导出断言超出现有 P1 格式的要求；不代替 D/E/B 的评审 |
| B 对修复版本复验、队友批准 | 下节引用的旧版复现和 D 修改请求不能代表新提交批准 | 待取得；不以本地/子代理记录冒充 B 本人验收 |

本轮浏览器使用本机缓存 Chromium 的单进程无头模式，避开缓存运行时 helper 崩溃；CLI wrapper 的 npx 元数据不完整，改用同一已安装 CLI。实际启动参数、下载文件大小与 SHA256 见 browser-summary，成功/partial 两次 Markdown 均已落盘。没有据此声称跨浏览器或 Windows 页面复验。正常与失败工厂由独立子代理实际启动并在结束后停止；原始截图/网络列表只留任务临时目录，不上传 cookie、header 或 storage state。根代理已复核成功、部分失败和输入失败截图，并对新增安全响应体执行 Schema、跨响应绑定及隐私检查。

## 队友证据与历史记录

- [B 的干净环境复现](https://github.com/Riverstar123/ResumeDoctor/pull/47#issuecomment-6186907779)针对旧提交 `ec07858`：页面经 Vite 真实 HTTP 跑通规范单岗位，第二份 Kubernetes JD 明确失败；未复现 #48 叠加组合或可控报告失败工厂。B 明确未同意合并。该证据已取得，修复后完整双岗位与失败流程仍需 B 再验。
- [D 的修改请求](https://github.com/Riverstar123/ResumeDoctor/pull/47#pullrequestreview-5529215968)要求消费 C 修复、移除严格 xfail 并保持原断言、重跑双 JD 与更新说明。本轮已处理实现和本地检查，仍需其复审处理原修改请求。指定 E/B 的最新 PR 批准也尚未取得，不虚构队友意见。
- 初轮 `ec07858` 的 272 passed / 1 xfailed 与实际浏览器失败记录保留为历史，不能作为本轮通过结果。`evidence/int-01/second-jd-failed-task.json` 是旧版合法第二 JD 的失败证据；`success-task.json`、`success-diagnosis.json` 与 `clean-api-smoke.json` 的双岗位使用手工修正 Docker 用例。旧报告失败文件也为初轮记录，不覆盖或重新标作本轮输出。

| 历史契约差异 | 消费者影响 | 当前处理 |
|---|---|---|
| C 原 SyntheticIntake 固定返回第一份 JD | 第二原文的 quote 与实际输入不一致，M2 拒绝 | C 在 #48 交付两个按规范原文选择的 fixture，已合入 main；本轮同步并转正验收，M2 未补写提取内容或绕过校验 |
| E 的 GatewayError 与 M2 异常形状不同 | 直接注入会丢安全错误码或使未知模型变 500 | GatewayCatalog / GatewayReporting 映射已有安全错误码并去掉内部异常原文，原回归保留 |
| API-01 / E 的模型元信息不同 | 目录与报告混装可能误记实际模型 | 共享一个 E 目录，校对报告返回与入队冻结映射，原回归保留 |

## 范围与收尾

P1 使用合成素材、fake 网关、内存 repository 和进程内执行器；真实确定性评分由 M4 提供。未交付数据库 worker、租约/崩溃恢复、真实文件解析、真实模型、正式 #19 报告或 #22 持久化联调。测试成功不等于所有后续阶段已完成。

PR 正文草稿见 [int-01-pr-draft.md](int-01-pr-draft.md)。本轮沿用既有提交/推送授权修复 #47，未自动发送 owner 评论、请求评审、合并或关闭 Issue，不开始下一张任务。`指南.md` 必须命中根 `/指南.md` 且未跟踪；提交前运行 git check-ignore、git ls-files、diff 与具名暂存检查，保留原 `.gitignore` 暂存/未暂存状态并排除业务提交。
