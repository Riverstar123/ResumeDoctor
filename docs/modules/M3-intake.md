# M3 文件、对话与 JD 结构化

负责人：C。完成协作演练及当前 Issue 的前置成果后，按任务索引直接开工。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

模块所有权目录：`backend/app/intake/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
提取文件文本、形成结构化档案、对话追问、JD 要求提取、引用验证与标准化。

## 输入 / 输出

输入：受限文件句柄、原文、当前 ProfileContent；E 的 ModelGateway。

交付：extract_document/build_profile/advance_conversation/extract_job 端口与输入/证据测试。

## 开发任务顺序

1. 先用纯文本与假网关生成 ProfileContent 和 JobContent。
2. 实现引用子串校验、未知字段、原文修正与要求去重。
3. 加入逐轮对话，只有用户原文成为证据。
4. 实现 PDF/DOCX 文本提取与异常/资源限制。

## 边界与协作

不直接写数据库、不最终评分、不引入 OCR 或招聘淘汰逻辑。

依赖关系：A 提供任务和存储；E 提供网关；D 共同确认事实标签/要求 operator；B 提供确认编辑。

## 验收与交接

优先完成 [验收计划](../07-testing.md) 的 T01/T02/T03/T06/T08/T17；提交一组正常和一组失败示例、实际测试命令、已知限制和集成步骤。能被假数据独立调用后再联调，不等所有人完成。

## 交给 Claude Code 的首个提示

> 先读 CLAUDE.md 和 docs/modules/M3-intake.md。从 docs/team/backlog.md 找到当前 Issue，检查演练及依赖成果已合并。前置未满足时只完成演练或准备；满足后实现该 Issue 的范围。保持 OpenAPI 字段与模块边界，使用 fake 模型独立验证，不生成整套应用。

## GitHub 任务入口

先完成 [#4](https://github.com/Riverstar123/ResumeDoctor/issues/4) 协作演练，再按依赖领取：

- [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) IN-01：档案与 JD 数据校验和合成提取端口。
- [#16](https://github.com/Riverstar123/ResumeDoctor/issues/16) IN-02：对话建档与 JD 提取工作流。
- [#17](https://github.com/Riverstar123/ResumeDoctor/issues/17) IN-03：PDF/DOCX 文件输入与解析异常。
- [#25](https://github.com/Riverstar123/ResumeDoctor/issues/25) QA-02：输入安全、提示注入与资料清理验收。
