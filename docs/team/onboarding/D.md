# D：M4 证据匹配与确定性评分协作演练

对应 [Issue #5](https://github.com/Riverstar123/ResumeDoctor/issues/5)。C 负责评审，A 协调合并。本次只交付模块理解文档，不实现算法。模块范围依据 [M4 说明](../../modules/M4-scoring.md)，数值依据 [评分规则](../../05-scoring.md) 和 [诊断示例](../../examples/diagnosis-item.json)。

## 我接收什么、输出什么

我负责把用户已确认的事实与岗位要求逐项对照，再按固定规则计算材料覆盖分。分数表示材料对岗位要求的覆盖程度，不是录用概率。

依据 [架构与内部端口](../../02-architecture.md)，M2 worker 把已确认的 ProfileContent、JobContent 和 matcher_version 交给 `assess_requirements`，得到 RequirementAssessment[]；再把明细和 rule_version 交给 `calculate_score`，得到 ScoreResult。字段和枚举以 [OpenAPI](../../api/openapi.json) 为准，不另定义一套接口。

每条评估保留 requirement_id、category、importance、status、weight、coefficient、evidence_ids 和 reason。ScoreResult 包含总分、未知权重比例、类别分解、评估明细及规则和匹配器版本。当前版本为 `coverage-v1`、`matcher-v1`。每个 JD 独立计算，历史诊断绑定已确认的不可变快照。

## 我不负责什么

我不解析文件、不用模型提取简历或 JD，这些属于 C 的 M3；不连接数据库、不创建会话或返回 HTTP 响应，这些属于 A 的 M2；不生成 AI 报告或管理模型网关，这些属于 E 的 M5；不写前端页面，这些属于 B 的 M1。M5 消费评分结果，不能改写分数。

匹配只使用明确事实、受控等价词和数值条件，不调用大模型或 embedding，不自行补充岗位门槛。性别、年龄、籍贯、照片、婚育等不参与评分；不能从教育时间推断学历性质，也不能按文风判断造假。

## 成功样例：手算现有基准

以下沿用仓库合成样例，不包含真实简历。依据 [评分规则的手算基准](../../05-scoring.md)：must 权重为 2，preferred 为 1；met 系数为 1，partial 为 0.5，unmet 和 unknown 为 0。

1. r1：Python 项目使用，must、met。项目原文证据 e1 支持实际应用，贡献为 `2 × 1 = 2`。
2. r2：SQL 应用能力，must、partial。证据 e2 只有了解程度自述，缺少应用证据，贡献为 `2 × 0.5 = 1`。
3. r3：Docker，preferred、unknown。没有相关证据，evidence_ids 为空，贡献为 `1 × 0 = 0`，权重仍计入分母。
4. r4：本科及以上，preferred、met。证据 e3 明确已获得本科学位，贡献为 `1 × 1 = 1`。

总权重是 `2 + 2 + 1 + 1 = 6`，加权贡献是 `2 + 1 + 0 + 1 = 4`。

总分为 `ROUND_HALF_UP(100 × 4 / 6, 1) = 66.7`；未知权重比例为 `1 / 6`，保留四位小数得到 `0.1667`。这里统计的是未知要求的权重，不是按要求条数计算。

skill 类别为 `100 × 3 / 5 = 60.0`，education 类别为 `100 × 1 / 1 = 100.0`。总分必须按全部权重计算，不能平均类别分数。上述结果与 [诊断示例](../../examples/diagnosis-item.json) 一致。

核对方法：逐项检查重要性、状态、权重、系数、原文引用和 reason；确认 evidence_ids 都能在档案中找到；独立重算总分、未知比例和类别分数；检查版本字段；重排要求后结果应保持一致。这些是文档核对和未来测试要求，不代表评分服务已经运行。

## 失败样例：所有要求都不可评分

假设一个合成 JD 仅包含年龄、性别等不参与评分的要求，全部标记 `ignored=true` 并保留忽略原因。有效总权重为 0，不能返回 0 分或 100 分。

依据 [评分规则](../../05-scoring.md)，M4 应拒绝计算并给出 `NO_SCORABLE_REQUIREMENTS`；M2 将其映射为 HTTP 422，引导用户修改岗位要求。M4 自己不返回 HTTP 响应。

核对方法：确认被忽略要求没有进入分子、分母或类别计算；检查没有生成有效 ScoreResult；工程建立后再验证 API 的错误码和提示。当前只核对设计契约，未执行 API 测试。

## 为什么 unknown 不等于 unmet

Docker 没出现在档案中，只能说明证据不足，不能说明用户不会，因此为 unknown。只有用户明确否认，或明确数值、学历达不到规则要求，才判 unmet。两者系数都为 0，但语义不同：前者需要补充证据，后者是明确差距。

对于 must 要求，unknown 对应 `needs_evidence`，unmet 对应 `explicit_gap`，partial 对应 `partial_gap`；都不自动得出“不能投递”的结论。若肯定和否定证据冲突，统一返回 unknown 并解释 conflict，不能静默挑选一条。

## 合并前检查与后续任务

- 本 PR 只包含 `docs/team/onboarding/D.md`，使用合成样例，不带真实简历、令牌或密钥。
- 输入输出、状态含义及手算数值对照 OpenAPI、评分规则和示例；本地相对链接全部可解析。
- PR 关联 `Closes #5`，由 C 留下实际评审，处理意见后由 A 协调合并；合并后拉取 main 核对成果，不能以写好文档代替团队验收。

演练与 A 的 [#7 公共骨架](https://github.com/Riverstar123/ResumeDoctor/issues/7) 合并并验收后，按 [任务索引](../backlog.md) 开始 [#11 SC-01](https://github.com/Riverstar123/ResumeDoctor/issues/11)，再在各自依赖满足后完成 [#18 SC-02](https://github.com/Riverstar123/ResumeDoctor/issues/18) 和 [#24 QA-01](https://github.com/Riverstar123/ResumeDoctor/issues/24)。前置未满足时只做演练或准备，不抢写业务代码。

