# M5 模型网关与 AI 报告

负责人：E（待替换为真实姓名）。当前只做设计；用户确认进入实现阶段后执行下列任务。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

未来可修改目录：`backend/app/llm/、backend/app/reporting/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
可切换模型目录/适配器、假网关、报告提示词、结构化输出校验、Markdown 格式化、全组验收协调。

## 输入 / 输出

输入：Profile/JD 快照、不可修改 ScoreResult、model_id；报告 schema。

交付：ModelGateway、至少两项可选真实模型配置能力、ReportContent、降级错误、导出文本和验收记录。

## 开发任务顺序

1. 先交 FakeModelGateway、ModelList 和报告合成样例，让 C/B 并行。
2. 统一 provider adapter 与 model_id 映射、能力筛选、超时/预算和配置检查。
3. 生成并校验 gaps/suggestions/actions，禁止改写分数或编造成果。
4. 实现 Markdown 导出，组织真实模型切换与端到端验收。

## 边界与协作

不把供应商 key 放前端，不修改 ScoreResult，不承担所有人的测试实现，不默默换供应商。

依赖关系：C 负责提取类 prompt；A 负责模型列表路由/任务快照；D 提供评分；B 展示报告与模型选择。

## 验收与交接

优先完成 [验收计划](../07-testing.md) 的 T11/T17/T18/T19/T20/T21/T22/T23；提交一组正常和一组失败示例、实际测试命令、已知限制和集成步骤。能被假数据独立调用后再联调，不等所有人完成。

## 交给 Claude Code 的首个提示

> 先读 CLAUDE.md 和 docs/modules/M5-report.md。当前仅做文档设计，请审查本模块输入输出、依赖与验收是否足够，不要写业务代码。将缺口列为待讨论项。进入实现阶段后，只实现当前 Issue 指定的一步，保持 OpenAPI 字段与模块边界，不生成整套应用。
