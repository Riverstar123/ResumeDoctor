# E：M5 模型网关与报告协作演练

对应 [Issue #6](https://github.com/Riverstar123/ResumeDoctor/issues/6)。本人 GitHub 账号为 [y1324-cyber](https://github.com/y1324-cyber)。按[团队计划的成员与职责表](../../04-team-plan.md#成员与职责)，M5 的第一评审人是 **B**，网关部分由 **C** 加看，A 协调合并。本记录只说明我对职责、调用关系和验证方法的理解，**本次 PR 不含任何应用代码**。

当前仓库只有文档与契约，尚无应用服务。下文所有网关、报告与导出行为都是设计预期和将来核对方法，不是已运行证据。模块范围依据 [M5 说明](../../modules/M5-report.md)，接口与字段依据 [AI 契约](../../06-ai-contract.md) 和 [OpenAPI](../../api/openapi.json)，模型配置入口见 [模型配置](../../10-model-configuration.md)。

## 我负责什么

M5 由两部分组成，所有权目录是 `backend/app/llm/` 和 `backend/app/reporting/`：

1. **统一模型网关 ModelGateway**。对外只暴露一个 `generate_structured` 接口；开发先用 FakeModelGateway，真实适配器替换同一接口，调用方不变。四类调用中 `profile_extract`、`profile_chat`、`job_extract` 的提示词归 C，`diagnosis_report` 的报告提示词与 ReportContent 归我。C 通过我的网关调用模型，不直接接触供应商或密钥。
2. **结构化诊断报告与 Markdown 导出**。输入是已确认的 Profile/JD 快照、不可修改的 ScoreResult 和固定 `model_id`；输出 ReportContent（summary、gaps、suggestions、actions），生成后再校验全部引用 ID、gap 状态与评分明细一致，不合格视为失败。`export_markdown` 生成不携带可执行 HTML 的导出文本。

我还交付**受控模型目录与至少两种可选真实模型配置能力**（id、display_name、provider、capabilities、enabled、真实 model 名、凭证环境变量名），以及**全组验收协调**（[#26 QA-03](https://github.com/Riverstar123/ResumeDoctor/issues/26)、[#27 AI-03](https://github.com/Riverstar123/ResumeDoctor/issues/27)、[#30 FINAL-01](https://github.com/Riverstar123/ResumeDoctor/issues/30)）。

## 我不负责什么

我不解析文件、不用模型提取简历或 JD（C 的 M3）；不连接数据库、不创建会话、不返回 HTTP 响应、不做持久化（A 的 M2）；不做匹配与打分（D 的 M4）；不写前端页面与模型选择交互（B 的 M1）。**我不修改 ScoreResult，报告不能改写分数**。我不承担所有人的测试实现，也不静默更换供应商。

## 我接收什么、输出什么

- 从 M2 接收：已确认的 Profile/JD 快照、不可修改的 ScoreResult、任务已固定的 `model_id`。
- 从 M4 接收：只读的评分明细 RequirementAssessment[] 与 ScoreResult。
- 交付给 M2/M1：ModelGateway、报告端口 `generate_report`、导出端口 `export_markdown`、可区分的降级错误码。
- 字段、枚举、必填项一律以 OpenAPI 为准，不另造一套命名。

## 成功样例：由固定评分生成一份合规报告

沿用仓库合成样例，内容全部虚构，不包含真实简历。依据 [诊断示例](../../examples/diagnosis-item.json)：ScoreResult 为 `score=66.7`、`unknown_weight_ratio=0.1667`、`rule_version=coverage-v1`、`matcher_version=matcher-v1`，四项评估 r1 met / r2 partial / r3 unknown / r4 met。

我据此应产出（字段以 OpenAPI 为准）：

| 区段 | 内容 | 关键约束 |
|---|---|---|
| summary | 覆盖部分要求；SQL 可补充应用证据，Docker 待确认 | 不引入分数以外的新结论 |
| gaps | r2 partial_gap、r3 needs_evidence | kind 与评估状态一致，引用正确 requirement_id |
| suggestions | r2：`original` 保留原句，`revised` 用占位模板 | 使用 `[真实项目名称]` 等占位，`requires_user_input=true` |
| actions | r3：P1、next_2_weeks、可核实的 `done_when` | 时间只作计划分类，不承诺获得能力 |

`report-v1` 生成后核对：gaps 的 kind 与 `score_result.assessments` 的状态一一对应（partial→partial_gap、unknown→needs_evidence）；所有 `evidence_ids` 能在快照中找到；ReportContent 不含任何可修改的 score 字段；`model_metadata.provider=fake` 明确标记合成来源。本轮为静态文档比对，未运行网关。

## 失败样例：报告编造成果数字或引用不一致

（a）建议里出现"把 SQL 使用率提升 30%"这类没有原文支撑的数字。**正确结果**：写 `[请填写真实数据]` 并置 `requires_user_input=true`，不得填入看似真实的虚构数据。
（b）报告引用了不存在的 `requirement_id` 或 `evidence_id`，或把 r3（unknown）写成 explicit_gap，与评分明细冲突。**正确结果**：视为失败，不返回该报告，不静默放行。

同类失败还有：

- 模型返回无法解析的 JSON → 一次格式修复后仍失败，报 `MODEL_OUTPUT_INVALID`，不伪造"AI 已成功生成"。
- 供应商不可用 → `PROVIDER_UNAVAILABLE`；单次调用超 45 秒 → `MODEL_TIMEOUT`；输入超 20,000 字符 → `INPUT_TOO_LONG`（请用户缩减，不静默截断关键证据）。
- 报告生成失败但评分已完成 → 该岗位终态为 `score_only`，保留分数，不丢分。

核对方法：逐条检查 summary/gaps/suggestions/actions 的引用与评分一致性，确认占位符与 `requires_user_input` 正确。这些是文档核对与将来测试要求，不代表报告服务已经运行。

## 为什么 unknown 不等于 unmet

Docker 没出现在档案中，只说明证据不足，判 unknown 并对应 `needs_evidence`，含义是"需要补证据"；只有用户明确否认、或数值/学历明确不达标才判 unmet，对应 `explicit_gap`，含义是"明确差距"。两者都不自动得出"不能投递"。报告必须保留这一区分，不把缺证据写成差距，也不替用户补经历或编造成果。

## 合并前检查

1. **契约与验证证据**：字段、枚举、错误码逐条对照 OpenAPI 与 AI 契约；明确区分静态文档核对与将来 HTTP/网关实测，不把未执行的测试写成已通过。
2. **范围与隐私**：diff 只包含本人 `docs/team/onboarding/E.md`，不改队友文件、公共契约或应用代码；只用合成样例，不含真实简历、密钥、cookie 或供应商端点。
3. **模型与分数边界**：报告不改 ScoreResult；不静默换供应商；前端不含密钥。
4. **流程**：PR 关联 `Closes #6`，请 B 留一条有内容的实际评审、C 加看网关部分，处理反馈后由 A 协调合并；不能代写"评审已通过"。

## 我理解到的下一步

本次演练合并、且 A 的 [#7 公共骨架](https://github.com/Riverstar123/ResumeDoctor/issues/7) 合并并验收后，我按依赖顺序推进：[#12 AI-01](https://github.com/Riverstar123/ResumeDoctor/issues/12) 模型目录与 FakeModelGateway（优先交付，让 C/B 并行）→ [#19 RP-01](https://github.com/Riverstar123/ResumeDoctor/issues/19) 结构化报告、校验与 Markdown 导出 → [#23 AI-02](https://github.com/Riverstar123/ResumeDoctor/issues/23) 可配置真实模型适配器 → [#26 QA-03](https://github.com/Riverstar123/ResumeDoctor/issues/26) 与 [#27 AI-03](https://github.com/Riverstar123/ResumeDoctor/issues/27) 假/真模型验收 → [#30 FINAL-01](https://github.com/Riverstar123/ResumeDoctor/issues/30) 最终验收。依赖未满足时只做准备或评审队友 PR，不抢写业务代码。
