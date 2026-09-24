# M4 确定性匹配与评分

负责人：D（待替换为真实姓名）。当前只做设计；用户确认进入实现阶段后执行下列任务。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

未来可修改目录：`backend/app/scoring/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
受控词典、要求条件匹配、证据状态、加权计算、未知覆盖和类别分解。

## 输入 / 输出

输入：已确认 ProfileContent + JobContent、rule_version 与 matcher_version。

交付：RequirementAssessment[]、ScoreResult、可手算的金标准和边界测试。

## 开发任务顺序

1. 先实现给定状态的 calculate_score，跑通 66.7 基准。
2. 实现 has_skill、has_evidence 和受控等价词典。
3. 实现 min_months 区间并集与学历条件、冲突 unknown。
4. 输出可追溯 reason/evidence_ids，固定版本并联调。

## 边界与协作

不调用模型、不连数据库、不按年龄性别打分、不擅自增加封顶规则。

依赖关系：C 确保结构化字段；A 调度和持久化；E 消费评分明细；B 展示结果。

## 验收与交接

优先完成 [验收计划](../07-testing.md) 的 T05/T07/T08/T09/T10/T20；提交一组正常和一组失败示例、实际测试命令、已知限制和集成步骤。能被假数据独立调用后再联调，不等所有人完成。

## 交给 Claude Code 的首个提示

> 先读 CLAUDE.md 和 docs/modules/M4-scoring.md。当前仅做文档设计，请审查本模块输入输出、依赖与验收是否足够，不要写业务代码。将缺口列为待讨论项。进入实现阶段后，只实现当前 Issue 指定的一步，保持 OpenAPI 字段与模块边界，不生成整套应用。
