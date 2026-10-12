# E：M5 模型网关与报告协作演练

对应 [Issue #6](https://github.com/Riverstar123/ResumeDoctor/issues/6)。本人 GitHub 账号为 [y1324-cyber](https://github.com/y1324-cyber)，账号映射见 [CLAUDE.md 角色与账号](../../../CLAUDE.md#角色与-github-账号) 与 [README 五人模块](../../../README.md#五人模块)。按[团队计划的成员与职责表](../../04-team-plan.md#成员与职责)，M5 的第一评审人是 **B**，网关部分由 **C** 加看，A 协调合并。

本记录只写"我理解成什么样"，**不含任何应用代码**。下面是设计预期和将来的核对方法，不是已运行证据；凡涉及实现的地方目前都还没写。

## 我这一块接收什么、输出什么

用大白话说：M5 是**中间那一层**——别人要用模型能力时，统一找我这一层去拿，而不是各自直连供应商。

**我接收**：已经确认、不能再改的 Profile / JD 快照；M4 算好的、**只读**的 ScoreResult；以及每个任务开工前就固定的 `model_id`。

**我输出**：一个统一的模型网关 ModelGateway（对外只有一个 `generate_structured` 入口）；一份受控模型目录和至少两种可选真实模型；报告内容 ReportContent（summary、gaps、suggestions、actions）；可区分的降级错误；Markdown 导出文本；以及全组验收记录。所有权目录是 `backend/app/llm/` 和 `backend/app/reporting/`。

## 我不负责什么

- 不解析文件、不用模型去"读"简历或 JD——那是 C 的 M3。
- 不连数据库、不建会话、不返回 HTTP、不做持久化——那是 A 的 M2。
- 不匹配、不打分——那是 D 的 M4。
- 不写页面和模型下拉框——那是 B 的 M1。
- **最要紧的一条：分数是 M4 定的，报告一个字都不能改**，只能解释和给建议。
- 我也不把供应商 key 放前端，不承担全组所有人的测试实现，更不能偷偷把供应商换掉。

## 成功样例：拿一份固定评分写出一份合规报告

用仓库里的合成样例（虚构，无真实简历）：[diagnosis-item.json](../../examples/diagnosis-item.json)。评分是 66.7 分，四项要求 r1 met、r2 partial、r3 unknown、r4 met。我据此应产出（字段以 [OpenAPI](../../api/openapi.json) 为准）：

| 区段 | 内容 | 约束 |
|---|---|---|
| summary | 覆盖部分要求；SQL 可补应用证据，Docker 待确认 | 不引入分数以外的新结论 |
| gaps | r2 partial_gap、r3 needs_evidence | kind 与评估状态一一对应 |
| suggestions | r2 保留原句，`revised` 用占位模板 | 用 `[真实项目名称]` 等占位，`requires_user_input=true` |
| actions | r3：P1、next_2_weeks、可核实的 `done_when` | 时间只作计划分类，不承诺获得能力 |

**如何核对**：gaps 的 kind 要和评分明细对得上（partial→partial_gap、unknown→needs_evidence）；所有 `evidence_ids` 能在快照里解析到；ReportContent 里**没有**能改分的字段；`model_metadata.provider=fake` 标明这是合成来源。这是拿文档逐条比对，**没有真的跑网关**。

## 失败样例：报告想编数字、或引用对不上

- **（a）编造数字**：建议里出现"把 SQL 使用率提升 30%"这类没有原文支撑的数字。正确做法是写 `[请填写真实数据]` 并置 `requires_user_input=true`，不填看着像真的假数据。
- **（b）引用不一致**：报告引用了不存在的 `requirement_id`/`evidence_id`，或把 r3（unknown）写成 explicit_gap，与评分明细冲突。正确做法是**判定为失败，不返回这份报告**，不静默放行。

同类失败还有：模型返回的 JSON 解析不了 → `MODEL_OUTPUT_INVALID`；供应商不可用 → `PROVIDER_UNAVAILABLE`；单次调用超 45 秒 → `MODEL_TIMEOUT`；输入超 20,000 字符 → `INPUT_TOO_LONG`（请用户缩减，不静默截断证据）；报告失败但评分已完成 → 该岗位终态 `score_only`，**保留分数、不丢分**。

**如何核对**：逐条检查 summary/gaps/suggestions/actions 的引用与评分是否一致，确认占位符与 `requires_user_input` 正确。这些是文档核对与将来测试要求，不代表报告服务已经运行。

## 补充：以后假模型和真模型怎么切换（**现在还没实现**）

这一节说的是"将来"的样子。**目前仓库里还没有 `backend/app/llm/` 的实现，也没有 `backend/config/models.yaml`，没有启用任何真实模型，更不要在这里填真实 key。** 依据 [模型配置](../../10-model-configuration.md) 与 [AI 契约](../../06-ai-contract.md)。

切换靠**三层**配合：

1. **适配器层**（`backend/app/llm/`）：假适配器和真适配器实现**同一个**网关接口。第一个真实适配器走 OpenAI 兼容的 Chat Completions 协议；换别的协议要新增适配器，不能只改 URL 就号称支持所有模型。
2. **配置层**（`backend/.env`，本地私有、不进 Git，从 [backend/.env.example](../../../backend/.env.example) 复制）：服务端变量决定用假还是真——
   - `LLM_MODE`：`fake` / `real`
   - `LLM_PROVIDER`：`fake` / `openai_compatible`
   - `LLM_MODEL`：默认真实模型名
   - `LLM_API_KEY`：**本地填、默认留空**（本演练不填真实 key）
   - 另有 `LLM_BASE_URL`、`LLM_MODEL_A / LLM_MODEL_B`。
3. **目录层**（`backend/config/models.yaml`）：保存公开 id、显示名、provider、能力、enabled 与"环境变量名"的映射；**目录里不放 key**，`GET /models` 只回公开元信息，前端只从这里选 `model_id`，不能直接输入 key 或任意端点。

**切换步骤（实现后才有）**：先由 AI-02 确认假/真适配器的 HTTP stub 测试通过 → 在本地 `.env` 填地址/模型/key（**不发到 Issue、PR 或聊天**）→ 在目录里启用条目并设 `LLM_MODE=real` → 用工程交付的实际启动命令重启服务与 worker → 到 AI-03 阶段逐一验收真实的提取与报告、两种模型间切换、以及失败降级；**同一份确认快照只换报告模型时，评分必须保持不变** → 回演示模式改 `LLM_MODE=fake` 并重启，页面必须明确显示演示标记。

**边界**：fake 只能用于开发/演示并明确标记"演示数据"，不能冒充真实诊断；凭证没配不影响之前的开发、联调和自动测试，但**真实 AI 验收必须在最终交付前完成**。

## 合并前检查

1. **契约与验证证据**：字段、枚举、错误码逐条对照 OpenAPI 与 AI 契约；明确区分静态文档核对与将来 HTTP/网关实测，不把未执行的测试写成已通过。
2. **范围与隐私**：diff 只包含本人 `docs/team/onboarding/E.md`，不改队友文件、公共契约或应用代码；只用合成样例，**不填真实 key**，不含真实简历、cookie 或供应商端点。
3. **模型与分数边界**：报告不改 ScoreResult；不静默换供应商；前端不含密钥。
4. **流程**：PR 关联 `Closes #6`，请 B 留一条有内容的实际评审、C 加看网关部分，处理反馈后由 A 协调合并；不能代写"评审已通过"。

## 我理解到的下一步

本次演练合并、且 A 的 [#7 公共骨架](https://github.com/Riverstar123/ResumeDoctor/issues/7)（已合并，PR #38）成果经核对验收后，我按依赖顺序推进：[#12 AI-01](https://github.com/Riverstar123/ResumeDoctor/issues/12) 模型目录与 FakeModelGateway（优先交付，让 C/B 并行）→ [#19 RP-01](https://github.com/Riverstar123/ResumeDoctor/issues/19) 结构化报告、校验与 Markdown 导出 → [#23 AI-02](https://github.com/Riverstar123/ResumeDoctor/issues/23) 可配置真实模型适配器 → [#26 QA-03](https://github.com/Riverstar123/ResumeDoctor/issues/26) 与 [#27 AI-03](https://github.com/Riverstar123/ResumeDoctor/issues/27) 假/真模型验收 → [#30 FINAL-01](https://github.com/Riverstar123/ResumeDoctor/issues/30) 最终验收。依赖未满足时只做准备或评审队友 PR，不抢写业务代码。
