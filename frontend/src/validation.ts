import type { JobContent, ProfileContent } from './types';
export type Issues = Record<string, string>;
const month = /^\d{4}-(0[1-9]|1[0-2])$/;
export function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
export function emptyProfile(): ProfileContent {
  return { overview: '', as_of_month: currentMonth(), facts: [], evidence: [] };
}
export function validateFile(file: File) {
  if (file.size === 0) return '文件为空，请选择有内容的文字 PDF 或 DOCX。';
  if (file.size > 10 * 1024 * 1024) return '文件超过 10 MiB，请压缩或改用对话输入。';
  if (!/\.(pdf|docx)$/i.test(file.name))
    return '仅支持文字 PDF 和 DOCX，不支持 DOC、图片或扫描件。';
  return '';
}
export function validateProfile(content: ProfileContent): Issues {
  const errors: Issues = {};
  if (!month.test(content.as_of_month) || content.as_of_month > currentMonth())
    errors.as_of_month = '请选择不晚于当前月份的资料截止月份。';
  if (content.overview.length > 8000) errors.overview = '概述最多 8,000 字符。';
  if (content.facts.length > 100 || content.evidence.length > 200)
    errors.facts = '最多 100 条事实与 200 条证据。';
  const evidenceIds = new Set(content.evidence.map((e) => e.id));
  if (
    evidenceIds.size !== content.evidence.length ||
    new Set(content.facts.map((f) => f.id)).size !== content.facts.length
  )
    errors.facts = '事实和证据 ID 不得重复。';
  content.evidence.forEach((e, i) => {
    if (!e.quote.trim() || !e.id.trim() || !e.source_id.trim())
      errors[`evidence.${i}`] = '证据原文、来源与 ID 不能为空。';
  });
  content.facts.forEach((f, i) => {
    if (!f.label.trim()) errors[`facts.${i}.label`] = '请填写事实标签。';
    if (!f.evidence_ids.length || f.evidence_ids.some((id) => !evidenceIds.has(id)))
      errors[`facts.${i}.evidence_ids`] = '请关联至少一条存在的原文证据。';
    if (
      f.kind === 'education' &&
      f.value !== null &&
      !['associate', 'bachelor', 'master', 'doctorate', 'other'].includes(f.value)
    )
      errors[`facts.${i}.value`] = '请选择明确的学历类型。';
    if (
      (f.start_month && !month.test(f.start_month)) ||
      (f.end_month && !month.test(f.end_month)) ||
      (f.start_month && f.end_month && f.start_month > f.end_month)
    )
      errors[`facts.${i}.dates`] = '请检查年月格式及起止顺序。';
  });
  return errors;
}
export function validateJob(raw: string, content: JobContent): Issues {
  const errors: Issues = {};
  if (!raw.trim() || raw.length > 20000) errors.raw_text = 'JD 需为 1–20,000 字符。';
  if (!content.title.trim() || content.title.length > 200)
    errors.title = '岗位名称需为 1–200 字符。';
  if (content.company_context.length > 10000) errors.company_context = '公司背景最多 10,000 字符。';
  if (content.requirements.length > 100) errors.requirements = '最多 100 条要求。';
  if (!content.requirements.some((r) => !r.ignored))
    errors.requirements = '至少保留一条可评分要求。';
  const keys = new Set<string>();
  const ids = new Set<string>();
  content.requirements.forEach((r, i) => {
    const prefix = `requirements.${i}`;
    if (!r.id.trim() || ids.has(r.id)) errors[prefix] = '要求 ID 不能为空或重复。';
    ids.add(r.id);
    if (!r.quote.trim() || !raw.includes(r.quote))
      errors[`${prefix}.quote`] = '要求原文必须是 JD 中的真实片段。';
    if (!r.target.trim()) errors[`${prefix}.target`] = '请填写匹配目标。';
    if (r.operator === 'min_months' && (!/^[1-9]\d*$/.test(r.target) || !r.subject?.trim()))
      errors[`${prefix}.target`] = '最低月数必须为正整数，并填写相关领域。';
    if (
      r.operator === 'degree_at_least' &&
      !['associate', 'bachelor', 'master', 'doctorate'].includes(r.target)
    )
      errors[`${prefix}.target`] = '学历目标需为 associate / bachelor / master / doctorate。';
    if (r.ignored && !r.ignore_reason?.trim())
      errors[`${prefix}.ignore_reason`] = '请说明忽略原因。';
    const key = [
      r.operator,
      r.target.trim().toLowerCase(),
      r.subject?.trim().toLowerCase(),
      r.category,
    ].join('|');
    if (!r.ignored && keys.has(key))
      errors[prefix] = '存在重复要求，请合并；重要性冲突时保留必须。';
    if (!r.ignored) keys.add(key);
  });
  return errors;
}
