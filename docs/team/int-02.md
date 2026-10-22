# INT-02：真实业务模块与持久化全链路联调

日期：2026-10-23（Asia/Shanghai）。任务：[Issue #22](https://github.com/Riverstar123/ResumeDoctor/issues/22)。负责人 A；评审 B / junnnh26、E / y1324-cyber。本文记录本地实测，不代表队友验收、已发布 PR、合并或 Issue 关闭。

## 前置核验与本轮边界

从 `origin/main=b0fda8e529046be00e67b211599aed2d193a4e08` 建立独立 `codex/int-02`，原 `codex/job-01` 工作区的暂存/未暂存 `.gitignore` 均保留。下列 PR 的 base 均为 main，GitHub 实时返回 MERGED，实际 squash merge commit 均在 origin/main 祖先链上；未用源分支提交是否在祖先链作为判断。

| Issue / owner | 交付 PR（base main） | 已合入 main 的 merge commit | 验收证据与当前边界 |
|---|---|---|---|
| [#15](https://github.com/Riverstar123/ResumeDoctor/issues/15) / A | [#51](https://github.com/Riverstar123/ResumeDoctor/pull/51) | d61f2175ca3bc030e956c5b5d00a8847fda89d5f | D/E 模块评审；[PostgreSQL/worker 记录](job-01.md)；Issue CLOSED |
| [#17](https://github.com/Riverstar123/ResumeDoctor/issues/17) / C | [#49](https://github.com/Riverstar123/ResumeDoctor/pull/49) | 5d0c8539b90ed942cc4cc4dd5482206343b22ea7 | A/D 模块评审；[维护者明确接受 DOCX 页数例外并要求提示](https://github.com/Riverstar123/ResumeDoctor/issues/17#issuecomment-6285725068)；Issue OPEN |
| [#18](https://github.com/Riverstar123/ResumeDoctor/issues/18) / D | [#40](https://github.com/Riverstar123/ResumeDoctor/pull/40) | c7c39d1bf225a11f07f1736d82de14f93c2df3d3 | A 对最终修复版本批准，评分与条件引用回归见 PR；Issue CLOSED |
| [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19) / E | [#52](https://github.com/Riverstar123/ResumeDoctor/pull/52) | 0d8b7b52c44230f2702802a4ded5ea3175560c60 | A/D 对 RP-01 最终版本批准；Issue OPEN |
| [#21](https://github.com/Riverstar123/ResumeDoctor/issues/21) / B | [#37](https://github.com/Riverstar123/ResumeDoctor/pull/37)、[#45](https://github.com/Riverstar123/ResumeDoctor/pull/45) | b318d202916e612aaad46fc9da97749bd0b469c7；195ad5ae6c56d413ae798e1018dc61a56611cc6e | 页面模块交付与 fake HTTP 验收见 [记录](https://github.com/Riverstar123/ResumeDoctor/issues/21#issuecomment-6138708767)；正式业务服务补验此前待 A 装配；Issue OPEN |

用户本轮明确授权：按“模块代码与模块级验收已交付”开工，将 #21 剩余真实业务服务/网页联调纳入 #22。没有把 OPEN 自动当成未交付，也没有把旧 mock 验收冒充正式服务验证。

## 替身盘点和实际装配

| 端口/环节 | 旧默认 | INT-02 默认 / 文件 |
|---|---|---|
| HTTP 持久化 | 内存 INT-01 与 DB-01 双入口 | `make dev` / `make dev-database` 均为 `app.database:create_app`，PostgreSQLRepository |
| 后台任务 | API 内存执行器或 JOB-01 synthetic worker | 独立 `python -m app.platform.jobs`，原租约/续约/fencing 不变 |
| 文件与提取 | SyntheticIntake / FakeIntake | C 的 GatewayIntake + DocumentExtractor；每任务绑定实际 document_id / message_id，文档定位交给 C helper |
| 匹配与评分 | FakeScoring / 部分入口 ScoringService | D 的 ScoringService，冻结版本与评分持久化 |
| 报告 | GatewayReporting / FakeReporting | E 的 ReportService，保留元信息和语义验证，逐岗位失败保留评分 |
| Markdown | FakeReporting | E 的 Markdown renderer，只读取 DiagnosisItem 保存结果，不重新评分 |
| 模型 | M5 固定来源/单份 JD fake 输出 | IntegrationFakeGateway：登记素材的模型 fake，继承 M5 超时/重试/schema/目录机制；报告仍用 M5 fake 输出 |
| 网页 | `npm run dev` 的页面 mock | `npm run dev:api`；实际 HTTP、匿名 cookie，无浏览器路由 mock |

API/worker 共用 `app.runtime.business_modules` 和 Settings（同一 backend/.env / DATABASE_URL / UPLOAD_DIR / 源码版本）。API 不自动迁移、不启动内存队列。历史替身只保留在显式 `make dev-synthetic` / `make dev-api-fakes` 和单元测试。

fake 模型**仅接受登记的合成原文**，不接受任意真实简历或任意 JD。未登记输入明确 MODEL_OUTPUT_INVALID，不返回另一份材料的固定事实。空白标准化只用于登记素材匹配；真实 quote/source 校验仍由 C 执行。每次返回独立对象，来源编号取本轮持久任务；不把固定 UUID 发送给新会话，也不宣称 T22 或真实模型效果。

## 共享契约冲突与最小修正

1. **解析 warnings 丢失**：C 的 `ExtractedDocument.warnings` 与 #17 的验收例外要求持久化并显示；原 OpenAPI TaskResult 没有对应字段。新增可选 `TaskResult.warnings: string[]`（最多 20 条，缺省空），保存模块固定提示字符串（稳定代码前缀加说明），并同步 Python DTO、OpenAPI、前端生成类型。存入现有 task.result JSONB，与档案提交同事务，无迁移。没有塞入 overview/quote/assistant_message。消费者：M2 / B / C / E；**待 B/E 评审，B 页面展示未完成**。
2. **本轮消息 ID 不可用**：旧 worker 到提交时才生成 Message.id。现在 HTTP 入队冻结 message_id，worker 提取使用它，提交消息也复用它。兼容旧队列：缺省使用 task_id 作为本轮 Message.id，仍与实际保存消息一致；不修改内部端口签名。
3. **人工编辑可伪造来源**：旧 POST/PUT 可把 arbitrary quote/source_id 标成 document/message。新建人工档案仅 manual；人工 PUT 对基准版本已有的 document/message 证据只能原样保留或删除，纠正用新 manual ID，不能改原文/来源/定位。PostgreSQL 在版本锁和冲突检查后校验，后台受租约保护的可信 M3 提交仍可新增来源。违规 422 VALIDATION_ERROR；不重读已删除原件。
4. **真实文件错误码**：worker 安全白名单补充 FILE_TOO_LARGE / UNSUPPORTED_FILE_TYPE，仍固定中文消息、空 details，不透传异常原文或路径。

## 可复现运行

按 README 配置私有 backend/.env（只补字段，不覆盖已有配置），使用 Python 3.12.13、uv 0.11.15、PostgreSQL 17.11。以下入口来自实际 Makefile：

```sh
uv sync --project backend --locked --extra database
# 设置 DATABASE_URL、同一个绝对 UPLOAD_DIR，LLM_MODE=fake；目标为自己的空库
make migrate
make dev
# 另一终端，配置相同
make worker
```

前端使用 `frontend/.nvmrc` 的 Node 24.14.1：

```sh
cd frontend
npm ci
VITE_PROCESSING_NOTICE='本地合成演示：真实解析与数据库持久化；模型为 fake，不向外部供应商发送资料。仅使用登记合成素材。' npm run dev:api
```

浏览器打开 `http://localhost:5173`（默认 ALLOWED_ORIGINS）。使用 127.0.0.1 时必须先把对应固定 origin 加入配置；本轮曾因 127.0.0.1 未允许得到预期 403，改用 localhost 后完成流程，未放宽来源校验。

生成真实可解析的合成文件和登记 JD（未提交二进制简历）：

```sh
cd backend
uv run --frozen python -m tests.platform.int02_fixtures --output /tmp/rd-int02-fixtures
```

输出 synthetic-resume.pdf（三页文字）、synthetic-resume.docx（三段正文）、source.txt 与 jd-1.txt 至 jd-5.txt。上传选择对应文件；对话可先发送 source.txt 第一句，再发送全文。JD 逐个粘贴登记文本，检查/确认后再诊断；不是通用真实模型提取演示。

## 已执行自动化验证

本轮使用新建专用 PostgreSQL 容器，浏览器库与 suite_test 库分离，避免外部 worker 抢走测试队列；不使用 SQLite、不 truncate 共享数据。测试会话由 fixture 创建并撤销。锁文件没有变化。uv 用户级镜像最初导致下载/锁检查失败，实际成功入口为 `uv --no-config sync --project backend --locked --extra database`，没有改动用户全局配置。

实际验证通过：

- 全量后端（含真实 PostgreSQL）：`RD_TEST_DATABASE_URL=<已迁移专用临时库> backend/.venv/bin/python -m pytest -q` → **719 passed**（最终全量，28.89s）。
- 移除持久平台最后一处默认占位导出后，重跑 test_postgres / test_jobs / test_int02 → **69 passed**；补充六个独立 JD 后 test_int02 单文件 **13 passed**（包含六个实际提取并确认的不同 ID，422 且数据库/模型调用计数不变）。
- `python -m app.tools.check_contracts` → **36 schemas / 4 examples / 18 业务路由，pending=[]**。逐响应由 `test_api.check` 按 OpenAPI 验证字段/错误 envelope；不是只检查成功码。
- Ruff check 全部通过；format check **109 文件**通过（含新增素材生成入口）。
- 前端 `types:generate` / `types:check`、build、format:check 通过；`npm test` → **29 passed**。没有把旧 mock 浏览器回归计为本轮真实服务验证。
- `python -m tests.platform.int02_fixtures --output ...` 实际运行成功。

## 验收条目 → 文件/证据 → 结果

| 条目 | 文件或实测证据 | 结果及边界 |
|---|---|---|
| T01 | test_int02 上传组合；实际网页 PDF 五岗位；C 文档模块测试 | PDF/DOCX 真字节解析，真实来源与 page/paragraph 定位通过；**DOCX 页数提示后端保存通过，网页展示待 B** |
| T02 | test_int02 `test_t02_scan_and_disguised_file_never_create_profile`；test_api 上传限额 | 无文本 PDF → NO_TEXT_LAYER，伪文件 415 或后台解析错误，无档案版本；大小限制 413；通过 |
| T03 | test_int02 对话组合；实际网页两轮对话 | v1 空档案 → v2/v3，证据 source_id 属于实际用户消息；不采纳助手为来源；通过 |
| T04 | test_int02 编辑/冻结；test_postgres / test_jobs 并发冲突；test_profile_sources | 人工 PUT 409、后台 VERSION_CONFLICT 无覆盖；新版本需重新确认；原证据不可篡改；通过 |
| T05 | test_int02 上传/对话 × 1/5 JD；test_demo_gateway 可变状态隔离；网页上传5/对话1 | 评分与建议绑定各自冻结快照；五份分数 66.7/0/100/50/0；通过 |
| T06 | test_int02 空 JD、全忽略、第六个岗位数量限制 | 六个实际提取并确认的不同 ID 返回422，未生成半成品诊断；通过 |
| T07 | 本轮全量中的 M4 评分基准测试；网页第一岗位与 Markdown | 66.7 / unknown 0.1667 / 类别 60与100，页面与导出一致；通过 |
| T08–T10 | 本轮全量中的 C/D 单元与跨模块用例；test_int02 的 partial/unknown | 模块回归通过；未声称将全部复杂日期/在读/冲突组合逐一经网页重跑 |
| T11 | test_int02 SelectiveReportFailure；M5 网关单元用例 | MODEL_TIMEOUT / 非法 JSON / provider 不可用，重试预算与 score_only 保分；通过，未调用真实供应商429 |
| T12 | test_int02 `test_t11_t12_partial_keeps_stored_score_and_foreign_export_hidden` | 同诊断一岗报告失败、另一岗成功，partial 可读/导出，标注报告失败；通过；未做网页失败注入 |
| T13 | 本轮 test_api / test_postgres / test_postgres_concurrency | 幂等同键返回同资源，不同内容409；并发和失败回滚通过 |
| T14 | 本轮 test_jobs 独立进程崩溃/领取/接管/旧token用例 | 真实 PostgreSQL 进程恢复通过；没有把同进程手动 run_once 当成进程证据 |
| T15 | test_int02 / test_profile_sources / test_api 全拥有权路由参数化 | 跨会话 GET/PUT/confirm/chat/diagnose/task/export 404，缺 cookie401；通过 |
| T16 | test_int02 真实报告调用暂停后撤销；test_jobs worker同步点撤销 | 无重新写回、cookie无效、原件进入清理；通过 |
| T23 | 两条网页实际下载/刷新；API/worker 重启；编辑后旧报告再次下载 | 页面/Markdown/保存分数与版本一致；冻结导出字节不变；通过 |
| T19/T20/T21 | 本轮原有模型目录/快照/禁用及评分测试 | 模块回归通过；本轮没有单独进行多模型切换的网页复验 |
| T22 | 无 | **未执行，真实 AI 不在本轮范围** |

## 全部 HTTP 路由核查

18 个业务方法/路径均由 compare_routes 检查无缺漏；路径/字段/状态声明与 OpenAPI 对照。API01 的参数化错误测试与本轮 PostgreSQL 业务集成一起运行。下表仅列实际用例，不声称每个路径的所有组合已做全排列：

| 方法与路径（省略 /api/v1） | 覆盖证据 |
|---|---|
| POST /session；DELETE /session；GET /models | test_api：成功、cookie、过期/撤销、403来源；test_int02：两会话与任务中撤销 |
| POST /documents | test_int02：202队列→真实解析成功/失败；test_api：415伪类型、413超限、422模型、幂等 |
| POST /profiles；GET /profiles/{id}；PUT /profiles/{id}；POST /profiles/{id}/confirm | test_int02：201/200、新版本、409冲突、404引用/隔离；test_profile_sources：422伪造来源、事务无副作用 |
| POST /profiles/{id}/messages；GET /profiles/{id}/messages | test_int02：202→v2/v3，真实消息列表及历史来源；test_api：404/401、409、请求格式校验 |
| POST /jobs；GET /jobs/{id}；PUT /jobs/{id}；POST /jobs/{id}/confirm | test_int02：真实5JD、200/202、空422、版本确认/新版本与404；test_api：业务校验和拥有权 |
| GET /tasks/{id} | test_int02：queued/running/终态、失败码；test_api：404/401 |
| POST /diagnoses；GET /diagnoses/{id} | test_int02：202、1/5、partial/failed、无效引用404、未确认422、全忽略/超数量422 |
| GET /diagnoses/{id}/export | test_int02：200 Markdown含保存评分；处理中/全无分409；partial可导出；跨会话404；网页实际下载 |

## 实际网页与进程证据

前端 Node 24.14.1，HTTP模式；浏览器 Microsoft Edge，经 Playwright CLI 技能操作，未注入任何 HTTP route mock；API 和 worker 是两个独立进程，均连接专用 PostgreSQL。只有合成材料，页面显示 fake 演示标识。

- 上传文字 PDF，档案 `4bfc40d6-fa8f-4821-abfc-c51b64fe6259` v1，来源 document `f2601a6c-a701-47aa-8f7c-d312eb910d0d`，三条证据定位 page:1/2/3。五岗位诊断 `c9eb4dfa-4654-4e51-9c76-89b89a2a197e` succeeded，页面 66.7/0/100/50/0；刷新和下载成功。
- 隔离浏览器对话会话：档案 `558fe425-326b-417c-9fcf-3ca5e9768695` v3，单 Python JD v1；诊断 `b60a2ab2-0812-4399-a84c-45bb9eca3169` succeeded，100分；刷新和下载成功。
- API/worker 停止并用相同配置重启，第一份五岗位报告继续读取；两次导出字节相同，SHA256 `d98f8afccae8d5813956d7dea7ba9b7ce71e3677500f56ed9a24b46331fae78a`。
- 网页人工修改档案概述到 v4、JD标题到 v2，重新确认并诊断；新诊断 `58d2134e-e3d5-4c7d-bb90-20df109be64b` 绑定 v4/v2。重新打开旧报告仍为 v3/v1，旧导出字节相同，SHA256 `d12687393a362398ccb41e6d7bfbfea29538d0fa8a1a9a1ad6f2381e6fcda3f7`。
- 另用网页上传 DOCX 成功创建档案 `42020395-8c10-45f9-842f-99cf5cbf412f` v1；已保存文档定位，但页面没有显示分页提示，截图 docx-warning-pending.png 供 B 修复复验。
- 本地截图与下载摘要在工作树 `output/playwright/`（未加入提交）：upload-five.png、upload-five-restarted.png、chat-one.png、chat-rediagnosed.png、chat-old-frozen.png、evidence.json。URL/UUID 是本轮运行得到的证据，不能复制到另一个会话当输入。
- 浏览器控制台仅观察到默认 favicon.ico 404；没有把它报告成业务失败或修前端无关资源。

## 尚未完成与收尾

- **B / junnnh26：DOCX 提示 UI**。TaskProgress 完成后当前直接导航 ProfilePage，未消费 warnings；需显示 `DOCX_PAGINATION_UNVERIFIED`（必要时连同其他 M3 提示），刷新/导航后仍可见。后端 task result 已持久化；选择合适 UI 保存方式由 B 实施，A 不重写页面。当前不能认定 T01 的完整 DOCX提示验收或 #21 的全部验收完成。
- **B/E：共享字段与来源编辑规则评审**。只有生成类型同步，无 UI 业务逻辑变更；需说明允许用户删除原证据并添加新 manual ID 更正。
- **B/E：独立复验与 #22 PR 评审**；本地实现与测试已完成，以草稿 PR 交付；B/E 尚未完成独立验收，未合并，Issue #22 仍 OPEN。评审请求状态以 GitHub 为准，角色字母不是账号。
- 不自动做下一 Issue，不调用真实模型，不关闭前置 #17/#19/#21，不以本地实测冒充队友意见。
