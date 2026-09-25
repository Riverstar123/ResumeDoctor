# M1 Web 前端

负责人：B。完成协作演练及当前 Issue 的前置成果后，按任务索引直接开工。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

模块所有权目录：`frontend/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
用户页面、模型选择、文件与对话输入、档案/JD 确认、任务轮询、逐岗位报告和 Markdown 下载。

## 输入 / 输出

输入：HTTP 契约与 docs/examples/diagnosis-item.json；接口未完成时使用 mock。

交付：完整页面流程、统一 API 客户端、错误/加载/空状态、组件测试与端到端操作。

## 开发任务顺序

1. 先依据 OpenAPI 定义前端类型和 mock；展示模型能力与选择。
2. 完成上传/对话→档案草稿→编辑确认。
3. 完成 JD 输入/编辑确认，1–5 项选择。
4. 完成任务轮询、逐岗位结果、partial/score_only 和导出。

## 边界与协作

不计算真实评分，不直接请求模型，不自行定义字段或改数据库。

依赖关系：A 提供 HTTP；C 解释编辑字段；D 解释分数；E 提供报告示例。

## 验收与交接

优先完成 [验收计划](../07-testing.md) 的 T01/T03/T05/T12/T19/T23；提交一组正常和一组失败示例、实际测试命令、已知限制和集成步骤。能被假数据独立调用后再联调，不等所有人完成。

## 交给 Claude Code 的首个提示

> 先读 CLAUDE.md 和 docs/modules/M1-web.md。从 docs/team/backlog.md 找到当前 Issue，检查演练及依赖成果已合并。前置未满足时只完成演练或准备；满足后实现该 Issue 的范围。保持 OpenAPI 字段与模块边界，使用 fake 模型独立验证，不生成整套应用。

## GitHub 任务入口

先完成 [#3](https://github.com/Riverstar123/ResumeDoctor/issues/3) 协作演练，再按依赖领取：

- [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9) WEB-01：前端工程与 mock 页面全流程。
- [#20](https://github.com/Riverstar123/ResumeDoctor/issues/20) WEB-02：上传、对话与档案/JD 确认交互。
- [#21](https://github.com/Riverstar123/ResumeDoctor/issues/21) WEB-03：多岗位报告、模型选择与导出页面。
- [#29](https://github.com/Riverstar123/ResumeDoctor/issues/29) DEMO-01：课堂演示路线与五人讲解彩排。
