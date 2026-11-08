# 报告返回失败定位与修复

日期：2026-11-06；关联 Issue #75、PR #76。

## 证据范围

检查了原工作区和当前工作区 output 中的 JSON/日志，未找到截图诊断对应的生成响应或独立
审核响应。历史截图那一次的具体触发句无法从现存记录恢复，不能把另一份报告的结论冒充为它的根因。
本轮优先回放此前明确标记为合成材料的 `case-real-03` 冻结快照与两份已保存的真实响应，
不重做简历/JD 提取。原始资料、模型响应和本地命中句子放在忽略目录，不进入仓库。

## 已确认的具体触发点

| 来源 | 字段 | 已确认结果 |
|---|---|---|
| 保存响应 2 | `/suggestions/1/requires_user_input` | true 触发 coverage-v2 禁止待确认事实改写的 UNSUPPORTED_TEMPLATE；本地可重复命中。 |
| 保存响应 2 | `/suggestions/0/revised` | 把独立技能清单中的 VBA、Power Query 写进某次 Excel 提醒表工作，原经历只明确使用 Excel；真实短审核返回 unsupported。 |
| 保存响应 2 | `/suggestions/1/revised` | 将 Wind 基础操作自述扩写成在行业研究与权益投资实习中实际使用；引用原文未记录这个应用场景，真实短审核返回 unsupported。 |

保存响应 1 通过本地确定性校验，未进行整份报告的真实语义验收。这说明 JSON/字段合法
不足以证明自由文本受证据支持。审核器也不是事实证明：本轮另一个被检查的行动返回 supported，
不将该行动记成已确认缺陷。

原策略会因任一可选改写/行动失败而丢掉整份报告，这放大了报告失败的影响。生成提示再严格，
也不能保证模型不把“单独列出的技能”拼成“在指定经历中已经应用”。

## 修复边界

- 新 coverage-v3 报告的可选项先逐项做确定性校验；不合格项移除并记录原因，保留所有程序
  生成的 summary/gaps。不能借“过滤可选项”吞掉冻结评分或必需项的问题。
- 独立审核必须完整覆盖全部候选条目、无重复/未知编号、引用范围正确。只有符合这些条件后，
  才允许移除被拒的可选建议/行动。摘要或 gap 被拒、审核缺项、伪造引文或越界支持均拒绝报告。
- 不重新请求审核来争取通过。带否决的格式错误或不完整审核仍立即结束，保留评分。
  正常仍是生成和审核两个请求；剔除可选项不增加调用。
- 保留的 AI 文案已经逐项审核。程序追加固定说明“部分 AI 建议未通过资料核对，已略去”，
  不把被拒文案当成通过，也不改动分数。旧 v1/v2 保留整份拒绝策略，不重写历史结果。
- HTTP 执行和离线回放共用响应封装提取逻辑，回放同样拒绝 finish_reason=length 的响应，
  避免将恰好可解析的截断 JSON 误记为通过。

## 能定位到哪里

普通日志记录 `report_output_rejected`：report trace UUID、profile/job UUID 及版本、提示/网关配置版本、阶段、HTTP
尝试序号（attempt=0 表示本地处理环节，不代表额外 HTTP 调用）、安全失败分类、JSON 字段路径、句子序号、字符区间、
文本摘要哈希。原文、模型引文、联系方式、密钥和完整供应商响应不写入普通日志。

句子序号和字符位置从零开始，字符区间为 Python Unicode 码点的 [start,end)。若审核引用在同一
字段重复出现，记录 occurrences 并不声称知道唯一位置；审核未给出可靠引文时只定位到条目。
Schema 未知属性名以 * 掩码，避免把模型生成的恶意字段名或个人信息带入日志。

generation/review 各阶段失败都记录，格式修复前的失败不会丢掉；普通日志不输出模型原文。
最终失败的 ErrorInfo.details 仅额外保留合法 UUID `report_trace_id`，页面显示“报告排查编号”，
可用它关联 worker 的 task/item、模型输出及业务校验日志，不暴露内部文件路径。

report-grounding-v8 增加 issues 的 field/quote/reason。程序检查引文确实来自对应候选字段，
再换算为字符范围；无法核对的引用不能作为“可过滤的合格审核”。通过项必须 issues=[]。

## 本地回放

`python -m app.tools.replay_report --profile profile.json --job job.json --diagnosis diagnosis.json --candidate response.json --response-mode deepseek_strict`

可加 `--review review.json` 复核已保存审核结果，或 `--assemble-advice` 合成当前评分说明。
模式须取自原请求记录：原生 strict 用 `deepseek_strict`，普通 JSON 用 `json_object`，同时约束候选和审核封装。不要根据响应是否存在工具调用或当前模型目录猜测。回放供应商封装而未传模式时返回 `REPLAY_MODE_REQUIRED`；纯解码 JSON 可不传模式，但无法验证原供应商封装是否合法。
这个工具回放响应封装和报告契约校验；--assemble-advice 仅组装评分说明，不代替 ReportService 的完整 v3 逐项筛除流程。该流程由受控 HTTP 回归单独验证。默认无网络，不读密钥，不因确定性通过而宣称语义通过；结果分别记录 deterministic/semantic。
仅对已授权的本地材料加 `--show-excerpts` 时输出命中片段。

ReportService 的可选 diagnostic_observer 仅为显式注入的本地合成材料回放钩子，可捕获供应商
封装、生成/审核响应、组装和过滤后的候选。生产装配不启用这个原文捕获器。捕获器故障不影响
诊断结果，不引发模型重试；并发请求的 trace 使用 ContextVar 隔离。

## 验证与费用

本轮后端全量：1108 passed、129 skipped、1 Starlette/httpx 弃用警告。随后追加的 HTTP 保存/
导出和审核异常场景，reporting 模块 185 passed；报告/网关/错误边界最终定向回归 373 passed。前端 119 passed，build/typecheck/types:check
通过。跳过的 PostgreSQL、隔离集群、旧解析器 wheel 与全新归档环境未视为已验收。

受控故障覆盖缺失字段、错误数字、非原文引用、必需项拒绝、负面且不完整/格式异常的审核、
越界支持、重复条目、伪造引文、截断但可解析的响应、原文不进入日志、并发 trace 隔离和捕获器故障。
新增 HTTP 回归证明：剔除被拒的可选项后，规则分数不变、报告可保存/导出、被拒文案不泄露到报告，
模型请求仍只有两次。

真实供应商只请求了一次短审核，复用已保存的三条合成输出；原生 strict 返回有效 issues，
其中一项 supported、两项 unsupported。供应商用量：输入 2902、输出 213、总计 3115 tokens，
其中输入缓存命中 640。响应与用量在 `output/report-investigation/scoped-audit-response.json`，
本地综合证据在同目录 findings.json。设置输出上限 1000，无自动重试，也没有重新生成整份报告。
这次短审核不等于完整真实报告链路或生产发布验收。

PR #76 更新后必须重新请求相关队友评审；批准当前提交后才能合并，再从 main 打包部署。

## 评审后续

以上为 c86c5df 的排查记录。mysteriesy 随后的评审发现了不可靠审核响应重试覆盖否决，以及毕业/到岗日期证明边界问题，已在同一 PR 修复。当前审核最多一次请求；最新行为与本地复现结果见 [评审修复](pr76-review-fixes.md)，不能以本记录原先的重试表述替代新规则。
