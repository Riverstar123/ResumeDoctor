# 报告可靠性修复与发布回滚

日期：2026-11-06。站点：<https://mf18.show.lingnan.top/>。

## 线上状态与协作门禁

用户报告确认按钮回归、AI 报告再次拒绝后，展示站已回滚至 release `20261106-152032`，
平台返回容器 running。两次中间发布 `20261106-181934`、`20261106-182451` 已撤回。
平台的 deploy.id 不随 rollback 更新，核对当前版本使用 status.release，不使用旧的 deploy.id。
本次修复从最新 main `bb5f7fd` 建分支，保留已合并 #69/#71 的紧凑确认及吸底操作栏。
新代码必须提交 PR、请求队友评审、获准后合并，再从 main 打包部署；当前尚未发布本修复。
手机布局另发现 overflow:hidden 创建了错误的滚动容器，改为 overflow:clip，保留横向裁剪且不阻断吸底。

回滚证据保存在原工作区忽略目录 `output/rollback-and-reviewed-fix/`。部署令牌、API 密钥、
数据库和原始模型响应不进入提交。

## 已确认的问题及诊断边界

- 上次直接发布使用旧分支，漏掉主分支已合并的 `.profile-confirmation` 样式挂接和紧凑确认。
- 截图中的报告错误为 MODEL_OUTPUT_INVALID / REPORT_VALIDATION_FAILED；旧错误分类同时用于
  确定性校验和独立审核，不能凭该代码认定为 JSON 语法错误，也不能定位到某一句报告。
  未取得当时被拒绝的完整候选报告，不声称已复现真实供应商的那一次否决。
- 对冻结资料与要求逐项核对后，确认“提供毕业时间”“提供可到岗日期”只匹配事实标签，
  漏掉已有日期记录；“英语财报阅读”和“英文财报阅读”也未被受控等价匹配。
  这类 unknown 不证明原文没有写，报告不得将其润色为候选人能力缺失。
- 原适配器仅使用 json_object，Schema 放在提示中；该模式保证 JSON 语法，不保证业务字段。
  原生能力依据 [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
  和 [strict Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/) 核对。

## 本次实现

- models-v5 仅为精确型号 deepseek-flash 启用官方 HTTPS Beta strict 工具调用，关闭 thinking。
  强制一个仅承载结果数据的函数，不执行工具；不重定向其他来源的密钥，不静默退回其他模型。
  Schema 在 wire 层展开引用、关闭额外字段、完整 required；供应商不支持的长度约束仍在本地验证。
- report-v9 的真实模型仅返回私有 ReportAdvice（suggestions/actions）。summary 和全部非 met
  gap 由程序从冻结状态生成，不让模型决定 gap 类型、引用或必需项是否存在；公开 ReportContent
  仍包含原四个字段。规则未匹配使用中性核对说明，不断言原文缺失，不改写历史分数。
- 可选建议和行动各限三条；当前覆盖规则不允许的待填模板在审核前移除，保留项仍须通过
  原有引用、数字及独立语义审核。不会把无依据的肯定句当作已确认事实，也不伪造审核成功。
- report-grounding-v7 输入保留完整证据与全局资料，输出仅返回逐项 verdict 与证据 ID；
  原生输出 evidence_checks 固定 null，不回显长原文。旧审核回显仍可离线验证。输出预算为
  2048–8192 tokens，总期限和一次失败重试保持不变；实质性拒绝或截断审核不再求一次批准。
- 新增安全分类 REPORT_GROUNDING_REJECTED、REPORT_REVIEW_INCOMPLETE、REPORT_REVIEW_INVALID，
  区分事实拒绝、审核覆盖不完整和无效审核引用。平台白名单传递分类，不暴露原始文本。
- 新诊断使用 coverage-v3 / matcher-v3：仅对受控的“提供日期”标签核对对应已有字段，
  毕业结束年月的兼容投影必须同时有原文明确毕业及相同年月；单独教育结束日期不能当毕业。
  到岗日期存在不证明立即可用。财报语言等价仍区分技能自述 partial 与实际应用 met。
  v1/v2 代码路径保留，持久化前按记录版本重算，旧报告及冻结资料不改写，无数据库迁移。
- 调用记录增加供应商实际 prompt/completion/cache-hit tokens。传输移除重复 Schema 文档和
  不需要的上传元数据，完整证据不截断。页面给出具体失败类别，避免引导重复付费重试。

## 验证状态

最终回归：后端 1090 passed、129 skipped、1 warning；前端单元测试 118 passed；浏览器 19 passed，
包含桌面/手机的长档案顶部、中部及展开编辑时按钮仍在视口内。构建、类型、Ruff 和契约检查通过
（41 个 Schema、4 个示例、路由完整）。全量后端之后新增的期限保护用例按相关模块单独复验。
跳过项包括未配置 PostgreSQL、隔离集群与新归档运行环境，不能视为这些环境已验收。
本轮尚未新增付费 DeepSeek 请求。受控 HTTP 响应验证不等于
真实供应商的完整语义审核通过，回滚健康检查也不替代新代码验收。

上一轮真实能力探测成功返回 strict nullable 工具调用（322 输入、50 输出 tokens）。报告
转接程序错误转发了已解压响应的压缩头，导致额外生成；两份生成共 17497 tokens，均未进入
独立审核。包含探测的三次请求合计 17869 tokens，记录在原工作区忽略目录
`output/structured-output-fix/`。这属于上次验证开销，不是本轮模型费用，也不是完整链路通过。
