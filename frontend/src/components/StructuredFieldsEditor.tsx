import type { Fact, Requirement } from '../types';
import { comparisonOptions } from '../structuredFields';

type Attribute = NonNullable<Fact['attributes']>[number];
type Condition = NonNullable<Requirement['condition']>;
type Criterion = Condition['any_of'][number]['all_of'][number];
export const fieldLabels: Record<string, string> = {
  skill: '技能',
  credential: '证书 / 考试',
  major: '专业',
  institution: '院校',
  graduation_year: '毕业年份',
  enrollment: '在读 / 毕业状态',
  experience_type: '经历类型',
  experience_domain: '经历领域',
  credential_status: '证书通过状态',
  credential_level: '考试级别',
  availability_days: '每周可到岗天数',
  availability_months: '可连续任职月数',
  availability_start: '可到岗月份',
  full_time: '可全职',
  manual: '需人工判断',
};
const attributesByKind: Record<Fact['kind'], Attribute['name'][]> = {
  education: ['institution', 'major', 'graduation_year', 'enrollment'],
  experience: ['experience_type', 'experience_domain'],
  project: ['experience_domain'],
  credential: ['credential_status', 'credential_level'],
  availability: ['availability_days', 'availability_months', 'availability_start', 'full_time'],
  skill: [],
};
const choices: Record<string, Record<string, string>> = {
  enrollment: { enrolled: '在读', completed: '已毕业' },
  experience_type: { internship: '实习', employment: '工作', volunteer: '志愿服务' },
  credential_status: {
    partial: '部分考试通过',
    complete: '完整取得资格',
    preparing: '备考 / 报名',
    expired: '已失效',
  },
  full_time: { true: '可以全职', false: '不能全职' },
};
function ValueInput({
  field,
  value,
  onChange,
}: {
  field: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return choices[field] ? (
    <select aria-label="条件值" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">请选择</option>
      {Object.entries(choices[field]).map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  ) : (
    <input
      aria-label="条件值"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={
        field === 'availability_start'
          ? 'YYYY-MM，或 immediate（明确可立即到岗）'
          : '仅填写原文明确信息'
      }
    />
  );
}
export function AttributeEditor({
  fact,
  onChange,
}: {
  fact: Fact;
  onChange: (v: Attribute[]) => void;
}) {
  const fields = attributesByKind[fact.kind];
  const attributes = fact.attributes ?? [];
  if (!fields.length) return null;
  return (
    <fieldset className="evidence-choices">
      <legend>可核对信息</legend>
      <p className="muted">每项信息都需关联原文；引用须包含在此事实勾选的证据中。</p>
      {attributes.map((a, i) => (
        <div className="form-grid three" key={i}>
          <label className="field">
            信息类型
            <select
              value={a.name}
              onChange={(e) =>
                onChange(
                  attributes.map((x, n) =>
                    n === i ? { ...x, name: e.target.value as Attribute['name'], value: '' } : x,
                  ),
                )
              }
            >
              {fields.map((f) => (
                <option key={f} value={f}>
                  {fieldLabels[f]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            明确取值
            <ValueInput
              field={a.name}
              value={a.value}
              onChange={(v) =>
                onChange(attributes.map((x, n) => (n === i ? { ...x, value: v } : x)))
              }
            />
          </label>
          <label className="field">
            支持此信息的原文
            <textarea
              value={a.quote}
              onChange={(e) =>
                onChange(attributes.map((x, n) => (n === i ? { ...x, quote: e.target.value } : x)))
              }
            />
          </label>
          <button
            className="text-button"
            type="button"
            onClick={() => onChange(attributes.filter((_, n) => n !== i))}
          >
            移除此信息
          </button>
        </div>
      ))}
      <button
        className="button secondary small"
        type="button"
        disabled={attributes.length >= 24}
        onClick={() => onChange([...attributes, { name: fields[0], value: '', quote: '' }])}
      >
        添加可核对信息
      </button>
    </fieldset>
  );
}
const fields: Criterion['field'][] = [
  'skill',
  'credential',
  'major',
  'graduation_year',
  'enrollment',
  'institution',
  'experience_type',
  'experience_domain',
  'availability_days',
  'availability_months',
  'availability_start',
  'full_time',
  'manual',
];
const comparisons: Record<Criterion['comparison'], string> = {
  eq: '等于 / 对应',
  gte: '至少',
  lte: '至多',
  exists: '有明确记录',
  any_pass: '允许部分通过',
  complete: '要求完整资格',
};
const blank = (quote: string): Criterion => ({
  field: 'skill',
  comparison: 'eq',
  value: '',
  quote,
});
export function ConditionEditor({
  value,
  quote,
  onChange,
}: {
  value: Condition;
  quote: string;
  onChange: (v: Condition) => void;
}) {
  const update = (g: number, c: number, patch: Partial<Criterion>) =>
    onChange({
      any_of: value.any_of.map((group, i) =>
        i === g
          ? {
              ...group,
              all_of: group.all_of.map((criterion, j) =>
                j === c ? { ...criterion, ...patch } : criterion,
              ),
            }
          : group,
      ),
    });
  return (
    <fieldset className="evidence-choices">
      <legend>满足下列任一方案即可（整项只计一次权重）</legend>
      {value.any_of.map((group, g) => (
        <section className="editor-card" key={g} aria-label={`备选方案 ${g + 1}`}>
          <strong>方案 {g + 1}：以下条件全部满足</strong>
          <label className="field">
            证据关联
            <select
              value={group.scope}
              onChange={(e) =>
                onChange({
                  any_of: value.any_of.map((x, i) =>
                    i === g ? { ...x, scope: e.target.value as typeof group.scope } : x,
                  ),
                })
              }
            >
              <option value="profile">可以来自不同经历</option>
              <option value="same_fact">必须来自同一段学历 / 经历</option>
            </select>
          </label>
          {group.all_of.map((c, i) => (
            <div className="form-grid three" key={i}>
              <label className="field">
                核对内容
                <select
                  value={c.field}
                  onChange={(e) =>
                    update(g, i, {
                      field: e.target.value as Criterion['field'],
                      comparison: e.target.value === 'credential' ? 'any_pass' : 'eq',
                      value: '',
                    })
                  }
                >
                  {fields.map((f) => (
                    <option key={f} value={f}>
                      {fieldLabels[f]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                满足方式
                <select
                  value={c.comparison}
                  onChange={(e) =>
                    update(g, i, {
                      comparison: e.target.value as Criterion['comparison'],
                      ...(e.target.value === 'exists' ? { value: c.field } : {}),
                    })
                  }
                >
                  {comparisonOptions(c.field).map((v) => (
                    <option key={v} value={v}>
                      {comparisons[v]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                要求值
                <ValueInput
                  field={c.field}
                  value={c.value}
                  onChange={(v) => update(g, i, { value: v })}
                />
              </label>
              <label className="field">
                子条件原文
                <textarea
                  value={c.quote}
                  onChange={(e) => update(g, i, { quote: e.target.value })}
                />
              </label>
              <button
                className="text-button"
                type="button"
                disabled={group.all_of.length === 1}
                onClick={() =>
                  onChange({
                    any_of: value.any_of.map((x, n) =>
                      n === g ? { ...x, all_of: x.all_of.filter((_, j) => j !== i) } : x,
                    ),
                  })
                }
              >
                移除此条件
              </button>
            </div>
          ))}
          <button
            className="button secondary small"
            type="button"
            disabled={group.all_of.length >= 12}
            onClick={() =>
              onChange({
                any_of: value.any_of.map((x, i) =>
                  i === g ? { ...x, all_of: [...x.all_of, blank(quote)] } : x,
                ),
              })
            }
          >
            增加同时满足的条件
          </button>
          <button
            className="text-button"
            type="button"
            disabled={value.any_of.length === 1}
            onClick={() => onChange({ any_of: value.any_of.filter((_, i) => i !== g) })}
          >
            移除此方案
          </button>
        </section>
      ))}
      <button
        className="button secondary small"
        type="button"
        disabled={value.any_of.length >= 12}
        onClick={() =>
          onChange({ any_of: [...value.any_of, { scope: 'profile', all_of: [blank(quote)] }] })
        }
      >
        增加另一可选方案
      </button>
    </fieldset>
  );
}
