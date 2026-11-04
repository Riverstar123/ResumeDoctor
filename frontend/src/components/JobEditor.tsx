import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { useAction } from '../hooks';
import type { Job, Requirement } from '../types';
import { validateJob, type Issues } from '../validation';
import { ErrorNotice, ValidationErrors, labels } from './ui';

const operators: Record<Requirement['operator'], string> = {
  has_skill: '技能应用',
  min_months: '最低相关月数',
  degree_at_least: '最低学历',
  has_evidence: '明确事实证据',
  manual_review: '待人工核对',
};
function focusEditorTarget(element: HTMLElement | null) {
  if (!element) return;
  const details = element.closest('details');
  if (details) details.open = true;
  element.focus({ preventScroll: true });
  element.scrollIntoView({
    block: 'start',
    behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
  });
}
export function JobEditor({
  initial,
  onSaved,
  onDirty,
  actionsContainer,
}: {
  initial: Job;
  onSaved: (job: Job) => void;
  onDirty: (dirty: boolean) => void;
  actionsContainer?: HTMLElement | null;
}) {
  const [job, setJob] = useState(initial);
  const [content, setContent] = useState(structuredClone(initial.content));
  const [raw, setRaw] = useState(initial.raw_text);
  const [errors, setErrors] = useState<Issues>({});
  const [latest, setLatest] = useState<Job>();
  const validationRef = useRef<HTMLDivElement>(null);
  const latestRef = useRef<HTMLDivElement>(null);
  const action = useAction();
  const dirty = raw !== job.raw_text || JSON.stringify(content) !== JSON.stringify(job.content);
  const errorCount = Object.keys(errors).length;
  useEffect(() => {
    if (Object.keys(errors).length) focusEditorTarget(validationRef.current);
  }, [errors]);
  useEffect(() => {
    if (latest) focusEditorTarget(latestRef.current);
  }, [latest]);
  const change = (next: Job['content']) => {
    setContent(next);
    onDirty(raw !== job.raw_text || JSON.stringify(next) !== JSON.stringify(job.content));
  };
  const update = (i: number, patch: Partial<Requirement>) =>
    change({
      ...content,
      requirements: content.requirements.map((r, n) => (n === i ? { ...r, ...patch } : r)),
    });
  const accept = (next: Job) => {
    setJob(next);
    setContent(structuredClone(next.content));
    setRaw(next.raw_text);
    onDirty(false);
    onSaved(next);
  };
  const save = () => {
    const problems = validateJob(raw, content);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void action.run(async () =>
      accept(await api.saveJob(job.id, { base_version: job.version, raw_text: raw, content })),
    );
  };
  const confirm = () => {
    const problems = validateJob(raw, content);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void action.run(async () => accept(await api.confirmJob(job.id, job.version)));
  };
  const actions = (
    <div className="job-editor-actions">
      <ErrorNotice error={action.error} />
      <div className="editor-footer">
        <div className="job-editor-action-status">
          <strong>
            {content.title || '当前岗位'} · v{job.version}
          </strong>
          <p>
            {dirty
              ? '修改后须先保存新版本，再重新确认。'
              : job.confirmed
                ? '此版本已确认，可用于诊断。'
                : '请核对原文、类别与重要性后确认。'}
          </p>
          {errorCount > 0 && (
            <button
              className="text-button"
              onClick={() => focusEditorTarget(validationRef.current)}
            >
              查看 {errorCount} 处待修正内容
            </button>
          )}
        </div>
        <div className="actions">
          <button
            className="button secondary"
            disabled={!dirty || action.busy || action.cooldown > 0}
            onClick={save}
          >
            保存 JD 新版本
          </button>
          <button
            className="button"
            disabled={dirty || job.confirmed || action.busy || action.cooldown > 0}
            onClick={confirm}
          >
            确认 JD v{job.version}
          </button>
        </div>
      </div>
    </div>
  );
  return (
    <section className="panel job-editor">
      <div className="section-heading">
        <div>
          <p className="eyebrow">岗位要求核对</p>
          <h2>{job.content.title}</h2>
        </div>
        <span className="tag">
          v{job.version} · {dirty ? '有未保存修改' : job.confirmed ? '已确认' : '待确认'}
        </span>
      </div>
      <p className="notice">
        公司背景只作解释补充。每条计分要求必须来自 JD
        原文；个人属性等不适宜计分的要求请忽略并说明原因。
      </p>
      {errorCount > 0 && (
        <div
          className="job-editor-validation"
          ref={validationRef}
          tabIndex={-1}
          aria-label="岗位校验问题"
          onClick={(event) => {
            const link =
              event.target instanceof Element
                ? event.target.closest<HTMLAnchorElement>('a[href^="#"]')
                : null;
            const field = link && document.getElementById(link.hash.slice(1));
            if (field) {
              event.preventDefault();
              focusEditorTarget(field);
            }
          }}
        >
          <ValidationErrors errors={errors} />
        </div>
      )}
      <fieldset className="editor-fields" disabled={action.busy}>
        <div className="form-grid">
          <label className="field">
            岗位名称
            <input
              id="title"
              maxLength={200}
              value={content.title}
              onChange={(e) => change({ ...content, title: e.target.value })}
            />
          </label>
          <label className="field">
            公司名称（可选）
            <input
              value={content.company_name || ''}
              onChange={(e) => change({ ...content, company_name: e.target.value || null })}
            />
          </label>
        </div>
        <details>
          <summary>查看 / 编辑 JD 原文与公司背景</summary>
          <label className="field">
            JD 原文
            <textarea
              id="raw_text"
              rows={5}
              maxLength={20000}
              value={raw}
              onChange={(e) => {
                setRaw(e.target.value);
                onDirty(
                  e.target.value !== job.raw_text ||
                    JSON.stringify(content) !== JSON.stringify(job.content),
                );
              }}
            />
          </label>
          <label className="field">
            公司背景
            <textarea
              id="company_context"
              rows={3}
              maxLength={10000}
              value={content.company_context}
              onChange={(e) => change({ ...content, company_context: e.target.value })}
            />
          </label>
        </details>
        <div className="section-heading" id="requirements" tabIndex={-1}>
          <h3>
            岗位要求 <span className="count">{content.requirements.length}</span>
          </h3>
          <button
            className="button secondary small"
            disabled={content.requirements.length >= 100}
            onClick={() =>
              change({
                ...content,
                requirements: [
                  ...content.requirements,
                  {
                    id: `r-${crypto.randomUUID()}`,
                    quote: '',
                    category: 'other',
                    importance: 'must',
                    operator: 'manual_review',
                    target: '',
                    subject: null,
                    ignored: false,
                    ignore_reason: null,
                  },
                ],
              })
            }
          >
            ＋ 添加要求
          </button>
        </div>
        {content.requirements.map((r, i) => (
          <article
            className={`editor-card ${r.ignored ? 'ignored' : ''}`}
            key={r.id}
            id={`requirements.${i}`}
            tabIndex={-1}
            aria-label={`要求 ${i + 1}`}
          >
            <div className="row">
              <span className="eyebrow">
                要求 {String(i + 1).padStart(2, '0')} · {r.id}
              </span>
              <button
                className="text-button destructive"
                onClick={() =>
                  change({
                    ...content,
                    requirements: content.requirements.filter((_, n) => n !== i),
                  })
                }
              >
                删除要求 {i + 1}
              </button>
            </div>
            <label className="field">
              JD 原文引用
              <textarea
                id={`requirements.${i}.quote`}
                rows={2}
                value={r.quote}
                onChange={(e) => update(i, { quote: e.target.value })}
              />
            </label>
            <div className="form-grid three">
              <label className="field">
                类别
                <select
                  value={r.category}
                  onChange={(e) =>
                    update(i, { category: e.target.value as Requirement['category'] })
                  }
                >
                  {['skill', 'experience', 'education', 'project', 'other'].map((c) => (
                    <option value={c} key={c}>
                      {labels[c]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                重要性
                <select
                  value={r.importance}
                  onChange={(e) =>
                    update(i, { importance: e.target.value as Requirement['importance'] })
                  }
                >
                  <option value="must">必须 · 权重 2</option>
                  <option value="preferred">优先 · 权重 1</option>
                </select>
              </label>
              <label className="field">
                核对方式
                <select
                  value={r.operator}
                  onChange={(e) =>
                    update(i, {
                      operator: e.target.value as Requirement['operator'],
                      subject: e.target.value === 'min_months' ? '' : null,
                    })
                  }
                >
                  {Object.entries(operators).map(([v, l]) => (
                    <option value={v} key={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                匹配目标
                <input
                  id={`requirements.${i}.target`}
                  value={r.target}
                  onChange={(e) => update(i, { target: e.target.value })}
                />
              </label>
              {r.operator === 'min_months' && (
                <label className="field">
                  相关领域 / 技能
                  <input
                    value={r.subject || ''}
                    onChange={(e) => update(i, { subject: e.target.value })}
                  />
                </label>
              )}
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={r.ignored}
                onChange={(e) =>
                  update(i, {
                    ignored: e.target.checked,
                    ignore_reason: e.target.checked ? r.ignore_reason || '' : null,
                  })
                }
              />
              忽略此要求，不纳入评分
            </label>
            {r.ignored && (
              <label className="field">
                忽略原因
                <input
                  id={`requirements.${i}.ignore_reason`}
                  value={r.ignore_reason || ''}
                  onChange={(e) => update(i, { ignore_reason: e.target.value })}
                />
              </label>
            )}
          </article>
        ))}
      </fieldset>
      <button
        className="text-button"
        disabled={action.busy}
        onClick={() => void action.run(async () => setLatest(await api.job(job.id)))}
      >
        读取最新 JD 版本
      </button>
      {latest && (
        <div className="notice" ref={latestRef} tabIndex={-1}>
          <strong>
            服务端 v{latest.version} · {latest.content.title}
          </strong>
          <p>{latest.content.requirements.length} 条要求。替换将放弃未保存的本地修改。</p>
          <button
            className="button secondary small"
            onClick={() => {
              accept(latest);
              setLatest(undefined);
              setErrors({});
              action.clearError();
            }}
          >
            用最新版本替换本地 JD
          </button>
        </div>
      )}
      {actionsContainer ? createPortal(actions, actionsContainer) : actions}
    </section>
  );
}
