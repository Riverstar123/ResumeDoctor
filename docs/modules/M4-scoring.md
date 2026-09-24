# M4 确定性匹配与评分

负责人：D。完成协作演练及当前 Issue 的前置成果后，按任务索引直接开工。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

模块所有权目录：`backend/app/scoring/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
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

> 先读 CLAUDE.md 和 docs/modules/M4-scoring.md。从 docs/team/backlog.md 找到当前 Issue，检查演练及依赖成果已合并。前置未满足时只完成演练或准备；满足后实现该 Issue 的范围。保持 OpenAPI 字段与模块边界，使用 fake 模型独立验证，不生成整套应用。

## GitHub 任务入口

先完成 [#5](https://github.com/Riverstar123/ResumeDoctor/issues/5) 协作演练，再按依赖领取：

- [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11) SC-01：确定性加权评分与手算金标准。
- [#18](https://github.com/Riverstar123/ResumeDoctor/issues/18) SC-02：要求匹配、同义词与证据状态。
- [#24](https://github.com/Riverstar123/ResumeDoctor/issues/24) QA-01：评分回归集与报告证据一致性回归。
