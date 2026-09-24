# M3 文件、对话与 JD 结构化

负责人：C（待替换为真实姓名）。当前只做设计；用户确认进入实现阶段后执行下列任务。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

未来可修改目录：`backend/app/intake/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
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

> 先读 CLAUDE.md 和 docs/modules/M3-intake.md。当前仅做文档设计，请审查本模块输入输出、依赖与验收是否足够，不要写业务代码。将缺口列为待讨论项。进入实现阶段后，只实现当前 Issue 指定的一步，保持 OpenAPI 字段与模块边界，不生成整套应用。
