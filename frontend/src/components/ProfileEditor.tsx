import type { Fact, ProfileContent } from '../types';
import { currentMonth } from '../validation';
import { labels } from './ui';

export function ProfileEditor({
  value,
  onChange,
  disabled,
}: {
  value: ProfileContent;
  onChange: (v: ProfileContent) => void;
  disabled: boolean;
}) {
  const updateFact = (index: number, patch: Partial<Fact>) =>
    onChange({
      ...value,
      facts: value.facts.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    });
  const addEvidence = () =>
    onChange({
      ...value,
      evidence: [
        ...value.evidence,
        {
          id: `e-${crypto.randomUUID()}`,
          source_type: 'manual',
          source_id: `manual-${crypto.randomUUID()}`,
          quote: '',
          locator: null,
        },
      ],
    });
  return (
    <fieldset className="editor-fields" disabled={disabled}>
      <div className="form-grid">
        <label className="field grow">
          经历概述
          <textarea
            id="overview"
            rows={3}
            maxLength={8000}
            value={value.overview}
            onChange={(e) => onChange({ ...value, overview: e.target.value })}
          />
        </label>
        <label className="field">
          资料截止月份
          <input
            id="as_of_month"
            type="month"
            max={currentMonth()}
            value={value.as_of_month}
            onChange={(e) => onChange({ ...value, as_of_month: e.target.value })}
          />
          <small>在职经历的结束月份请确认到这一时点。</small>
        </label>
      </div>
      <div className="section-heading" id="facts">
        <h2>
          结构化事实 <span className="count">{value.facts.length}</span>
        </h2>
        <button
          className="button secondary small"
          disabled={value.facts.length >= 100}
          onClick={() =>
            onChange({
              ...value,
              facts: [
                ...value.facts,
                {
                  id: `f-${crypto.randomUUID()}`,
                  kind: 'project',
                  label: '',
                  value: null,
                  polarity: 'positive',
                  application: 'claimed',
                  start_month: null,
                  end_month: null,
                  completed: null,
                  evidence_ids: [],
                },
              ],
            })
          }
        >
          ＋ 添加事实
        </button>
      </div>
      {!value.facts.length && (
        <p className="notice">
          还没有事实。先添加原文证据，再添加事实并建立关联；也可以通过下方对话补充。
        </p>
      )}
      {value.facts.map((fact, i) => (
        <article className="editor-card" key={fact.id} aria-label={`事实 ${i + 1}`}>
          <div className="row">
            <span className="eyebrow">
              事实 {String(i + 1).padStart(2, '0')} · {labels[fact.kind]}
            </span>
            <button
              className="text-button destructive"
              onClick={() => onChange({ ...value, facts: value.facts.filter((_, n) => n !== i) })}
            >
              删除事实 {i + 1}
            </button>
          </div>
          <div className="form-grid three">
            <label className="field">
              类别
              <select
                value={fact.kind}
                onChange={(e) =>
                  updateFact(i, {
                    kind: e.target.value as Fact['kind'],
                    value: null,
                  })
                }
              >
                {['skill', 'experience', 'education', 'project'].map((k) => (
                  <option key={k} value={k}>
                    {labels[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              事实标签
              <input
                id={`facts.${i}.label`}
                value={fact.label}
                placeholder="如 Python、后端开发"
                onChange={(e) => updateFact(i, { label: e.target.value })}
              />
            </label>
            <label className="field">
              {fact.kind === 'education' ? '学历' : '补充内容（未知可留空）'}
              {fact.kind === 'education' ? (
                <select
                  id={`facts.${i}.value`}
                  value={fact.value ?? ''}
                  onChange={(e) => updateFact(i, { value: e.target.value || null })}
                >
                  <option value="">未知 / 暂未提供</option>
                  {Object.entries({
                    associate: '专科',
                    bachelor: '本科',
                    master: '硕士',
                    doctorate: '博士',
                    other: '其他学历',
                  }).map(([v, name]) => (
                    <option key={v} value={v}>
                      {name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={fact.value || ''}
                  onChange={(e) => updateFact(i, { value: e.target.value || null })}
                />
              )}
            </label>
            <label className="field">
              陈述性质
              <select
                value={fact.polarity}
                onChange={(e) => updateFact(i, { polarity: e.target.value as Fact['polarity'] })}
              >
                <option value="positive">肯定陈述</option>
                <option value="negative">明确否认</option>
              </select>
            </label>
            <label className="field">
              应用程度
              <select
                value={fact.application}
                onChange={(e) =>
                  updateFact(i, { application: e.target.value as Fact['application'] })
                }
              >
                <option value="claimed">仅自述</option>
                <option value="applied">有实际应用</option>
              </select>
            </label>
            <label className="field">
              是否完成
              <select
                value={fact.completed === null ? 'unknown' : String(fact.completed)}
                onChange={(e) =>
                  updateFact(i, {
                    completed: e.target.value === 'unknown' ? null : e.target.value === 'true',
                  })
                }
              >
                <option value="unknown">未知</option>
                <option value="true">已完成</option>
                <option value="false">未完成 / 在读</option>
              </select>
            </label>
            <label className="field">
              开始月份
              <input
                type="month"
                id={`facts.${i}.dates`}
                value={fact.start_month || ''}
                onChange={(e) => updateFact(i, { start_month: e.target.value || null })}
              />
            </label>
            <label className="field">
              结束月份
              <input
                type="month"
                value={fact.end_month || ''}
                onChange={(e) => updateFact(i, { end_month: e.target.value || null })}
              />
            </label>
          </div>
          <fieldset className="evidence-choices" id={`facts.${i}.evidence_ids`}>
            <legend>关联原文证据（至少一条）</legend>
            {value.evidence.map((e) => (
              <label className="checkbox" key={e.id}>
                <input
                  type="checkbox"
                  checked={fact.evidence_ids.includes(e.id)}
                  onChange={(event) =>
                    updateFact(i, {
                      evidence_ids: event.target.checked
                        ? [...fact.evidence_ids, e.id]
                        : fact.evidence_ids.filter((id) => id !== e.id),
                    })
                  }
                />
                <span>
                  {e.id.slice(0, 12)} · {e.quote || '请先填写证据原文'}
                </span>
              </label>
            ))}
            {!value.evidence.length && <p>请先在下方添加证据。</p>}
          </fieldset>
        </article>
      ))}
      <div className="section-heading">
        <h2>
          原文证据 <span className="count">{value.evidence.length}</span>
        </h2>
        <button
          className="button secondary small"
          disabled={value.evidence.length >= 200}
          onClick={addEvidence}
        >
          ＋ 添加手动证据
        </button>
      </div>
      <p className="hint">原始文档与对话证据只读。纠正时请添加真实的手动证据，再更新事实关联。</p>
      {value.evidence.map((e, i) => (
        <div className="evidence-card" key={e.id}>
          <div className="row">
            <small>
              {e.id} · {e.source_type} · {e.locator || '未提供页段位置'}
            </small>
            <button
              className="text-button destructive"
              onClick={() =>
                onChange({
                  ...value,
                  evidence: value.evidence.filter((item) => item.id !== e.id),
                  facts: value.facts.map((f) => ({
                    ...f,
                    evidence_ids: f.evidence_ids.filter((id) => id !== e.id),
                  })),
                })
              }
            >
              删除证据 {i + 1}
            </button>
          </div>
          <label className="field">
            证据原文 {i + 1}
            <textarea
              id={`evidence.${i}`}
              readOnly={e.source_type !== 'manual'}
              rows={2}
              value={e.quote}
              onChange={(event) =>
                onChange({
                  ...value,
                  evidence: value.evidence.map((item) =>
                    item.id === e.id ? { ...item, quote: event.target.value } : item,
                  ),
                })
              }
            />
          </label>
          <small className="muted">来源：{e.source_id}</small>
        </div>
      ))}
    </fieldset>
  );
}
