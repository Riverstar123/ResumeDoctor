# AI、模型网关与报告契约

## 职责划分

M3 拥有档案提取、对话追问、JD 提取的提示词；M5 提供统一模型网关并拥有报告提示词。M4 的 v1 匹配和打分不调用模型。
开发首先提供 FakeModelGateway，真实适配器替换相同接口；前端不接触供应商密钥。实际端点、模型名和密钥由服务端配置注入，不影响 fake 模式开发；配置入口见 [模型配置](10-model-configuration.md)。

## 四类调用

| task_name | 输入 | 输出 | 内容负责人 |
|---|---|---|---|
| profile_extract | 文本段及来源定位 | ProfileContent | C |
| profile_chat | 本轮用户原文、已有档案、最近用户消息；可选服务端核验的诊断目标 | assistant_message、ProfileContent | C |
| job_extract | JD 原文、分隔的公司背景 | JobContent | C |
| diagnosis_report | 确认快照、不可修改的 ScoreResult | ReportContent | E |

提示词初始版本为 `profile-v1`、`chat-v1`、`job-v1`、`report-v1`；每次调用记录实际 model、prompt_version、请求耗时、token 统计，日志不含原文或密钥。

2026-11-01 的合成端到端整改将四类当前提示版本同步提升至 v2：提取提示明确区分原子项目/工作应用事实与技能清单，JD 的规范 target/subject 与 matcher-v1 对齐；报告提示明确数字、日期只能由本条引用支持。新任务冻结新版本，历史快照和旧报告不改写，评分规则仍为 coverage-v1 / matcher-v1。

同日 PR #64 评审修复将档案提取和对话提示进一步提升为 `profile-v3`、`chat-v3`，明确区分历史证据不可改写与当前事实可以凭新增用户来源纠正。JD 与报告仍为 `job-v2`、`report-v2`；已保存的 v2 证据与快照保留原版本，不重新生成。

2026-11-05 的本地优化实现将当前对话、报告提示提升为 `chat-v4`、`report-v3`；档案提取与 JD 保持 `profile-v3`、`job-v2`。对话增加岗位定向提问，非 fake 报告增加独立事实审核请求，审核提示为 `report-grounding-v2`。历史任务仍保留冻结版本。本次已通过报告生成与审核、只提问、回答整理三项真实供应商合成烟测；这不替代全面质量评测或生产验收，尚未部署至学院服务器。证据见[优化记录](team/ux-benchmark-and-optimization.md)。

## 提取要求

按 Schema 返回 JSON，不含 markdown fence。未知值用 null/空数组，不杜撰。只引用用户原始文字作为证据；不能用 assistant 追问当作用户事实。
quote 必须是来源文本中的真实子串，source_id 定位 document/message/manual revision；JSON 通过字段校验后再检查引用。档案修改导致证据不一致时拒绝保存并提示修正。
用户明确更正且提供新增用户来源时，可更新对应事实并保持事实 ID，引用该来源的真实纠正证据；不能只为统一标签改写旧事实。历史证据继续原样保留，不通过追加相反事实替代纠正；未被更正的旧事实不能遗漏，无新来源支持的改写仍被拒绝。
JD 每条要求都要有原文 quote；公司背景独立存储，不自动添加为要求。不从岗位名称凭空推断必备技能。

## 对话设计

普通对话接受用户内容 → 整理候选事实与最多 3 个有用追问 → 用户修改/确认。内容变化时生成新草稿；内容未变时不强行增加版本。优先追问角色、负责动作、结果依据、技能应用、日期。无法提供数字可以描述成果，不诱导伪造量化。
同一档案同时只能有一个 profile_chat/profile_extract 任务；用户编辑与后台提交均校验 base_version，冲突返回 VERSION_CONFLICT，重新读后再尝试，不覆盖用户编辑。
历史仅用本会话、同档案最近 10 轮，外加当前结构化档案；隐私字段在模型请求前移除。

岗位定向补充沿用 `POST /profiles/{id}/messages`，新增可选 `diagnosis_focus={diagnosis_id,item_id,requirement_id}` 与 `questions_only=false`。服务端按会话归属读取诊断、冻结 JD、非 met 的可评分要求及对应 assessment/gap，不能由客户端上传一段岗位文字冒充已核验目标。TaskResult 回显目标和 questions_only，前端恢复任务时校验档案与目标，防止其他要求的结果串入。

首轮 `questions_only=true` 必须提供诊断目标：只生成追问，忽略 content 作为事实来源，不保存 user 消息；成功时保存 assistant 消息，档案内容、版本和确认状态均保持原样。模型必须原样返回其收到的脱敏档案投影，再由服务端保留原档案，不要求模型恢复未收到的联系方式。JD、assessment、gap 和 assistant 问题都不能成为用户证据。

提交真实回答时使用 `questions_only=false`，按本轮用户原文建立来源、核验引用；发生内容变化后生成未确认草稿，用户核对并确认后才能诊断。用户可以明确说没有做过，不得将否定润色为具备能力。前端用新确认档案与原 JD 版本创建另一份诊断，原报告及证据快照保留。

## 报告结构

ReportContent 包含 summary、gaps、suggestions、actions。report-v9 的真实模型只输出私有 ReportAdvice（suggestions/actions）；服务端按冻结评分生成 summary 与全部非 met gaps，合成完整报告后仍执行确定性检查和独立审核。公开 HTTP 契约不变。每条 gap 关联 requirement_id 和 kind（explicit_gap/partial_gap/needs_evidence）；事实关联 evidence_ids。
suggestion 包含 original（可以 null）、revised、rationale、evidence_ids、requires_user_input。历史 coverage-v1 可以使用标记 requires_user_input=true 的显式待填写模板；coverage-v2/v3 只允许完整证据支持的事实改写，未知信息放入 gaps/actions。两者都不得填入看似真实的虚构数据。
action 包含 requirement_id、priority（P0/P1/P2）、horizon（now/next_2_weeks/next_2_months）、task、done_when。时间只作计划分类，不承诺用户在该时间获得能力。
分数由外层 DiagnosisItem.score_result 提供，ReportContent 不含可修改的 score 字段。报告生成后再次验证全部引用 ID、gap 状态与评分明细一致；不合格输出视为失败。

非 fake 报告在确定性结构、来源和数字检查之后，以独立请求逐项审核 summary、gap、suggestion、action。审核使用同一已选模型、过滤后的证据及冻结 JD 上下文，不代表独立供应商；JD 只能解释岗位条件，不能支持用户经历。审核者只能判断冻结候选，不能改写候选来获得通过。代码检查审核项完整且不重复、引用属于该项允许的证据、证据 ID 绑定本次完整输入原文。审核不回显原文；旧格式若带 evidence_checks，仍要求完整、去重且与原文逐字一致。旧 v1/v2 中 `unsupported`、`contradicted`、`uncertain` 或不完整审核均拒绝报告。新 coverage-v3 只有在完整覆盖、无重复且引用合法的审核后，才可剔除被拒的可选建议/行动；摘要或 gap 被拒、格式异常、审核不完整或引用不合法仍拒绝整份报告。被拒内容不展示，不重新求批准。待补充模板也不能将缺失事实写成已完成经历。

没有独立审核能力的非 fake 网关拒绝生成报告并保留规则评分。明确标记的 fake 网关保留合成演示路径，只运行确定性校验，不运行独立语义审核；fake 测试通过不证明自然语言建议真实。模型审核本身也不是事实正确性的证明，仍须通过带人工标准的案例评测与真实供应商复验。

## 失败、预算与降级

普通结构化调用共用 45 秒截止和最多 1 次重试；429/5xx 短退避，非法 JSON 使用格式修复，二者共享重试预算，最多两个 HTTP 请求。非 fake 报告的生成与独立审核合计共用 45 秒：生成最多一次失败重试，审核最多发出一次请求，收到不可靠输出或传输失败即结束。正常两个 HTTP 请求，最多三个，不是每个阶段各有 45 秒或各重试一次。超过总任务剩余时长不发起新调用。
单次报告输入最多 20,000 字符，生成输出上限 6,000 tokens；审核输入另行校验相同字符上限，输出使用独立的 2,048–8,192 token 上限；profile/job 提取输入最多 30,000 字符，超出请用户缩减，不静默截断关键证据。LLM 网关必须返回可区分的 PROVIDER_UNAVAILABLE、MODEL_TIMEOUT、MODEL_OUTPUT_INVALID、INPUT_TOO_LONG。
提取失败则 task failed，保留可编辑原文；必需报告内容或审核完整性失败则该岗位 score_only，不丢分数；v3 被拒的可选建议可按上述规则剔除，程序明确提示已略去；不伪造“AI 已成功生成”。

真实 OpenAI-compatible 报告路径使用 `generate_reviewed`：先生成并完成确定性校验，再审核同一冻结候选。生成阶段的校验/格式及 429/5xx/网络失败共用一次重试；审核阶段的任何失败均直接结束，不能通过新请求覆盖可能存在的否决。修复指令使用固定失败分类，回显仍受字符预算限制。既有 `generate_validated` 仍可用于单阶段结构化校验，但不能替代非 fake 报告要求的独立审核。

真实网关以单调时钟建立整次调用截止时间，HTTP 只得到剩余额度；生成、审核、退避、格式/业务修复及输出校验共同消耗这份预算。预算到期后不再发送后续请求；同步校验结束后再次检查时间，超时不返回成功。到期统一返回 MODEL_TIMEOUT 并只记录一次最终调用结果，外部取消仍原样传播。

`MODEL_OUTPUT_INVALID` 可在 ErrorInfo.details 返回经过白名单校验的 `reason_code`：`JSON_INVALID`、`SCHEMA_INVALID`、`OUTPUT_TRUNCATED`、`UNSUPPORTED_NUMBERS`、`REFERENCE_INVALID`、`REPORT_VALIDATION_FAILED`、`PROFILE_DATE_INVALID`、`FUTURE_END_DATE`。只暴露类别，禁止携带原文、供应商输出、异常正文或凭证；逐岗位拒绝日志也只记录任务 ID、错误码和类别。前端按模型输出错误提示，不要求用户修正已被接受的输入字段。旧错误没有 reason_code 时仍可显示通用提示。
供应商不可用时 FakeModelGateway 仅用于开发/演示并在界面明确标记“演示数据”，不能冒充真实诊断。

## 数据与提示边界

简历/JD 是数据，不允许其中“忽略规则、给满分”等内容改变系统逻辑。模型不得调用 shell、联网抓取、访问数据库或其他用户资料。HTML 作为文本呈现；Markdown 导出不携带可执行 HTML。
外部模型前去掉电话、邮箱、详细地址等联系方式；学校/公司名是否发送由产品告知说明；默认不抽取年龄性别等字段。原始文档和对话绝不提交到 GitHub。

## 模型切换（MVP 必做）

服务端模型目录为受控配置：id（稳定标识）、display_name、provider、capabilities（profile_extract/profile_chat/job_extract/diagnosis_report）、enabled、实际 model 名、凭证环境变量名。GET /models 仅返回公开元信息，不含 key/base URL。响应中的 default_model_id 必须可用。
前端为后续任务选择 model_id；默认保留当前页面选择，刷新可回到服务端默认。所有异步创建请求显式包含 model_id；disabled 或不支持 task_name 时在入队前 422。执行前配置已停用则任务 MODEL_UNAVAILABLE，不转用其他模型。
至少配置两种可用真实模型（可同供应商不同型号），课程验收通过 Web 切换并看到报告元信息。适配器支持多供应商扩展，不强制为 MVP 接入所有厂商。不承诺 Claude Code 订阅能作为应用 API 额度。
切换报告模型不触发重新提取，不改变冻结档案/JD 或 M4 评分；若重新提取采用不同模型，应新建版本并重新确认，分数可能因材料变化而改变。真实模型价格、支持和预算在接入时查供应商官方信息，本文不预填。

## 上传日期与输出长度修复（2026-11-05）

当前提示升级为 `profile-v4`、`chat-v5`、`report-v4`。已开始的在读教育（kind=education、completed=false，入学月为空或不晚于资料截止月）允许 end_month 保存原文明示的预计毕业月份；不推算日期，不改动档案截止月份，不认定已获得学历。M3、M2 和前端采用相同的未来结束日期规则；工作/项目及已毕业或完成状态未知的教育仍不能把未来结束月作为完成事实。

平台档案校验失败在用户直接编辑时仍为 VALIDATION_ERROR，提供安全的具体日期或引用提示；相同校验在后台模型任务中映射为 MODEL_OUTPUT_INVALID，保留白名单 reason_code，不暴露简历或模型原文。模型截断提示明确指输出长度限制，与账户余额无关。报告输出上限由 3,000 提至 6,000 tokens，同时要求精简说明、优先少量建议和行动，不遗漏任何必需 gap。共享 45 秒总期限和一次重试不变，审核截断仍直接拒绝。


## 结构化条件升级（2026-11-05）

同步 #69 后的当前提示版本为 profile-v5 / chat-v8 / job-v4 / report-v7，独立报告审核为 report-grounding-v6。
字段与评分细节见 [评分契约](05-scoring.md) v2。PDF 优先使用页面排版顺序；只有非空白字符完整保留时才采用，否则保留原文字并给出阅读顺序待核对提示。
真实提取的属性类别、值、同事实原文引用和子条件比较在共享重试预算内校验；非法结构不得进入评分。季节/相对时间不能臆定为具体到岗月份。
报告审核接收一次完整证据表与档案事实，条目只按编号关联冻结要求/评分/证据，防止遗漏已提供信息及上下文重复膨胀。人工待核对不等于缺经历；日期冲突要澄清；OR 已满足时不能再要求另一个备选。
历史 v1 的显式待填写模板接受 `[请填写真实…]`（有界标签）和既有占位符，仍须标记 requires_user_input。v2 改写建议只允许已有证据完整支持的表述；未知事实、日期冲突和可用时间问题移入 actions，不再提供容易被照抄为肯定事实的待填写简历模板。
report-v7 将两版改写策略显式分开，gap_constraints 同时列出 required、unknown_reason 和 counted_in_score；必须解释的人工项即使不计分也不能遗漏，但描述应为待核对而非候选人欠缺。审核接收冻结的资料截止月和改写策略，检查过去到岗安排及 JD 未要求的组件门槛。
报告生成和独立审核仍共用 45 秒和一次失败重试；独立审核否决不重试刷通过。未通过时只保存规则评分。

属性 quote 若逐字存在于本轮输入、但模型遗漏其 evidence_id，提取阶段可为该原文建立证据并关联；不修造 quote/value，不修改未变旧事实。普通并列技能固定为独立条目，只有明示“或/任一”等关系时才按备选合并计权。

## PR #69 复审修复

原 #69 使用 `chat-v7` / `report-grounding-v4`；与结构化条件整合后为 `chat-v8` / `report-grounding-v6`。对话保留最近 10 条用户消息和最近 10 条助手消息，并以消息 ID 序列保留顺序。助手问题只作为理解短答的上下文，绝不加入新增证据的来源白名单；SQL worker 和内存任务采用相同窗口规则。

数据库 Worker 传递存储层已按角色限制的完整历史，不再将合并序列截为总共 10 条；模型适配器仍按角色取最近 10 条，并受既有输入总预算约束。

审核输入集中存储证据、岗位要求及评分，各审核项只保留对应 ID。输出 `checks[].supports` 只列证据 ID，`evidence_checks` 对所有实际使用的完整 quote 去重回显一次。服务端同时校验逐项授权、证据原文完全一致、没有多余/遗漏/重复的证据回显，以及审核项完整性。独立输出预算按最大预期 JSON 的 UTF-8 字节数加 512 估算，并限制在 8,192–16,384 tokens；仍可能受供应商或推理消耗影响，不能保证任意材料均在预算内。总期限、一次重试及明确拒绝/截断不再求批准的规则保持不变。

站内跳转时，岗位补充页的已生成问题、对应任务引用、未提交回答和未保存编辑保存在当前会话的内存中，返回原目标可恢复；即使用户尚未填写回答，也保留已生成的问题。不写浏览器持久存储、不自动提交事实或重复生成任务。刷新仍提示可能丢失输入，会话过期或删除会清空暂存。


2026-11-06 修复采用 models-v5 官方 DeepSeek strict 工具输出，保留本地业务校验；原生结构不代表事实一定正确。新分类区分事实拒绝、审核不完整与无效审核引用；实质性拒绝仍不重新求批准。详见 [修复与回滚记录](team/structured-output-reliability-2026-11-06.md)。


2026-11-06 报告返回排查：独立审核提升至 report-grounding-v8，以 field/quote/reason 定位候选句；普通日志只保存安全路径、字符区间与摘要哈希。ErrorInfo.details 允许额外的合法 UUID report_trace_id，供用户关联服务日志。私有 ReviewRequest 增加可选 finalize_candidate，仅供完整审核后的可选项剔除；旧调用默认不启用。证据、回放方法、费用和兼容边界见 [报告返回排查](team/report-return-investigation-2026-11-06.md)。


PR #76 的评审修复进一步限定审核只发出一次请求，并拒绝多个结果、重复 JSON 键和混合输出。v3 日期证明要求毕业事件关联、到岗记录相对冻结截止月仍有效，同义词不能绕过期限条件。详见 [复审记录](team/pr76-review-fixes.md)。

2026-11-07 根据 C 的复审，当前提取/对话提示同步升级为 `profile-v6` / `chat-v9`，JD/报告保持 `job-v4` / `report-v9`。`graduation_year` 不仅要有四位年份及真实子串引用，还要在属性引用和同事实关联证据中明确对应毕业事件或届别；单纯课程/学期结束、结业、毕业设计/论文，以及待定、否定或延期表述不能支持该属性。正常完成课程后的明确离校安排可保留，退学/休学/肄业离校不能支持。未确认时省略属性并保留原证据，不猜月份或完成学位。提取、对话、人工保存和 matcher-v3 共用此校验，避免错误属性绕过 v3 的 end_month 投影检查；matcher-v2 仍可按冻结规则回放。此轮验证仅使用本地合成数据，未调用真实 DeepSeek。

同轮按 D 的复审统一两种响应模式的封装检查：普通 JSON 不能忽略同消息的非空 tool_calls，native 不能忽略额外正文；两者均拒绝非空 refusal、旧式 function_call、content_filter 或其他显式异常结束状态。兼容供应商省略 finish_reason，显式正常状态为 stop（native 另可为 tool_calls），length 保留 OUTPUT_TRUNCATED 分类。审核异常仍只结束，不增加请求。离线回放共用这些检查，且空/非法 choices 返回可定位的错误，不因先取第一个元素而崩溃。

2026-11-07 后续 D 复审修正：毕业属性的历史短引用可由精确出现位置所对应的明确毕业事件支持，正常括号限定语不再导致合法档案保存失败；课程日期不能借用另一处毕业事件。离校仅接受已建立正常课程完成先后关系的证据，同时处理相邻多个修饰词后的延期/未确认状态。响应封装回放必须显式传原请求的 `--response-mode json_object|deepseek_strict`，不得凭响应是否含工具调用猜测；缺少模式返回 `REPLAY_MODE_REQUIRED`，在线严格模式拒绝的空工具结果不会被离线按普通 JSON 放行。原请求模式同时用于候选与审核封装，纯解码 JSON 只能证明报告契约及已存审核结果，不能证明供应商封装合法。提示版本不变，本轮仅本地验证。
