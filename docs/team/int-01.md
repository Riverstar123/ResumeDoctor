# INT-01 本地装配与验收记录

关联 [Issue #13](https://github.com/Riverstar123/ResumeDoctor/issues/13)，负责人 A；评审 E（`y1324-cyber`）、B（`junnnh26`），账号来源为根 README / CLAUDE.md 的团队映射。本记录日期为 2026-10-15（Asia/Shanghai）。

**状态：M2 装配已在本地实现，INT-01 尚未验收完成。** 两份不同 JD 的独立提取受 C 的固定合成端口限制；B 本人干净环境复现未取得。用户已授权提交、推送和创建 Draft PR；发布状态以 GitHub 实时记录为准。未单独发布 owner 通知或请求评审，未合并或关闭 Issue；不把正文中的交接要求视为队友已接单或已验收。

## 前置实核

本轮通过 GitHub 实时读取 Issue 正文、评论、关联 PR、PR 正文和 reviews，并用 HTTPS `git fetch origin` 更新跟踪引用。核查基线 `origin/main=ce142a13572ceb2d20848731d058f72cb26e95ad`。下表实际 merge commit 均通过 `git merge-base --is-ancestor <commit> origin/main`；同时读取 main 中交付文件的实际导出，未用源分支提交祖先关系代替合并核验。

| Issue / owner | 交付 PR / base | main 中实际 merge commit | 验收证据（来自链接 PR 的 reviews / 正文） |
|---|---|---|---|
| [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) / A | [#42](https://github.com/Riverstar123/ResumeDoctor/pull/42) / main，MERGED | `b99c037b1c09590bed7723d3df3bf60644e38b77` | D 对 `d64e5a1` APPROVED；Windows 锁定环境平台回归、契约与 lint 通过，范围为 fake API |
| [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9) / B | [#37](https://github.com/Riverstar123/ResumeDoctor/pull/37) / main，MERGED | `b318d202916e612aaad46fc9da97749bd0b469c7` | A 对 `1900c8b` APPROVED；构建、组件和 mock/HTTP stub 浏览器测试通过；Issue 有关闭验收评论 |
| [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) / C | [#44](https://github.com/Riverstar123/ResumeDoctor/pull/44) / main，MERGED | `b024b993dd42373043f876879987ed4acb1cb563` | D、A 对 `58d6592` APPROVED；纯校验、固定合成端口及与 main 组合测试通过，尚未声称独立多 JD 提取 |
| [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11) / D | [#39](https://github.com/Riverstar123/ResumeDoctor/pull/39) / main，MERGED | `7ae105a78e5bf85e0de3d6e1e52f131fb795cf20` | A APPROVED；手算、舍入、空分母、顺序与输入不可变验证通过 |
| [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12) / E | [#46](https://github.com/Riverstar123/ResumeDoctor/pull/46) / main，MERGED | `ce142a13572ceb2d20848731d058f72cb26e95ad` | A 对 `c1ddd49` APPROVED；Schema 边界与跨 M3 合成素材复审通过；HTTP 装配留给 #13 |

上表五项 Issue 当前 CLOSED，合并和验收另外核实，不以 CLOSED 推断交付。前置核查时 #13 OPEN、无关联交付 PR、无评论；搜索 INT-01 返回的 #44 是正文引用，不是 #13 的交付。

额外核实：[#18 / PR #40](https://github.com/Riverstar123/ResumeDoctor/pull/40) 已按 main 合并为 `c7c39d1bf225a11f07f1736d82de14f93c2df3d3`，A 对 `d678d87` APPROVED；因此可使用 D 的真实 matcher-v1，不需要在集成层模拟匹配。[#19](https://github.com/Riverstar123/ResumeDoctor/issues/19) 仍 OPEN、无交付 PR，报告/导出保留明确的 P1 合成范围。

起始工作区为 `codex/api-01@d64e5a1`，仅 `.gitignore` 有已暂存和未暂存的私人忽略规则；从上述最新 main 建立 `codex/int-01`，保留全部原修改，业务成果不纳入 `.gitignore`。未发现仓库或父目录中的额外 AGENTS.md，遵守用户提供的 AGENTS 指令。

## 导出与装配边界

| 模块 | 实际入口 / 签名 | 装配方式与限制 |
|---|---|---|
| M1 / B | `frontend/src/api/index.ts` 的 `ApiClient`；`npm run dev:api` | Vite 同源 `/api` 代理、cookie；目录来自 `GET /models`，不改前端实现 |
| M2 / A | `app.main.create_app(settings, *, repository, executor, catalog, intake, scoring, reporting)` | 复用原路由、内存 repository、版本/确认、幂等、进程内执行器；无数据库 worker |
| M3 / C | `SyntheticIntake` 的异步 `advance_conversation(..., *, context)`、`extract_job(raw_text, company_context, *, context)`；build_profile/extract_document 同共享端口 | 直接注入已交付类；固定素材，不调用网关，不推断用户输入；不是 IN-02 / IN-03 |
| M4 / D | `ScoringService.assess_requirements(profile_content, job_content, matcher_version)` 与 `calculate_score(assessments, rule_version)`，同步 | 直接调用真实 matcher-v1 / coverage-v1；spy 验证每岗位确实调用函数；不在页面或编排层写分数 |
| M5 / E | `FakeModelDirectory.list_models/resolve`，异步 `FakeModelGateway.generate_structured(..., *, context)` | 共享一个目录实例；`GatewayCatalog` 仅把 GatewayError 转成 M2 安全错误；不复制目录 |
| P1 报告 / A 装配 | `GatewayReporting.generate_report(...)` | 把冻结快照与 M4 ScoreResult 传给 E 网关，使用共享 ReportContent Schema；沿用 API-01 合成 Markdown 格式器；不是 #19 的正式报告模块 |

新增组合根 `backend/app/integration.py`，`make dev` 指向它；旧 `app.main:create_app` 留作 API-01 全替身基准，通过 `make dev-api-fakes` 启动。导入组合根不读配置、不联网；factory 仍拒绝 `LLM_MODE=real`。全部 HTTP DTO / OpenAPI 字段保持原样，不创建第二套 DTO。

网关错误在 M2 边界映射，保留 MODEL_UNAVAILABLE / MODEL_TIMEOUT / MODEL_OUTPUT_INVALID / PROVIDER_UNAVAILABLE / INPUT_TOO_LONG，丢弃异常原文。不可用模型入队前返回 422；执行前停用则 task failed，不换模型。报告调用的模型元信息必须匹配入队冻结映射，变化时明确失败。报告失败保留真实评分，item 为 score_only、诊断/task 为 partial；状态聚合沿用现有契约。

## 运行与页面复现

在干净源码目录，后端版本以 `.python-version`、`backend/pyproject.toml`、`backend/uv.lock` 为准，前端版本以 `frontend/.nvmrc` 和 `frontend/package.json` 为准。前端要求 Node 24.14.1 / npm 11.11.0，与根 `.nvmrc` 的 Node 版本不同。

后端（无需密钥/数据库；已有私人配置时不要覆盖）：

```sh
uv python install 3.12.13
make setup
LLM_MODE=fake ALLOWED_ORIGINS='["http://127.0.0.1:5173"]' make dev
```

另一个终端进入 `frontend`，先按该目录 `.nvmrc` 切换 Node：

```sh
npm ci
VITE_API_MODE=http VITE_PROCESSING_NOTICE='P1 演示数据：合成提取及 fake 模型，不向外部供应商传输资料；评分由 coverage-v1 计算。' npm run dev:api
```

打开 `http://127.0.0.1:5173`，接受处理告知，选择「对话整理」，提交以下 C 的规范合成经历，等待任务成功，核对档案草稿并确认最新版本：

```text
使用 Python 完成课程数据清洗项目。
了解 SQL 基本语法。
已获得计算机相关专业本科学位。
```

进入目标岗位页，提交 C 的规范 JD，等待提取完成，再确认：

```text
必须有 Python 项目应用经验。
必须具备 SQL 应用能力。
熟悉 Docker 优先。
本科及以上学历优先。
```

切换目录中的 demo-model-a/b，创建诊断，轮询终态后读取逐项结果。该规范样例的 66.7、unknown_weight_ratio=0.1667、skill=60、education=100 来自 `docs/05-scoring.md` 的手算金标准，服务实际调用 D 的函数；不是所有输入都应该得到此分数。

**必须单独重放的阻塞验收：** 第二份原文输入 `平台运维合成岗位：必须具备 Kubernetes 应用能力。`。当前提取任务 failed / VALIDATION_ERROR，无新 Job；界面显示错误，停止轮询。不得宣称两份不同原文的独立提取通过。

补充的后续链路验证（不替代上述验收）：再次提取规范合成草稿，通过页面手工把岗位名称改为「[演示数据] 手工修正 Docker 岗位」，删除 Python、SQL、学历要求，仅保留 Docker，保存新版本并确认。选择两个已确认岗位，选择 demo-model-b 开始诊断。实际页面为 66.7 与 0.0；切换第二岗位只显示 Docker 要求、unknown 与对应报告。API 测试还将第二岗位原文缩为 Docker 单句、ID 改为 docker-only，检查快照、报告引用及换模型后评分保持不变。

可控报告失败：停止正常后端，使用同一 Origin 配置启动下列工厂，重启清空内存，重新进入页面建立会话及规范档案/JD：

```sh
LLM_MODE=fake ALLOWED_ORIGINS='["http://127.0.0.1:5173"]' uv run --project backend --frozen uvicorn app.integration:create_report_failure_app --factory --host 127.0.0.1 --port 8000
```

此工厂在服务端注入 E 网关 `invalid_json`；材料中的文字不会触发故障控制。预期 report 两次尝试后 MODEL_OUTPUT_INVALID，item score_only、task partial，评分仍可读/导出。超时、供应商不可用、单岗位评分失败和全评分失败由集成测试分别注入。恢复正常工厂后再重建会话。

## 契约差异与 owner 交接草稿

| 项目 | 字段 / 来源 | 消费者影响与复现 | 最小修正 / owner / 状态 |
|---|---|---|---|
| 不同 JD 提取能力缺口 | `SyntheticIntake.extract_job(raw_text, company_context)` 固定返回 `synthetic_job_content()`，并用常量原文校验；来自 C 的 `backend/app/intake/synthetic.py` | 第二份 Kubernetes 原文得到第一份 JD 的 title/requirements/quote；M2 `validate_job(content, body.raw_text)` 拒绝，终态 failed / VALIDATION_ERROR。#13 明确要求两个不同 JD；AI 契约要求 quote 属于当前原文 | C（huih02427-cmyk）扩展可注入/按规范合成输入选择的双 fixture，保留原始 quote 和 company_context；未知输入明确失败。若改为消费 E 网关，需与 E 对齐第二 fixture。M2 不补写提取器、不绕过校验。**阻塞；待 C 接单，未单独通知** |
| 内部异常形状不同 | E 的 GatewayError.code；M2 原 task_error 只识别 PlatformError.info | 直接注入 E 目录，未知模型会变 500；报告失败会丢失具体码 | A 在 GatewayCatalog / GatewayReporting 映射，使用安全消息；本地已验证 |
| 模型元信息不同 | API-01 元信息为 api-01-fake-v1；E 为 synthetic-fake-v1 / report-v1 / fake-gateway-v1 | 目录和报告混装会造成历史模型信息不实 | A 使用同一个 E 目录，并校对返回元信息与冻结映射；本地已实现 |

给 C 的交接内容即第一行：补双合成 fixture，不要求接真实 AI。完成后删除严格 xfail 标记，重跑该验收、完整后端和本文实际页面。B 需亲自在其干净环境重复本节，提交系统/版本、命令、两份输入、响应和截图；目前未取得，不以 A 的浏览器记录替代 B。E/B 的 PR review 尚未请求或取得。

## 验收条目 → 文件/证据 → 结果

本轮本地初次旧 Python 和 uv 缓存文件不完整，启动/安装失败；随后在 `/private/tmp/resumedoctor-int01-python` 安装项目固定 Python，使用全新 uv 缓存与 venv 按锁文件重新安装成功。没有修复/替换旧环境，没有改变锁文件。环境覆写仅为隔离路径和网络配置，不含密钥。

| 条目 | 实际执行 / 证据 | 结果 |
|---|---|---|
| 装配、评分、降级、目录 | `backend/tests/platform/test_integration.py`；`uv run --project backend --frozen pytest -q backend/tests/platform/test_integration.py` | 6 passed、1 xfailed；通过项含真实函数调用、双快照手工修正、模型切换、三种网关错误、单项与全项失败、停用模型 |
| 完整回归 | `PYTHONUTF8=0 make test contracts lint`（本任务新 venv；UV_NO_CONFIG / UV_OFFLINE，完整安装后运行） | 272 passed、1 xfailed；36 Schema / 4 样例 / 18 操作、pending=[]；Ruff check / format 通过。xfail 是未完成验收，不是通过 |
| 前端已有工程回归 | frontend 下 Node 24.14.1 / npm 11.11.0；缓存安装 `npm ci --offline --ignore-scripts --no-audit --no-fund`，`npm run types:check`、`npm run build`、`npm test` | 类型与构建通过，29 tests passed；本轮未重复旧 mock/HTTP stub 浏览器套件 |
| 实际页面 / API 请求 | Playwright CLI；HTTP 模式页面从对话到确认再到岗位、模型选择与报告；浏览器 requests + 后端访问日志逐项对应 | 真实 POST/GET 到集成 API，无 network stub；fake 来源明显；规范得分与手工修正第二岗位独立；成功终态后请求清单两次比较相同 |
| 不同 JD 的失败 | `evidence/int-01/second-jd-failed-task.json`；浏览器错误快照与请求清单 | failed / VALIDATION_ERROR，错误可见；终态后请求清单两次比较相同，不无限轮询；独立提取验收阻塞 |
| 成功结果体 | `evidence/int-01/success-task.json`、`success-diagnosis.json` | task/diagnosis succeeded；model_id=demo-model-b；两个 item 成功；分数分别 66.7 / 0.0，证据仅合成资料 |
| 受控网关失败的页面 | 本文失败工厂；`evidence/int-01/report-failed-task.json`、`report-failed-diagnosis.json` | 真实页面 item score_only、task/diagnosis partial、MODEL_OUTPUT_INVALID；保留 66.7；终态后请求清单相同；点击导出实际 HTTP 200 并下载 Markdown |
| 干净源码目录复现 | `/private/tmp/resumedoctor-int01-clean-mbp9y4an`；main 源码快照叠加本任务具名文件；不复制私人配置/旧环境；新 venv 按锁文件 `make setup`，包与 npm 从已准备缓存安装 | 完整 `make test contracts lint` 为 272 passed / 1 xfailed，契约与 Ruff 通过；前端安装、types:check、build、29 tests 通过；实际 `make dev` / `npm run dev:api` 可启动；经 Vite 代理调用真实 TCP API 的完整规范/手工修正链、导出通过；不同 JD 仍明确失败。摘要见 `evidence/int-01/clean-api-smoke.json`。这是 A 的干净目录复现，不是 B 证据 |
| B 复现 / E、B review | 团队映射已核实；未发送远程消息或请求 | **待队友验证 / 待请求评审** |

浏览器原始快照、请求列表、合成截图位于本机 `/private/tmp/resumedoctor-int01-audit/`，不会上传 cookie/header/state；已提取的安全响应体保存到 `docs/team/evidence/int-01/`。favicon.ico 的 404 是本轮浏览器控制台唯一资源错误，不影响业务；未接管 B 的静态资源修复。

## 范围与收尾

P1 合成素材与 fake 网关、进程内内存执行；不交付数据库、租约/崩溃恢复、真实文件解析、真实模型、正式 #19 报告/导出或 #22 持久化全链路。评分是真实确定性算法，报告只是合成解释。当前严格 xfail、B 复现和评审均未完成，不可合并验收或关闭 #13。PR 模板草稿见 [int-01-pr-draft.md](int-01-pr-draft.md)。

私人 `指南.md` 保持 `/指南.md` 忽略；提交前检查 `git check-ignore -v -- 指南.md`、`git ls-files -- 指南.md` 和具名暂存清单。原 `.gitignore` 修改保持独立，禁止纳入业务 PR。用户本轮已授权提交、推送和创建 PR；发布 owner 评论、请求评审及合并仍未执行。本轮不开始下一张 Issue。提交检查须确保指南命中根忽略规则且未跟踪；原有已暂存 `.gitignore` 保持原状，本任务使用具名文件提交，明确排除原有暂存项。
