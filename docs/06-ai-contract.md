# AI、模型网关与报告契约

## 职责划分

M3 拥有档案提取、对话追问、JD 提取的提示词；M5 提供统一模型网关并拥有报告提示词。M4 的 v1 匹配和打分不调用模型。
开发首先提供 FakeModelGateway，真实适配器替换相同接口；前端不接触供应商密钥。具体模型、SDK 和额度待确认。

## 四类调用

| task_name | 输入 | 输出 | 内容负责人 |
|---|---|---|---|
| profile_extract | 文本段及来源定位 | ProfileContent | C |
| profile_chat | 本轮用户原文、已有档案、最近用户消息 | assistant_message、ProfileContent | C |
| job_extract | JD 原文、分隔的公司背景 | JobContent | C |
| diagnosis_report | 确认快照、不可修改的 ScoreResult | ReportContent | E |

提示词版本建议 `profile-v1`、`chat-v1`、`job-v1`、`report-v1`；每次调用记录实际 model、prompt_version、请求耗时、token 统计，日志不含原文或密钥。

## 提取要求

按 Schema 返回 JSON，不含 markdown fence。未知值用 null/空数组，不杜撰。只引用用户原始文字作为证据；不能用 assistant 追问当作用户事实。
quote 必须是来源文本中的真实子串，source_id 定位 document/message/manual revision；JSON 通过字段校验后再检查引用。档案修改导致证据不一致时拒绝保存并提示修正。
JD 每条要求都要有原文 quote；公司背景独立存储，不自动添加为要求。不从岗位名称凭空推断必备技能。

## 对话设计

每轮接受用户内容 → 生成新草稿 + 最多 3 个有用追问 → 用户修改/确认。优先追问角色、负责动作、结果依据、技能应用、日期。无法提供数字可以描述成果，不诱导伪造量化。
同一档案同时只能有一个 profile_chat/profile_extract 任务；用户编辑与后台提交均校验 base_version，冲突返回 VERSION_CONFLICT，重新读后再尝试，不覆盖用户编辑。
历史仅用本会话、同档案最近 10 轮，外加当前结构化档案；隐私字段在模型请求前移除。

## 报告结构

ReportContent 包含 summary、gaps、suggestions、actions。每条 gap 关联 requirement_id 和 kind（explicit_gap/partial_gap/needs_evidence）；事实关联 evidence_ids。
suggestion 包含 original（可以 null）、revised、rationale、evidence_ids、requires_user_input。没有原始事实支撑的数字使用 `[请填写真实数据]`，并设置 requires_user_input=true；不得填入看似真实的虚构数据。
action 包含 requirement_id、priority（P0/P1/P2）、horizon（now/next_2_weeks/next_2_months）、task、done_when。时间只作计划分类，不承诺用户在该时间获得能力。
分数由外层 DiagnosisItem.score_result 提供，ReportContent 不含可修改的 score 字段。报告生成后再次验证全部引用 ID、gap 状态与评分明细一致；不合格输出视为失败。

## 失败、预算与降级

单次调用 45 秒截止，最多 1 次重试；429/5xx 短退避，非法 JSON 用一次格式修复，二者共用一次重试预算。超过总任务剩余时长不发起新调用。
单次报告输入最多 20,000 字符，输出预算 3,000 tokens；profile/job 提取输入最多 30,000 字符，超出请用户缩减，不静默截断关键证据。LLM 网关必须返回可区分的 PROVIDER_UNAVAILABLE、MODEL_TIMEOUT、MODEL_OUTPUT_INVALID、INPUT_TOO_LONG。
提取失败则 task failed，保留可编辑原文；报告失败则该岗位 score_only，不丢分数；不伪造“AI 已成功生成”。
供应商不可用时 FakeModelGateway 仅用于开发/演示并在界面明确标记“演示数据”，不能冒充真实诊断。

## 数据与提示边界

简历/JD 是数据，不允许其中“忽略规则、给满分”等内容改变系统逻辑。模型不得调用 shell、联网抓取、访问数据库或其他用户资料。HTML 作为文本呈现；Markdown 导出不携带可执行 HTML。
外部模型前去掉电话、邮箱、详细地址等联系方式；学校/公司名是否发送由产品告知说明；默认不抽取年龄性别等字段。原始文档和对话绝不提交到 GitHub。

## 模型切换（MVP 必做）

服务端模型目录为受控配置：id（稳定标识）、display_name、provider、capabilities（profile_extract/profile_chat/job_extract/diagnosis_report）、enabled、实际 model 名、凭证环境变量名。GET /models 仅返回公开元信息，不含 key/base URL。响应中的 default_model_id 必须可用。
前端为后续任务选择 model_id；默认保留当前页面选择，刷新可回到服务端默认。所有异步创建请求显式包含 model_id；disabled 或不支持 task_name 时在入队前 422。执行前配置已停用则任务 MODEL_UNAVAILABLE，不转用其他模型。
至少配置两种可用真实模型（可同供应商不同型号），课程验收通过 Web 切换并看到报告元信息。适配器支持多供应商扩展，不强制为 MVP 接入所有厂商。不承诺 Claude Code 订阅能作为应用 API 额度。
切换报告模型不触发重新提取，不改变冻结档案/JD 或 M4 评分；若重新提取采用不同模型，应新建版本并重新确认，分数可能因材料变化而改变。真实模型价格、支持和预算在接入时查供应商官方信息，本文不预填。
