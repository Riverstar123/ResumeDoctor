# 证据覆盖评分（当前 coverage-v3 / matcher-v3）

诊断页面、版本比较和 Markdown 导出以「已证实覆盖分」为主分。它直接读取冻结的逐项评分明细，
分母是全部非 ignored 要求的总权重，分子仍是各项权重乘以原有覆盖系数的总和，保留一位小数。
明确不满足和待核验项当前贡献均为零，页面分别展示两种状态。待人工核验的要求可进入定向补证，
补充后仍由规则判断可自动识别的条件。接口中的历史 `score` 和 `counted_in_score` 保留原自动评分口径。
页面明确以评分卡的已证实覆盖分为准，摘要保留经历分析、考试成绩等文字内容。AI 提示要求摘要只做材料分析，不另行给出岗位诊断分数。

2026-11-08 候选隔离：新提取中的日期语义疑问由M3放入 `unverified_attributes`；
该数组不提供满足证明，缺少其他可用记录时保持 unknown，仍计入自动评分分母。
毕业年份已标待核对时，不从同一事实的 end_month 再投影出“已提供毕业时间”。
程序在理由中说明候选待核对；整份档案确认不会提升它。旧快照没有此字段时按原路径处理；
直接提交到 attributes 的不合法解释仍被严格校验，历史报告不改写。

到岗候选须与整个冻结档案一起核对：只要另有可用到岗属性，仍标记为待核对的
`availability_start` 待核对记录就不能被跳过，返回 unknown/conflicting_evidence 并保留
两边证据（包括跨事实、来源和来源类型，适用于 profile、same_fact 及受控日期存在性条件）。
候选是否已处理以数组状态为准，不根据结束月份、历史叙述格式或引文子串自动判定失效。
即使引文外层写“历史安排已结束”，内部仍可能夹带当前约束，故取消历史候选的自动排除。
纯历史但仍待核对的候选也先保留unknown；用户核对后可使用既有“移除这条候选”操作保存
新版本，原始证据保留。新版本不再受已移除候选影响，旧版本和已有报告不变。整份档案
确认不会自动移除候选，也不要求改写原文来匹配格式。不处理候选仍可生成和导出基础报告。
这是保守取舍：历史候选可能需多一次人工移除，不新增字段、审核请求或模型token开销。
无关字段及独立 OR 分支不受影响；
旧 matcher-v2 回放保持原语义。这里表示当前安排尚不能确认，不把待核对候选当作已证实的否定。

## v3 日期证明与受控等价修复

新诊断使用 v3，权重、系数与计分范围沿用 v2。旧 v1/v2 路径及已存结果保留。

- has_evidence 的受控目标“提供毕业时间”“提供可到岗日期”等核对对应已有日期属性，不只匹配事实标签。
- 无 graduation_year 时，只有教育 end_month 与同一子句中明确指向毕业事件的年月一致，才可作内部只读投影；课程结束、毕业设计/论文、待定、否定或条件式不提供毕业证明。教育结束日期本身不证明毕业，不改写档案或认定已获得学位。
- 已有 graduation_year 也须由该属性引用及关联证据中的明确毕业表述或届别支持；提取、人工保存与 v3 评分共用校验，错误属性返回输入校验错误，不能绕过日期检查直接计分。明确毕业年份/届别无需编造月份；正常完成课程后明确的离校年月可支持，退学/休学/肄业不能支持。旧 matcher-v2 的属性回放语义不变。
- 离校需要同一或相邻子句明确先完成课程；两者都有日期时，最晚课程完成日不能晚于最早离校日。完成时间待定、晚于离校或矛盾的完成说明不提供毕业证明。相邻“但实际已延期”“但尚未确认”“日期已经推迟”会使证明失效，无关的实习延期不影响毕业证明。
- 兼容“毕业（全日制）”等正常限定语及历史短日期引用：短引用的每个精确出现位置都必须对应同一事实证据中明确的毕业事件。不能借用别处的毕业字样把课程日期变成毕业年份，也不自动改写旧引用；仅修改概述的合法旧档案仍可保存。
- 提供到岗日期必须是相对冻结资料截止月仍有效的明确安排；过去月份的记录需重新确认，返回 unknown 并保留证据。同月、未来或 immediate 可以提供证明，但具体月份存在不证明能立即到岗。当前安排冲突仍需本人澄清；含阈值或不在词表的目标不适用此兼容路径。
- “英语财报阅读”与“英文财报阅读”是受控等价，自述仍为 partial；普通“英语”不证明财报阅读。肯定、否定冲突继续返回 unknown。

- 立即到岗属性需关联原文明确承诺，并核对同一事实完整证据中的等待期/否定；“每周三天到岗”是出勤频率，不是等待三天。无法确认时省略属性，不能凭“到岗”短引用计为立即到岗。
- 同一事实、同一来源及来源类型拆开的毕业延期/未确认说明仍参与校验；不同学历的日期按各自毕业事件归属，不因同句含两个年份误判冲突。
- JD 中被误归为职业证书的 MBA/MSc 条件转人工核对，只转换受影响的备选分支。`CFA OR MBA` 中 CFA 完整资格仍可满足；未满足自动分支、人工分支仍待核对时为 unknown/manual_review，不进入自动分母。受影响的 same_fact 合取整体转人工，避免用不同事实拼接；原 JD 保留供核对。已被明确否定的合取不触发此豁免；冲突仍优先处理。旧 matcher-v2 回放语义不变。

实现与验证边界见 [报告可靠性修复](team/structured-output-reliability-2026-11-06.md)。


## v2 当前口径

v2 作为历史版本保留；新诊断使用 v3。历史快照保持原样，可按记录版本离线重算。评分不是能力评价或录用概率。

### 结构化条件与证据

- Fact 新增可选 `attributes`（name/value/quote）；每条属性引用必须属于该事实关联的原文证据。学校、专业、届别、在读状态、经历类型/领域、证书进度、未来可到岗安排分别存储。新增 kind=`credential`、`availability`。旧档案缺少属性时不猜值。
- Requirement 新增 operator=`criteria` 和 `condition.any_of[].all_of[]`。最多 12 个方案、每方案 12 个条件；任一方案全部满足即可；整条要求只计一次权重。`scope=same_fact` 禁止拼接不同学历/经历凑资格，`profile` 可使用多个事实。两种 scope 都检查整份档案的当前到岗承诺冲突（天数、月数、月份及全职），保留冲突双方证据；同事实限制不能隐藏其他当前记录。不同学历/经历的正常差异不按当前承诺冲突处理。
- 子条件支持技能、资格、专业/院校、毕业年份/在读、经历类型/领域、每周天数/连续月数/到岗月份/全职。比较方式与字段类别须一致；条件的 quote 必须属于该项 JD 原文。
- 证书 `any_pass` 接受 partial/complete，`complete` 只接受完整资格；preparing/expired 不算通过。备选证书共享一条权重。证书名带有单独记录的明确阶段后缀时，可支持母项 any_pass；完成某阶段不等于完整取得母项资格。
- Office、Adobe Creative Cloud 等受控套件与组成工具不是等价词；组成工具只给 partial。明确技能应用仍为 met，自述为 partial；不使用子串/模糊相似度推断技能。
- `same_fact` 同样保留整份档案中同一规范化技能/证书的肯定、否定及证书进度冲突，返回 unknown/conflicting_evidence 并附双方证据；单条满足记录不能覆盖矛盾。不同名称、不同学历/经历的正常差异保持独立，另一项备选资格独立满足时仍可 met。
- 未来可连续任职月数不能用历史实习时长代替。数字缺失保持 unknown；暑期等模糊安排不得转换成具体到岗月份。
- `availability_start=immediate` 与具体月份作 eq/gte/lte 比较时，只在比较中归一为冻结的 `profile.as_of_month`，不读取运行当天日期，也不改写原属性。立即到岗和同一冻结月份不是互相冲突的两条月份记录。JD 要求明确立即到岗时，只有 immediate 承诺可确认满足；仅写当前或过去月份仍为 unknown，明确未来月份为 unmet。
- 新写入的同一学历不允许 `completed=true` 与 `enrollment=enrolled`、`completed=false` 与 `enrollment=completed`，也不允许同时写两个互斥 enrollment 值；前端、提取和保存校验均提示核对，不自动改写原文。只有一方未知时不补猜。历史冲突资料在 matcher-v2 中对在读条件保留 unknown/conflicting_evidence，也不能凭该矛盾事实证明已完成学历；另有无矛盾学历独立满足时仍可 met。历史 matcher-v1 不变。
- 同一事实互相矛盾的属性、届别与教育结束年份冲突、当前到岗安排冲突均保留证据并要求澄清。如果届别与教育结束年份虽不同、却都达到本项毕业年份门槛，则该门槛可确定为 met，理由仍提示日期须核对；不能据此确认在读状态。人工校名评价、软性评价、未说明领域的“相关行业”不由规则代判。

### 状态与分母

v2 保留 met/partial/unmet/unknown 及 1/0.5/0/0 系数。AND：unmet 优先，其次 unknown、partial、met；OR：任一 met 即 met，其次 partial，否则有 unknown 则 unknown，全部 unmet 才 unmet。

unknown 增加 `unknown_reason`：missing_evidence（缺明确字段）、conflicting_evidence（有冲突）、manual_review（人工评价）、unsupported_condition（规则不支持）。不能把后两者描述成“简历没写”。

`counted_in_score=false` 只允许用于 unknown 且原因是 manual_review/unsupported_condition；这些项目保留展示，但不纳入自动分母。缺证据、冲突和明确不满足仍计入分母。must=2、preferred=1、四舍五入方式沿用 v1。

`score = ROUND_HALF_UP(100 × Σ计分项目(weight × coefficient) / Σ计分项目weight, 1)`。
`scorable_weight_ratio = Σ计分项目weight / Σ全部非 ignored 项目weight`，保留四位。
`unknown_weight_ratio` 仍按所有非 ignored 要求计算，人工项也在其中。两个比例含义不同，均需显示。
全部为人工项时保存 score=0、scorable_weight_ratio=0，界面显示“暂不可评分”，不能把 0 当成候选人零分。没有任何非 ignored 项仍拒绝诊断。

v2 保存前按冻结材料重算核对，拒绝伪造分数或缩小分母。条件去重忽略方案顺序、标题和引用措辞；语义相同的条件不得重复计权。

## v1 历史规则（不改写旧快照）


## 基本口径

算法输出 `score` 0–100，表示已提供材料对该 JD 可评分要求的覆盖程度。不预测录用概率，不为岗位自动补充未写出的要求，不因没写某技能断言不会。
AI 可提取要求和事实；用户确认后，M4 以固定 matcher_version 与 rule_version 计算。v1 不使用实时大模型或 embedding 参与匹配，以保证可离线测试。

## 要求与证据

每项要求有唯一 ID、JD 原文、类别 skill/experience/education/project/other、重要性 must/preferred、operator、target 与 subject。min_months 的 subject 是相关事实标签，其余 operator 的 subject 为 null。
operator：has_skill（规范化同义词匹配）、min_months（相关经历区间并集月数）、degree_at_least（明确学历序列）、has_evidence（需要匹配的明确事实标签）、manual_review（v1 无法可靠计算，unknown）。
不适合评分的个人属性标记 ignored=true，保留 reason；不进入分母。软技能没有可核验行为标签时 manual_review，不能关键词出现就满分。
受控词典只做等价名，如 JS→JavaScript、Postgres→PostgreSQL；Python 不等于机器学习。词典也有版本，随 matcher_version 发布。
事实采用 kind、label、value、start_month/end_month、evidence_ids；工作月份计法见数据字典。日期未明确或不能确定相关性时 unknown。

## 四种状态

| 状态 | 系数 | 判定 |
|---|---:|---|
| met | 1 | 有充分直接证据满足条件 |
| partial | 0.5 | 技能仅自述、没有应用证据；或最低月数达到要求的 50% 但不足全部 |
| unmet | 0 | 用户明确否认，或明确数值低于最低值且低于 50%；学历低于要求 |
| unknown | 0 | 没有证据、日期不完整、冲突尚未解决、manual_review |

has_skill：有项目/工作应用事实且引用原文 → met；只有技能清单自述 → partial；明确否认 → unmet；否则 unknown。
has_evidence：已确认事实标签完全/受控等价对应 → met；明确否认 → unmet；否则 unknown；v1 不用 partial。
degree_at_least：associate < bachelor < master < doctorate；completed=true 的最高明确学历参与，在读且 JD 没明确接受在读则 unknown；低于要求 unmet。
min_months：只能累计 label 与 requirement.subject 经受控词典等价的 experience/project 事实的确认区间，月区间 [start_month,end_month) 并集，不能重复累计并行项目。未结束经历先把 end_month 固定为 profile.as_of_month，避免历史分数随时间漂移。实际月数≥阈值 met；≥阈值/2 partial；低于阈值/2 unmet；缺少完整区间 unknown。
互相矛盾的肯定/否定证据统一 unknown，附 conflict 提示，不静默选择。

## 公式

每条 must 权重 2，preferred 权重 1。v1 不额外叠加维度权重、不做硬门槛封顶。

`score = ROUND_HALF_UP(100 × Σ(weight_i × coefficient_i) / Σ(weight_i), 1)`

只对 ignored=false 的要求求和；unknown 仍在分母。`unknown_weight_ratio = Σunknown 权重 / Σ总权重`，范围 0–1、保留 4 位；该字段不是概率。
类别分数用本类别同一公式计算，没有可评分要求则不输出该类别。总分不能简单平均类别分数。
总分母=0：拒绝诊断该 JD，返回 NO_SCORABLE_REQUIREMENTS（422），请用户修改要求。
所有 must 中的 unmet 标为 explicit_gap，unknown 标为 needs_evidence，partial 标为 partial_gap；不自动判“不能投递”。

## 手算基准

| ID | 重要性 | 状态 | 权重×系数 |
|---|---|---|---:|
| r1 Python 项目使用 | must | met | 2 |
| r2 SQL 应用能力 | must | partial | 1 |
| r3 Docker | preferred | unknown | 0 |
| r4 本科及以上 | preferred | met | 1 |

总权重 6，分子 4，总分 **66.7**；未知权重比例 **0.1667**。skill 类为 60.0（3/5），education 为 100.0（1/1）。这是测试固定值，示例 JSON 应保持一致。

## 版本与稳定性

score 记录 rule_version=`coverage-v1`、matcher_version=`matcher-v1`；每项保存 coefficient、weight、evidence_ids、reason。规则变化生成新版本，不能重写旧报告。
同一要求列表重排不改变分数；重复的相同要求在 JD 确认前合并，避免重复加权；不同 JD 从不混算。重复识别使用规范化 operator/target/subject/category 键，若重要性冲突保留 must 并提示用户确认。
