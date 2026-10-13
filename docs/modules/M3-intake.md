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

## 实现进度

### #10 IN-01：语义校验与合成端口

已交付 [backend/app/intake/](../../backend/app/intake/)：

| 文件 | 内容 |
|---|---|
| `errors.py` | `IntakeError`，携带机器可读 `code`；HTTP 映射由 M2 负责 |
| `validation.py` | `validate_profile_content`、`validate_job_content`；纯函数，不依赖数据库或模型 |
| `synthetic.py` | `SyntheticIntake`：`IntakePort` 的固定合成实现，供 M2/B/D 在没有真实模型时联调 |

校验范围：

- 引用必须来自来源原文：`quote` 必须是 `sources[source_id]` 的真实子串；来源缺失报 `UNKNOWN_SOURCE`
- 局部 ID 唯一：facts / evidence / requirements 各自唯一，重复报 `DUPLICATE_LOCAL_ID`
- 引用存在：`fact.evidence_ids` 必须能在同一快照的 evidence 中解析
- 月份：区间 `[start_month, end_month)` 必须非空；`as_of_month` 不得晚于当前月
- 学历：`kind=education` 的 `value` 限 associate/bachelor/master/doctorate/other
- 要求语义：`min_months` 必须有 `subject` 且 `target` 为正整数月数；`degree_at_least` 的 target 限四档；其余 operator 的 `subject` 必须为 null
- `ignored=true` 必须给出 `ignore_reason`
- 重复要求按 `(operator, target, subject, category, quote)` 规范化键合并：完全相同的合并为一条，重要性冲突时保留 must 并返回 warning；**结构相同但原文不同的两条**（如「接受在读」与「不接受在读」）无法自动判断是否等价，报 `REQUIREMENT_CONFLICT` 交用户确认

合成端口返回与 `docs/examples/profile.json`、`docs/examples/job.json` 完全一致的虚构数据，
可直接与 M4 的手算基准（score 66.7、unknown_weight_ratio 0.1667）对接；端口输出自身也走一遍上述校验。

测试入口：`uv run --project backend --frozen pytest -q`，本模块测试位于 [backend/tests/intake/](../../backend/tests/intake/)。

待定项：`[start_month, end_month)` 两端相等目前按非法处理（月数为零）。PR #44 评审指出半开区间只说明月数的计数方式，同月完成的短项目仍可能有合法技能证据；待与 A/B 明确「可保存事实」与「可累计月数」的录入规则后再定，不作为本任务阻塞项。

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
