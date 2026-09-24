# 匹配算法 v1：证据覆盖评分

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
