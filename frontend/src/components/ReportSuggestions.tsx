import { useId, useState, type ReactNode } from 'react';
import type { Schema } from '../types';

type Props = {
  selectionKey: string;
  suggestions: Schema['Suggestion'][];
  renderEvidence: (ids: string[]) => ReactNode;
};
type CopyTarget = number | 'checklist';

export function ReportSuggestions(props: Props) {
  // Polling can recreate the same data; reset only when the item or suggestion content changes.
  return (
    <SuggestionList key={JSON.stringify([props.selectionKey, props.suggestions])} {...props} />
  );
}

function SuggestionList({ suggestions, renderEvidence }: Props) {
  const checklistId = useId();
  const [selected, setSelected] = useState<number[]>([]);
  const [copyStatus, setCopyStatus] = useState<{
    message: string;
    failed: boolean;
    target: CopyTarget;
  } | null>(null);
  const [copyingTarget, setCopyingTarget] = useState<CopyTarget | null>(null);
  const copying = copyingTarget !== null;
  const available = suggestions.flatMap((suggestion, index) =>
    suggestion.requires_user_input ? [] : [index],
  );
  const chosen = suggestions.filter(
    (suggestion, index) => !suggestion.requires_user_input && selected.includes(index),
  );
  const checklist = chosen
    .map((suggestion, index) => `${index + 1}. ${suggestion.revised}`)
    .join('\n\n');

  function select(indices: number[]) {
    if (copying) return;
    setSelected(indices);
    setCopyStatus(null);
  }

  async function copy(text: string, target: CopyTarget) {
    setCopyingTarget(target);
    setCopyStatus(null);
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus({ message: '已复制，请核对后使用。', failed: false, target });
    } catch {
      setCopyStatus({
        message: '无法复制，请手动选取建议或修改清单中的文字。',
        failed: true,
        target,
      });
    } finally {
      setCopyingTarget(null);
    }
  }

  function copyFeedback(target: CopyTarget) {
    if (copyStatus?.target !== target) return null;
    return (
      <p
        className={`notice suggestion-copy-status${copyStatus.failed ? ' warning' : ''}`}
        role={copyStatus.failed ? 'alert' : 'status'}
      >
        {copyStatus.message}
      </p>
    );
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">REWRITE / 修改建议</p>
          <h2>让真实经历更有说服力</h2>
        </div>
      </div>
      {!suggestions.length ? (
        <p className="empty-inline">本报告未列出改写建议。</p>
      ) : (
        <>
          <div className="suggestion-toolbar">
            <p>
              可审阅采用 {available.length} 条 · 待补充事实 {suggestions.length - available.length}{' '}
              条
            </p>
            <p className="hint">
              核对建议后加入本次修改清单。选择不会修改经历档案或评分，切换岗位或离开报告后清空。
            </p>
            <div className="suggestion-checklist-actions">
              <button
                type="button"
                className="button secondary small"
                disabled={copying || !available.length || chosen.length === available.length}
                onClick={() => select(available)}
              >
                全选可用建议
              </button>
              <button
                type="button"
                className="button secondary small"
                disabled={copying || !chosen.length}
                onClick={() => select([])}
              >
                清空选择
              </button>
            </div>
          </div>
          {suggestions.map((suggestion, index) => (
            <article className="suggestion" key={`${suggestion.requirement_id}-${index}`}>
              <div className="row">
                <small>
                  建议 {index + 1} · 关联要求 {suggestion.requirement_id}
                </small>
                <span
                  className={`badge status-${suggestion.requires_user_input ? 'unknown' : 'met'}`}
                >
                  {suggestion.requires_user_input ? '待补充事实' : '可审阅采用'}
                </span>
              </div>
              {!suggestion.requires_user_input && (
                <label className="suggestion-select">
                  <input
                    type="checkbox"
                    disabled={copying}
                    checked={selected.includes(index)}
                    aria-label={`加入修改清单：建议 ${index + 1}`}
                    onChange={(event) =>
                      select(
                        event.target.checked
                          ? [...selected, index]
                          : selected.filter((i) => i !== index),
                      )
                    }
                  />
                  加入本次修改清单
                </label>
              )}
              <div className="rewrite-grid">
                <div>
                  <h3>原文</h3>
                  <p>{suggestion.original || '没有可引用的原文'}</p>
                </div>
                <div className="revised">
                  <h3>{suggestion.requires_user_input ? '待补充的表达模板' : '建议表达'}</h3>
                  <p>{suggestion.revised}</p>
                  {!suggestion.requires_user_input && (
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={copying}
                      aria-label={`复制建议 ${index + 1}`}
                      onClick={() => void copy(suggestion.revised, index)}
                    >
                      {copyingTarget === index ? '正在复制…' : '复制这条建议'}
                    </button>
                  )}
                  {copyFeedback(index)}
                </div>
              </div>
              <p className="hint">修改依据：{suggestion.rationale}</p>
              {suggestion.requires_user_input && (
                <p className="notice warning">
                  这条建议需要补充真实信息，不能直接作为完成稿。仅填写确实做过且可核实的内容；
                  下一步请回到经历档案补充事实并确认，再到目标岗位页开始新诊断。原报告保留原来的资料快照。
                </p>
              )}
              <details>
                <summary>查看建议引用证据</summary>
                {renderEvidence(suggestion.evidence_ids)}
              </details>
            </article>
          ))}
          <section className="suggestion-checklist" aria-labelledby={checklistId}>
            <div className="section-heading">
              <h3 id={checklistId}>本次修改清单 · 已选 {chosen.length} 条</h3>
              <button
                type="button"
                className="button small"
                disabled={!chosen.length || copying}
                onClick={() => void copy(checklist, 'checklist')}
              >
                {copyingTarget === 'checklist' ? '正在复制…' : '复制修改清单'}
              </button>
            </div>
            {copyFeedback('checklist')}
            {chosen.length ? (
              <textarea
                readOnly
                aria-label="本次修改清单内容"
                value={checklist}
                rows={Math.min(12, chosen.length * 3 + 1)}
              />
            ) : (
              <p className="hint">
                {available.length
                  ? '尚未选择建议。核对并勾选可审阅采用的建议后，可在这里汇总复制。'
                  : '当前建议均需先补充事实，暂不能加入修改清单。'}
              </p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
