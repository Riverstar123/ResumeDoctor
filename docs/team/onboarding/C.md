# C：M3 输入与结构化协作演练

对应 [Issue #4](https://github.com/Riverstar123/ResumeDoctor/issues/4)，评审角色为 D，A 协调合并。本次任务只写文档，不实现业务代码。我的模块说明见 [M3-intake](../../modules/M3-intake.md)。

当前仓库只有文档与契约，尚无应用服务。下文所有接口行为都是设计预期和将来的核对方法，不是已运行证据。

## 我负责什么、不负责什么

M3 的任务是：把用户给的材料（文件、对话、JD 原文）变成**可核验的结构化数据**。所有权目录是 `backend/app/intake/`，只提供内部端口给 M2 调用，自己不暴露 HTTP 接口。

我交付四个端口，签名依据 [架构与内部端口](../../02-architecture.md)：

| 端口 | 输入 | 输出 |
|---|---|---|
| extract_document | 受限临时文件句柄、媒体类型 | 原始文本、页段定位、warnings |
| build_profile | 原始文本、来源类型、可选上一版 Profile | ProfileContent |
| advance_conversation | 用户原文、现有 ProfileContent、历史用户轮次 | assistant_message + ProfileContent |
| extract_job | JD 原文、公司背景 | JobContent |

需要模型时通过 E 的 `generate_structured` 模型网关，我不直接接触供应商、不持有密钥。

**我不负责**：不直接写数据库（持久化是 M2）；不决定最终分数（M4）；不生成报告（M5）；不写页面（B）；不做 OCR；不做招聘筛选、淘汰或候选人排名。

## 我接收什么

- 从 M2 接收：受限文件句柄、JD 原文、每轮用户对话原文、当前档案快照、任务已固定的 `model_id`
- 从 E 接收：ModelGateway
- 字段、枚举、必填项一律以 [OpenAPI](../../api/openapi.json) 为准，我不另造一套命名

## 一条输入怎样经过 M3

三条路径都只产出**草稿**，用户确认之前不能用来诊断。

1. **上传文件**：M2 校验大小与真实类型并存好文件 → worker 调 `extract_document` 拿到文本和页段定位 → `build_profile` 得到 ProfileContent 草稿 → 交回 M2 存成 v1 草稿。
2. **对话**：`advance_conversation` 每轮产出新草稿加最多 3 个追问 → 交回 M2。
3. **JD**：`extract_job` 得到 JobContent → 交回 M2。

"写消息""建版本"这两个动作属于 M2 的事务，不是我的职责；我失败时不留下半成品消息或草稿。

## 成功样例：两句虚构经历怎样变成事实与原文证据

以下内容完全虚构。用户分两轮输入：

- 第 1 条：`我在课程项目里用 Python 做过一份数据清洗。`
- 第 2 条：`SQL 我了解基本语法，还没在项目里用过。`

我应当产出的事实（简化示意，字段以 OpenAPI 为准）：

| 事实 | kind | label | application | evidence_ids |
|---|---|---|---|---|
| f1 | project | Python | applied | [e1] |
| f2 | skill | SQL | claimed | [e2] |

对应的原文证据：

| 证据 | source_type | source_id | quote |
|---|---|---|---|
| e1 | message | 第 1 条消息的 id | 我在课程项目里用 Python 做过一份数据清洗。 |
| e2 | message | 第 2 条消息的 id | SQL 我了解基本语法，还没在项目里用过。 |

怎么核对：

1. 每条 `quote` 必须能在来源原文里**原样找到**，是真实子串；不能是模型改写过的句子。这是 [AI 契约](../../06-ai-contract.md) 对提取的硬要求。
2. 每条 fact 的 `evidence_ids` 都要能在本快照的 evidence 列表里解析到，档案内 id 唯一；解析不到就拒绝保存。
3. 只采信用户原文。assistant 的追问不是事实来源，`source_type` 只能落在 document / message / manual 这三处用户来源上。
4. 对接 M4 的后果：f1 带"实际应用"证据，Python 类要求可能判 met；f2 只是自述、没有应用，只能 partial —— 写了 "SQL" 不等于会用 SQL。

## 失败样例：JD 要求 Docker，档案里完全没提到

岗位要求 r3「熟悉 Docker 优先」，而档案里既没有 Docker 事实，也没有任何否认表述。

**正确结果：`unknown`**（缺少证据）。它照样进分母，不给分也不倒扣。
**错误结果：`unmet`**。`unmet` 只用于用户明确否认、或数值明确不达标；**没提到一律是 unknown**。这也正是我不替用户补经历、不编造成果数字的原因。

同类失败还有两个：

- 模型返回的 quote 不是原文子串 → 拒绝该事实并提示修正，不把改写句当证据。
- 扫描版 PDF 没有文字层 → 报 `NO_TEXT_LAYER`，引导用户改走对话路径，不伪造内容。

## 合并前检查

1. **契约与证据**：字段、枚举、必填项逐条对照 OpenAPI；明确区分"静态文档核对"和"将来 HTTP 实测"，不把没执行过的测试写成已通过。
2. **范围与隐私**：只提交 `docs/team/onboarding/C.md`，不改别人的 onboarding 文件和公共契约；只用完全虚构的材料，不含真实简历、密钥或 cookie。
3. **流程**：PR 关联 `Closes #4`，请 D 留一条有内容的评审，处理后由 A 合并。

## 我理解到的下一步

本次演练合并、且 A 的 #7 公共骨架合并之后，我按顺序做：#10 档案与 JD 校验和合成提取端口（fake 网关独立验证）→ #16 对话建档与 JD 提取工作流 → #17 PDF/DOCX 输入与解析异常 → #25 输入安全与提示注入验收。依赖未满足时只做准备或评审队友 PR，不抢写业务代码。
