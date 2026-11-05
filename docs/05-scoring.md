# 证据覆盖评分（当前 coverage-v2 / matcher-v2）

## v2 当前口径

新诊断使用 v2；历史 v1 快照保持原样，可离线重算。评分不是能力评价或录用概率。

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
