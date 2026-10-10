# A：M2 平台与集成协作演练

对应 [Issue #2](https://github.com/Riverstar123/ResumeDoctor/issues/2)，评审角色为 C；本次任务由用户确认其 GitHub 账号为 [huih02427-cmyk](https://github.com/huih02427-cmyk)。本记录说明我对职责、调用关系和验证方法的理解，不实现后端。

当前仓库只有文档与契约，尚无应用服务。下面的 HTTP 行为均为设计预期和未来核对方法；合成 JSON 可以现在读取，但不是运行成功证据。阶段与分工依据：[项目基线](../../00-decisions.md)、[团队计划](../../04-team-plan.md)、[任务索引](../backlog.md)。

## 我接收什么、交付什么

M2 是前端与业务模块之间的平台入口。来自 M1 的输入包括文件、经历消息、JD 原文、编辑后的内容、确认版本，以及诊断所选的档案/JD 版本和 `model_id`。字段、路径、必填项与响应类型以 [OpenAPI](../../api/openapi.json) 为准；[API 说明](../../api/README.md) 补充业务校验，不能另造一套 HTTP 字段。

我还需要从 `rd_session` HttpOnly cookie 取得会话上下文，检查有效性、资源归属、写请求来源、`Idempotency-Key` 和编辑的 `base_version`。资源 UUID 本身不等于访问权限。内部通过共享 DTO/端口接收 `ProfileContent`、`JobContent`、`RequirementAssessment[]`、`ScoreResult` 和 `ReportContent`，不让模块之间绕道调用 HTTP 或各自维护不同结构，签名依据 [架构与内部端口](../../02-architecture.md)。

我交付带资源 ID、版本与确认状态的 Profile/Job，任务受理和轮询接口，逐岗位 DiagnosisItem、统一错误及导出路由；也负责数据库迁移、内容版本和诊断快照、幂等事务、任务 worker、文件清理，以及可复现的装配/运行说明。表、约束和提交边界以 [数据库文档](../../03-database.md) 为准。API/worker 如何启动必须等工程任务提供实际入口，不能把设计目录写成现有程序。

| 角色 | 其主责 | A 的配合与边界 |
|---|---|---|
| B / M1 | 页面、交互、API 客户端、轮询展示 | 我提供契约与接口，不替 B 编写页面 |
| C / M3 | 文件解析、对话建档、JD 提取与原文证据 | 我交付受限文件句柄/输入上下文，接收校验后的内容，不在路由里实现提取 |
| D / M4 | 要求匹配、确定性评分与规则测试 | 我传入确认快照和版本，保存评分，不自行算分或让 AI 改分 |
| E / M5 | 模型目录、网关、报告校验与 Markdown 生成 | 我固定任务模型、调用报告端口、提供导出路由，不实现供应商适配或建议生成 |

模块所有权见 [M2 说明](../../modules/M2-platform.md)；共享 DTO 由 A 协调并请相关消费者评审。C/D/E 的业务模块不直接写数据库，持久化由 M2 控制。

## 一次用户流程怎样经过各模块

这是一组 HTTP 请求与后台任务，不是一次上传同步返回完整诊断。流程依据 [需求](../../01-requirements.md)、[架构](../../02-architecture.md)、[API](../../api/README.md) 与 [数据库事务](../../03-database.md)。

1. 用户接受模型处理说明后，M2 创建匿名会话；M1 从模型列表选择适合当前任务的 `model_id`。
2. 文件上传、经历消息或 JD 提取请求通过校验后，M2 创建 queued 任务并返回受理信息。后台调用 M3 的 `extract_document` / `build_profile` / `advance_conversation` / `extract_job`；M3 需要模型时通过 M5 的 `generate_structured` 网关，沿用任务已固定的模型，不私自换供应商。
3. M2 验证模块结果并按事务保存档案/JD 草稿。M1 轮询任务，从 `result.resource_type`、`resource_id`、`version` 获取内容；用户检查、必要时编辑，再显式确认最新版本。对话失败不保存半成品消息或草稿。
4. 创建诊断时，M2 在同一事务检查所有资源归属、确认状态及可评分要求，保存任务、诊断与岗位项，绑定指定的不可变版本。后续编辑只产生新版本，不改变进行中或历史诊断。
5. worker 逐岗位把确认快照交给 M4 的 `assess_requirements` 和 `calculate_score`，得到 `ScoreResult`；再把快照、评分和模型上下文交给 M5 的 `generate_report`。M5 只能解释评分和给建议，不能覆盖 M4 分数。
6. M2 校验并保存逐项结果、聚合任务状态；提交前核验租约、截止时间和会话有效性。M1 轮询终态并读取诊断；导出时 M2 检查访问权限与诊断状态，由 M5 的 `export_markdown` 生成内容。

按上述契约，异步提交返回 HTTP `202`；上传/消息/JD 返回 `task_id`，诊断还返回 `diagnosis_id`。任务状态是 `queued → running → succeeded / partial / failed`，只有诊断可为 `partial`。岗位项依次处于 `pending / scoring / reporting`，终态为 `succeeded / score_only / failed`。报告失败而评分已完成时保存 `score_only`，不是丢掉评分；聚合规则见架构文档。轮询任务接口 HTTP `200` 仅代表读取成功，须另查任务 `status`，不能把受理或轮询成功当作业务成功。

## 合成成功样例：固定输入怎样核对

资料来源：[样例说明](../../examples/README.md)、[profile.json](../../examples/profile.json)、[job.json](../../examples/job.json)、[diagnosis-request.json](../../examples/diagnosis-request.json)、[diagnosis-item.json](../../examples/diagnosis-item.json)。所有经历和岗位均为虚构；示例 UUID 不是服务端已经存在的资源 ID，`demo-model-a` 也不表示已接入真实供应商。

现在可做的文档核对：档案中 Python 有项目应用证据 `e1`，SQL 仅自述并引用 `e2`，已获得本科学位引用 `e3`，没有 Docker 证据。岗位要求 `r1/r2/r3/r4` 分别对应这四项。核对结果 JSON 的 `assessments[].requirement_id` 均存在于岗位，`evidence_ids` 均能在档案找到；Docker 应为 `unknown`，不能因为没提到就写 `unmet`。

该固定样例的手算值来自 [docs/05-scoring.md 的手算基准](../../05-scoring.md#手算基准)：总权重为 6，得分分子为 4，`score = 66.7`，`unknown_weight_ratio = 0.1667`；skill 分类为 60.0，education 分类为 100.0。这些数值只适用于该样例相同的规范化事实、要求和规则版本，不是任意输入的结果。

服务实现后的核对步骤（本轮未执行）：

1. 按 [合成接口演练](../../examples/README.md) 创建会话、选择 fake 模型，在同一会话创建档案并提交上述合成经历消息；轮询成功后获取实际档案 ID 和版本。用户核对事实与证据，必要时通过编辑校正成固定样例内容，再确认最新版本。
2. 提交 `job.json` 中的 JD 原文和公司背景，使用模型列表实际返回的模型 ID；轮询获取实际岗位 ID 和版本。核对并必要时编辑要求，使其与固定样例一致，再确认最新版本。
3. 参照 `diagnosis-request.json` 的结构提交诊断，但替换为上述实际资源 ID、确认版本及可用 `model_id`，携带新的幂等键。记录返回的 `task_id`、`diagnosis_id`；不能把示例 ID 或固定版本号直接当成真实资源使用。
4. 轮询到终态后读取诊断，检查 `profile.id/version` 和 `items[].job.id/version` 与请求的确认版本一致。对于此 fake 成功样例，预期任务及岗位项均 `succeeded`；岗位项同时有 `score_result`、`report`、`model_metadata`，且 `error=null`。
5. 核对固定样例评分和引用：`rule_version=coverage-v1`、`matcher_version=matcher-v1`；`r1/r2/r3/r4` 状态分别为 `met/partial/unknown/met`。若校正后的规范化输入一致，才与上述手算值比较；报告的差距/建议引用正确要求与证据，`model_metadata.provider=fake` 明确标示合成来源。
6. 导出终态诊断的 Markdown，核对档案/JD/规则/模型信息与页面相同；编辑档案生成新版本后，重新读取旧诊断，确认仍绑定原版本。相关未来验收见 [T07、T23 与版本测试](../../07-testing.md)。

这些是预期检查点；没有服务、测试替身或运行记录时，不能写成“API/worker 已通过”。

## 失败样例：另一会话读取诊断或导出

本例对应 [T15](../../07-testing.md) 与 [API 隔离规则](../../api/README.md)：有效会话访问其他会话的资源应为 HTTP `404`、`error.code=RESOURCE_NOT_FOUND`；没有有效会话应为 HTTP `401`、`error.code=SESSION_EXPIRED`。错误体结构以 [OpenAPI Error](../../api/openapi.json) 为准，包含 `error` 和 `request_id`。

服务实现后按以下方法检查，本轮未发起应用请求：

1. 建立两个独立浏览器上下文，或两个互不共享的临时 cookie jar，分别调用 `POST /api/v1/session`，请求体为 `{"consent_version":"v1"}`。写请求使用运行配置允许的 Origin；核对返回的会话 `id` 不同且各自保存 `rd_session`。同一有效 cookie 重复创建会话不会得到独立会话，因此不能复用同一个 cookie jar。
2. 只在会话一按成功样例创建并完成合成诊断，从实际响应取得 `diagnosis_id`；使用会话一先确认诊断和导出可读取，保存其特有的虚构内容作为泄漏检查标记。不要用随机或样例 UUID 替代这一步，否则无法证明资源确实属于别人。
3. 使用会话二的 cookie 对这个真实 ID 请求 `GET /api/v1/diagnoses/{id}` 和 `GET /api/v1/diagnoses/{id}/export`。分别检查 HTTP `404` 和统一错误体，响应中不得包含会话一的经历、JD、分数、报告、模型元信息或导出内容；状态/正文也不应透露资源属于别人。
4. 再用会话二请求一个不存在的诊断 ID，核对也是 `404 / RESOURCE_NOT_FOUND`，业务错误信息不区分“不存在”和“其他会话资源”；`request_id` 可不同。
5. 在没有 cookie 的第三个上下文请求同一诊断和导出，分别检查 `401 / SESSION_EXPIRED`，不能误写成跨会话 `404`。将来记录响应状态、脱敏错误体和结果，cookie、原始请求头与个人资料均不提交。

## 合并前两项检查

1. **契约与验证证据**：逐项对照 OpenAPI 字段/状态码、数据库版本与事务、内部端口及固定手算来源；检查相对链接。明确区分静态文档核对与未来 HTTP 测试，PR 只报告实际执行的步骤、结果和未执行原因，不虚构 pytest 或前端测试通过。
2. **范围、隐私与真实队友评审**：diff 只包含本人的 `docs/team/onboarding/A.md`，不修改队友文件、公共接口或应用代码；只用合成资料，不上传密钥、cookie、真实简历。保留根 `.gitignore` 的 `/指南.md`，但不把本地指南或忽略规则杂项纳入此 PR。提交前运行 `git check-ignore -v -- 指南.md`、`git ls-files -- 指南.md` 并检查暂存清单。PR 关联 `Closes #2`，请确认账号后的角色 C 留有内容的实际评审并处理反馈；不能代写“C 已通过”。协作流程见 [GitHub 指南](../github-guide.md)。

演练最终完成还需要真实评审、反馈处理、PR 合并，以及本人更新 main 后看到本人和队友成果。本记录完成不等于上述团队验收已完成，也不解除 #7 对全部演练的依赖。
