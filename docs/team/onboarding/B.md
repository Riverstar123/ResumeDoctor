# B：M1 Web 前端协作演练

对应 [Issue #3](https://github.com/Riverstar123/ResumeDoctor/issues/3)。本人 GitHub 账号为 [junnnh26](https://github.com/junnnh26)。按[团队计划的成员与职责表](../../04-team-plan.md#成员与职责)，M1 的第一评审人是 **E**，M2 是 HTTP 对接方这一点不改变评审归属；**A** 补充接口层评审并协调合并。E 的可核实 GitHub 账号需要 E 本人提供后补入，本文不代填。本记录说明我对职责、调用关系和验证方法的理解，**本次 PR 不含任何应用代码**。

`main` 上目前只有文档与契约，没有 `frontend/`、`backend/` 或任何应用服务。下面的 HTTP 行为、页面行为和测试命令均为设计预期与未来核对方法；`docs/examples/*.json` 可以现在读取，但不是运行成功证据。阶段与分工依据：[项目基线](../../00-decisions.md)、[团队计划](../../04-team-plan.md)、[任务索引](../backlog.md)、[M1 模块说明](../../modules/M1-web.md)。

## 当前依赖状态（开工前核查）

| 项 | 结论 |
|---|---|
| 我的演练 #3 | 本文件即成果；尚需真实评审、反馈处理与合并 |
| [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) SET-01 公共工程 | **未合并**：`main` 上没有任何工程文件 |
| [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9) WEB-01 前置 | 前置为 #7，按依赖表**未满足** |
| 演练本身 | 只做演练与准备，不写应用代码 |

[开发环境约定](../../08-development.md#必须提供的入口)把“前端 dev/build/test”列为我（B）的交付入口，“工程及实际命令由 SET-01、WEB-01 交付”。因此在 #7 提供公共工程与共享 DTO、验证入口之前，按依赖表前端工程不该由我抢先建立。

## 演练之后的实际情况（必须说明）

演练完成后，用户明确授权**提前**建前端工程。因此本地已有一份尚未提交的 `frontend/`（React 19 + Vite 8 + TypeScript 7，9 个页面，34 个测试用例；`npm run typecheck`、`npm run test`、`npm run build` 均通过）。本次 PR 不包含它，所以 `main` 与 #7 的依赖关系没有变化。

这样做偏离了依赖表，必须如实记录并承担后果：等 SET-01 合并后，需要对齐它的工程布局与共享 DTO，并把前端从 `mockApi` 切到 `httpApi`、改为消费 M2 的 HTTP 接口。**层次要说清**：`mockApi.ts` 是 M1 里 HTTP 客户端的替身；E 的 `FakeModelGateway`（#12）是服务端 M5 的内部端口，由 M2/M3/M5 在服务端注入，不是前端 API 层的替代品。做法上已经把返工面收在两个文件里——页面只依赖 `ResumeDoctorApi` 接口，`httpApi.ts` 与 `mockApi.ts` 各实现一份。细节与已知限制见该目录的 `README.md`（其中明确写了 mock 的分数是合成数据，不是评分实现）。

## 我接收什么、交付什么

M1 是求职者唯一直接接触的界面层。我从 M2 接收 HTTP 契约与资源，字段、路径、必填项、状态码与枚举**只以 [OpenAPI](../../api/openapi.json)（OpenAPI 3.1.0 / 契约版本 0.1.0，server `/api/v1`；按 `paths` 下的 HTTP 方法计数为 18 个操作）为准**，[API 说明](../../api/README.md) 补充业务校验；我不另造 HTTP 字段，也不改数据库。

我交付：完整页面流程、统一 API 客户端（含 cookie 会话、`Idempotency-Key`、`base_version`、错误归一化）、加载/空/错误状态、逐岗位报告与 Markdown 下载、组件测试与端到端操作。接口未完成时用 mock，mock 形状必须与服务端契约一致。

我的边界：**不计算真实评分**（分数只显示 M4 返回的 `ScoreResult`）、**不直接请求模型**（`model_id` 只是提交给服务端的字符串，前端不持有密钥或供应商 URL）、**不自行定义字段**、**不直接改数据库**。

| 角色 | 其主责 | 我的配合与边界 |
|---|---|---|
| A / M2 | 会话、任务受理与轮询、资源版本、导出路由 | 我用其 HTTP 接口；不绕过它直连业务模块 |
| C / M3 | 文件解析、对话建档、JD 提取 | C 解释档案/JD 哪些字段可编辑、追问语义；我只渲染与提交 |
| D / M4 | 要求匹配与确定性评分 | D 解释 `status`/`coefficient`/`weight` 与 unknown 语义；我只展示，不改分 |
| E / M5 | 模型目录、报告生成与 Markdown | E 提供报告示例与模型能力字段；我只展示 `ModelList` 与 `ReportContent` |

## 一次用户流程在前端怎样走

流程依据 [PRD 用户主流程](../../01-requirements.md)、[API](../../api/README.md) 与 [合成样例演练](../../examples/README.md)。页面与状态清单见 PRD 的“页面与状态”。前端不把 HTTP 202 或轮询 200 当作业务成功，必须读 `task.status`。

1. **会话与告知页**：`POST /api/v1/session`，body `consent_version="v1"`；同意模型处理说明后才允许上传/对话。响应设置 HttpOnly `rd_session`，前端拿不到也不该读 cookie 内容。
2. **模型选择**：`GET /api/v1/models` → `ModelList{default_model_id, items[]}`；按 `Model.capabilities` 筛选下拉项，用户不输入密钥。切换只影响之后提交的任务。
3. **输入页（两条路线）**：上传 `POST /api/v1/documents`（multipart `file`+`model_id`），或对话 `POST /api/v1/profiles`（手动建空草稿）后 `POST /api/v1/profiles/{id}/messages`。两者都返回 `TaskAccepted{task_id}`。
4. **任务轮询**：约每 2 秒 `GET /api/v1/tasks/{task_id}`，`status ∈ queued/running/succeeded/partial/failed`，终态停止，离开页面停止计时，429 尊重 `Retry-After`。成功后按 `result.resource_type`（`profile`/`job`/`diagnosis`）、`resource_id`、`version` 取内容；对话另有 `assistant_message`。
5. **档案页**：编辑后 `PUT /api/v1/profiles/{id}`（`base_version`+`content`）生成新版本，再 `POST /api/v1/profiles/{id}/confirm`（body `{version}`，仅允许 latest）。未确认版本不得进入诊断。
6. **岗位页**：`POST /api/v1/jobs`（`raw_text`≤20,000 字符、`company_context` 可空、`model_id`）→ 轮询 → 核对/编辑要求再 `confirm`；一次 1–5 个 JD，公司信息只作背景。
7. **诊断进度页**：`POST /api/v1/diagnoses`（body `DiagnosisCreate{profile,jobs,model_id}`）返回 `DiagnosisAccepted{task_id, diagnosis_id}`；轮询任务同时可 `GET /api/v1/diagnoses/{id}` 看逐岗位 `items[]`。
8. **报告页**：逐岗位显示 `score_result.score`、`unknown_weight_ratio`、`dimensions[]`、`assessments[]`、`report{gaps,suggestions,actions}` 与 `model_metadata`；终态可 `GET /api/v1/diagnoses/{id}/export` 下载 Markdown。

写请求约定：**所有 `POST` 除 `/session` 与 `{id}/confirm` 外必须带 `Idempotency-Key`**（16–128 字符随机）。契约里明确要求该头的是 `POST /profiles`、`/documents`、`/profiles/{id}/messages`、`/jobs`、`/diagnoses` 五项；网络重试沿用原 key，用户主动重新诊断换新 key。`PUT` 用 `base_version` 防覆盖、**不需要**该头；`DELETE /session` 同样不需要。

## 页面清单与验收对应

| # | 页面 | 主要接口 | 关键状态 | 相关验收 |
|---|---|---|---|---|
| 1 | 会话/告知 + 输入页 | `POST /session`、`GET /models`、`POST /documents`、`POST /profiles` | 格式与大小限制提示、解析失败可改走对话 | T01、T02 |
| 2 | 对话页 | `POST/GET /profiles/{id}/messages` | 一轮一轮、每轮追问≤3、失败轮可重试不伪装成功 | T03 |
| 3 | 档案页 | `GET/PUT /profiles/{id}`、`/confirm` | 结构化编辑、原文证据、unknown 与 unmet 区分、版本与确认、409 | T03、T04、T08 |
| 4 | 岗位页 | `POST /jobs`、`GET/PUT /jobs/{id}`、`/confirm` | 1–5 个 JD、要求编辑与确认、第六个 JD 拦截 | T05、T06 |
| 5 | 诊断进度页 | `POST /diagnoses`、`GET /tasks/{id}` | queued/running/succeeded/partial/failed、逐岗位 pending→scoring→reporting | T11、T12 |
| 6 | 报告页 | `GET /diagnoses/{id}`、`/export` | 总分/分类分解/要求明细/差距/建议/行动计划、score_only 降级 | T05、T12、T23 |
| 7 | 多模型对比 | 同快照换 `model_id` 重诊断 | 列出后端模型、记录实际模型、不改旧任务 | T19 |
| 全局 | 状态与错误 | 任意 | 加载/空/重试/401/404/409/429 | T15、T23 |

## 合成成功样例：前端该渲染成什么

资料来源：[样例说明](../../examples/README.md)、[profile.json](../../examples/profile.json)、[job.json](../../examples/job.json)、[diagnosis-request.json](../../examples/diagnosis-request.json)、[diagnosis-item.json](../../examples/diagnosis-item.json)。全部虚构；示例 UUID 不是服务端已有资源，`demo-model-a` 也不代表已接入的供应商。

现在可做的文档核对（前端渲染契约）：[diagnosis-item.json](../../examples/diagnosis-item.json) 里 `status="succeeded"`，页面必须**同时**显示 `score_result`、`report`、`model_metadata` 且 `error=null`；`score=66.7`、`unknown_weight_ratio=0.1667`、`dimensions` 为 skill 60.0 与 education 100.0。四条 `assessments` 的 `requirement_id` 为 `r1/r2/r3/r4`，状态分别是 `met/partial/unknown/met`——页面必须把 **`unknown`（r3 Docker）显示为“缺少证据”，不能显示成“不满足”`unmet`**。`report.gaps` 只引用 `r2/r3`，`suggestions[0].requires_user_input=true` 表示改写含 `[真实项目名称]` 占位符，页面不能当成已确认事实。`model_metadata.provider="fake"` 必须标明是合成/演示数据。

已经做过的（仅前端 mock 模式，本地）：在未提交的 `frontend/` 里用内置合成数据验证过上面的渲染契约——`npm run test` 34 个用例通过，其中报告页对同样的合成输入显示 66.7、未知权重 16.7%、技能 60.0、学历 100.0，r3 Docker 显示“缺少证据”而非“不满足”，`requires_user_input=true` 标注为待填写占位符，`provider=fake` 标注为演示数据。**这是前端替身的证据，不是后端或真实模型的证据。**

还没有做过的（需要真实服务，本轮确实未执行）：

1. 启动会话、选 fake 模型，走对话路线得到档案草稿，轮询成功后核对档案 ID 与 version，编辑并确认。
2. 提交 `job.json` 的 JD 原文与公司背景，轮询后核对/编辑/确认岗位要求。
3. 按 `diagnosis-request.json` 结构提交诊断，ID 与 version 换成实际值、换新幂等键。
4. 轮询到终态，核对报告页显示的 `profile.id/version` 与 `items[].job.id/version` 与请求的确认版本一致；fake 成功样例预期任务与岗位项均 `succeeded`。
5. 核对页面上的 66.7 / 60.0 / 100.0 与四个状态，且导出 Markdown 与页面信息一致。

mock 通过不代表契约已对齐：FastAPI 生成的契约必须与 [openapi.json](../../api/openapi.json) 比对（见[契约更改](../../api/README.md#契约更改)）。在 M2 的 HTTP 服务与 M5 的网关合并之前，不能写成“前端测试已通过”或“接口已通过”。

## 失败样例：另一个岗位失败与页面降级

本例对应 [T12](../../07-testing.md) 与 [DiagnosisItem 状态不变量](../../api/README.md#schema-之外的业务校验)：一个 JD 报告生成失败、另一个成功时，`Diagnosis.status="partial"`；成功的岗位项为 `succeeded`（有 `score_result`+`report`+`model_metadata`，`error=null`），失败的岗位项为 `score_only`（有 `score_result`、`report=null`、具体 `error`）。

服务实现后按以下方法检查（本轮未发起应用请求）：

1. 用两个 JD 创建诊断，使其中一个的模型调用失败（fake 模式下按 E 提供的开关触发映射，或按 A 的任务超时规则制造）；`POST /diagnoses` 只核对返回 `202` 与 `task_id`/`diagnosis_id`，**不能据此判断成功**。
2. 轮询 `GET /tasks/{id}` 到 `partial`；打开报告页，核对失败岗位**仍显示确定性分数**而非空白，页面上写明报告失败原因与 `error.code`，并提供重试或导出入口。
3. `GET /diagnoses/{id}/export` 在 `partial` 应能导出已完成评分并标注报告失败；在 `running` 应返回 `409`。页面据此禁用导出按钮并给出说明。
4. 另测三条错误路径：无有效 cookie 时 `401 SESSION_EXPIRED`（提示会话过期，不假装资料仍在）；访问其他会话资源 `404 RESOURCE_NOT_FOUND`（不区分“不存在”与“他人的”，页面不泄漏归属）；`PUT` 用过期 `base_version` 得 `409 VERSION_CONFLICT`，页面提示刷新后重 GET 核对，不盲目覆盖。

## 合并前两项检查

1. **契约与验证证据**：逐项对照 OpenAPI 的路径/字段/状态码枚举、`Idempotency-Key` 与 `base_version` 规则、`Task`/`DiagnosisItem` 状态不变量；检查本文件相对链接；明确区分静态文档核对与未来 HTTP/前端测试，PR 只报告实际执行的步骤、结果与未执行原因，不虚构 Vitest/Playwright 通过。
2. **范围、隐私与真实队友评审**：diff 只包含本人的 `docs/team/onboarding/B.md`，不修改队友文件、公共契约或应用代码；只用合成资料，不上传密钥、cookie、真实简历。PR 关联 `Closes #3`，请评审人留有内容的实际评审并处理反馈；不能代写“评审已通过”。协作流程见 [GitHub 指南](../github-guide.md)。

## 演练不解除依赖

本记录完成不等于团队验收完成：还需真实评审、反馈处理、PR 合并，以及合并后从最新 `main` 重新核对本人与队友成果。

**#9 在依赖表上仍受 #7 SET-01 阻塞**；演练之后被授权提前建好的那份 `frontend/` 不能改变这个判断，它只是让后续工作提前开始。按依赖表，下一步仍是等 #7 合并并验收，然后：对齐 SET-01 的工程布局与共享 DTO → 前端从 `mockApi` 切到 `httpApi`、接入 M2 的 HTTP 接口（服务端由 M2/M3/M5 注入 E 的 fake 网关，#12 不是 #9 的直接前置）→ 逐页补齐 #9 → #20 → #21，优先覆盖 [T01/T03/T05/T12/T19/T23](../../07-testing.md)。开发顺序见 [M1 开发任务顺序](../../modules/M1-web.md#开发任务顺序)。
