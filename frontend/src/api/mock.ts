import profileExample from '../../../docs/examples/profile.json';
import jobExample from '../../../docs/examples/job.json';
import itemExample from '../../../docs/examples/diagnosis-item.json';
import type { Diagnosis, DiagnosisItem, Job, Profile, Schema, Task } from '../types';
import { isTerminal } from './client';

export const demoText = (profileExample as Profile).content.evidence.map((e) => e.quote).join('\n');
export const demoJob = (jobExample as Job).raw_text;
export type Scenario =
  | 'success'
  | 'partial'
  | 'failed'
  | 'parse-failed'
  | 'conflict'
  | 'rate-limit';
type Pending = {
  task: Task;
  ready: number;
  scenario: Scenario;
  profile?: Profile;
  job?: Job;
  messages?: Schema['Message'][];
  base?: number;
};
type Database = {
  session?: Schema['Session'];
  profiles: Record<string, Profile[]>;
  jobs: Record<string, Job[]>;
  tasks: Record<string, Pending>;
  diagnoses: Record<string, Diagnosis>;
  messages: Record<string, Schema['Message'][]>;
  keys: Record<string, { fingerprint: string; body: unknown; status: number }>;
  scenario: Scenario;
};
const storageKey = 'rd:mock-database-v1';
const blank = (): Database => ({
  profiles: {},
  jobs: {},
  tasks: {},
  diagnoses: {},
  messages: {},
  keys: {},
  scenario: 'success',
});
const clone = <T>(value: T): T => structuredClone(value);
const now = () => new Date().toISOString();
const uuid = () => crypto.randomUUID();
function read(): Database {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey) || 'null') || blank();
  } catch {
    return blank();
  }
}
function save(db: Database) {
  sessionStorage.setItem(storageKey, JSON.stringify(db));
}
export function setScenario(scenario: Scenario) {
  const db = read();
  db.scenario = scenario;
  save(db);
}
export function resetMock() {
  sessionStorage.removeItem(storageKey);
}
export const mockModels: Schema['ModelList'] = {
  default_model_id: 'demo-model-a',
  items: ['a', 'b'].map((letter) => ({
    id: `demo-model-${letter}`,
    display_name: `演示模型 ${letter.toUpperCase()}`,
    provider: 'fake',
    capabilities: ['profile_extract', 'profile_chat', 'job_extract', 'diagnosis_report'],
  })),
};
class MockFailure extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}
const fail = (
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
): never => {
  throw new MockFailure(status, code, message, details);
};
function latest<T extends { version: number }>(versions?: T[], version?: string | null): T {
  const found = version ? versions?.find((v) => v.version === Number(version)) : versions?.at(-1);
  return found || fail(404, 'RESOURCE_NOT_FOUND', '资料不存在，或不属于当前会话。');
}
function modelCheck(id: string, capability: Schema['Model']['capabilities'][number]) {
  if (!mockModels.items.some((m) => m.id === id && m.capabilities.includes(capability)))
    fail(422, 'MODEL_UNAVAILABLE', '当前模型不支持该任务，请手动选择其他模型。');
}
function taskStart(
  db: Database,
  kind: Task['kind'],
  model: string,
  result: Schema['TaskResult'],
  extra: Partial<Pending> = {},
) {
  const task: Task = {
    id: uuid(),
    kind,
    model_id: model,
    status: 'queued',
    result,
    error: null,
    created_at: now(),
    updated_at: now(),
  };
  db.tasks[task.id] = { task, ready: Date.now() + 900, scenario: db.scenario, ...extra };
  return task;
}
const DOCX_WARNING =
  'DOCX_PAGINATION_UNVERIFIED: 已检查明确分页；实际排版页数未经核验，需要准确页数时请另存为 PDF。';
function result(
  type: Schema['TaskResult']['resource_type'],
  id: string,
  version: number | null,
  assistant: string | null = null,
  warnings: string[] = [],
): Schema['TaskResult'] {
  return {
    resource_type: type,
    resource_id: id,
    version,
    assistant_message: assistant,
    ...(warnings.length ? { warnings } : {}),
  };
}
function buildItem(
  db: Database,
  diagnosis: Diagnosis,
  item: DiagnosisItem,
  index: number,
  scenario: Scenario,
): DiagnosisItem {
  const profile = latest(db.profiles[diagnosis.profile.id], String(diagnosis.profile.version));
  const job = latest(db.jobs[item.job.id], String(item.job.version));
  const known =
    JSON.stringify(profile.content.facts) === JSON.stringify(profileExample.content.facts) &&
    JSON.stringify(job.content.requirements) === JSON.stringify(jobExample.content.requirements);
  const base = clone(itemExample) as DiagnosisItem;
  base.id = item.id;
  base.job = item.job;
  // These are fixed UI fixtures, never a browser implementation of M4 scoring.
  if (!known) {
    const requirements = job.content.requirements.filter((r) => !r.ignored);
    base.score_result = {
      score: 0,
      unknown_weight_ratio: 1,
      rule_version: 'coverage-v1',
      matcher_version: 'matcher-v1',
      assessments: requirements.map((r) => ({
        requirement_id: r.id,
        category: r.category,
        importance: r.importance,
        status: 'unknown',
        weight: r.importance === 'must' ? 2 : 1,
        coefficient: 0,
        evidence_ids: [],
        reason: '演示占位：未执行真实匹配，请连接后端获取评分。',
      })),
      dimensions: [...new Set(requirements.map((r) => r.category))].map((category) => ({
        category,
        score: 0,
      })),
    };
    base.report = {
      summary: '演示占位报告；自定义材料的真实提取与评分需接入后端。',
      gaps: requirements.map((r) => ({
        requirement_id: r.id,
        kind: 'needs_evidence',
        description: '等待后端证据匹配。',
        evidence_ids: [],
      })),
      suggestions: [],
      actions: [],
    };
  }
  base.model_metadata = {
    model_id: diagnosis.model_id,
    provider: 'fake',
    model: `synthetic-fixture-${diagnosis.model_id.endsWith('b') ? 'b' : 'a'}`,
    prompt_version: 'report-v1',
    gateway_config_version: 'demo-v1',
    generated_at: now(),
  };
  if (base.report)
    base.report.summary = `【演示数据 · ${job.content.title}】${base.report.summary}`;
  if (scenario === 'failed' || (scenario === 'partial' && index > 1)) {
    base.status = 'failed';
    base.score_result = null;
    base.report = null;
    base.model_metadata = null;
    base.error = { code: 'TASK_TIMEOUT', message: '演示：该岗位处理超时，请重新诊断。' };
  } else if (scenario === 'partial' && (index === 1 || diagnosis.items.length === 1)) {
    base.status = 'score_only';
    base.report = null;
    base.error = { code: 'MODEL_TIMEOUT', message: '演示：报告生成超时，确定性评分已保留。' };
  }
  return base;
}
function settle(db: Database, pending: Pending) {
  const task = pending.task;
  if (isTerminal(task.status)) return;
  if (Date.now() < pending.ready) {
    task.status = 'running';
    return;
  }
  task.updated_at = now();
  if (task.kind === 'diagnosis') {
    const diagnosis = db.diagnoses[task.result!.resource_id];
    diagnosis.items = diagnosis.items.map((item, i) =>
      buildItem(db, diagnosis, item, i, pending.scenario),
    );
    diagnosis.status = diagnosis.items.every((i) => i.status === 'succeeded')
      ? 'succeeded'
      : diagnosis.items.some((i) => i.score_result)
        ? 'partial'
        : 'failed';
    task.status = diagnosis.status;
    if (task.status === 'failed') {
      task.error = { code: 'TASK_TIMEOUT', message: '演示：所有岗位均处理失败。' };
      task.result = null;
    }
    return;
  }
  if (pending.scenario === 'parse-failed') {
    task.status = 'failed';
    task.result = null;
    task.error = {
      code: task.kind === 'document_parse' ? 'NO_TEXT_LAYER' : 'MODEL_TIMEOUT',
      message:
        task.kind === 'document_parse'
          ? '演示：未检测到可提取的文字层，请改用对话输入。'
          : '演示：提取超时，原文保留，请重试。',
    };
    return;
  }
  if (pending.profile) {
    const versions = db.profiles[pending.profile.id] || [];
    if (pending.base !== undefined && versions.at(-1)?.version !== pending.base) {
      task.status = 'failed';
      task.result = null;
      task.error = { code: 'VERSION_CONFLICT', message: '档案已有新版本，请重新读取后提交。' };
      return;
    }
    db.profiles[pending.profile.id] = [...versions, pending.profile];
    if (pending.messages)
      db.messages[pending.profile.id] = [
        ...(db.messages[pending.profile.id] || []),
        ...pending.messages,
      ];
  }
  if (pending.job) db.jobs[pending.job.id] = [pending.job];
  task.status = 'succeeded';
}
function markdown(db: Database, diagnosis: Diagnosis) {
  const safe = (s: string) => s.replace(/[<>]/g, (c) => (c === '<' ? '&lt;' : '&gt;'));
  const lines = [
    '# ResumeDoctor 诊断报告',
    '',
    '> 演示数据：仅用于前端流程验证，不代表真实诊断。',
    '',
    `档案：${diagnosis.profile.id} / v${diagnosis.profile.version}`,
    `模型：${diagnosis.model_id}`,
    `状态：${diagnosis.status}`,
    '分数为材料覆盖度，不是录用概率。',
  ];
  for (const item of diagnosis.items) {
    const job = latest(db.jobs[item.job.id], String(item.job.version));
    lines.push(
      '',
      `## ${safe(job.content.title)}`,
      `JD：${item.job.id} / v${item.job.version}`,
      `状态：${item.status}`,
    );
    if (item.error) lines.push(`错误：${item.error.code} / ${safe(item.error.message)}`);
    if (item.score_result) {
      lines.push(
        `分数：${item.score_result.score}`,
        `未知权重比例：${item.score_result.unknown_weight_ratio}`,
        `规则：${item.score_result.rule_version} / ${item.score_result.matcher_version}`,
      );
      for (const a of item.score_result.assessments)
        lines.push(
          `- ${a.requirement_id} · ${a.status} · ${safe(a.reason)} · 证据：${a.evidence_ids.join(', ') || '无'}`,
        );
    }
    if (item.model_metadata)
      lines.push(
        `实际模型：${item.model_metadata.provider} / ${item.model_metadata.model} / ${item.model_metadata.prompt_version}`,
      );
    if (item.report) {
      lines.push('', safe(item.report.summary), '### 差距');
      item.report.gaps.forEach((g) =>
        lines.push(`- ${g.requirement_id} · ${g.kind} · ${safe(g.description)}`),
      );
      lines.push('### 修改建议');
      item.report.suggestions.forEach((s) =>
        lines.push(
          `- ${s.requirement_id} · ${safe(s.revised)}${s.requires_user_input ? '（待填写真实信息）' : ''}`,
          `  ${safe(s.rationale)}`,
        ),
      );
      lines.push('### 行动计划');
      item.report.actions.forEach((a) =>
        lines.push(
          `- ${a.priority} · ${a.horizon} · ${safe(a.task)}；完成标准：${safe(a.done_when)}`,
        ),
      );
    }
  }
  const profile = latest(db.profiles[diagnosis.profile.id], String(diagnosis.profile.version));
  lines.push('', '## 冻结档案证据');
  profile.content.evidence.forEach((e) =>
    lines.push(`- ${e.id} · ${e.source_type} / ${safe(e.source_id)}：${safe(e.quote)}`),
  );
  return lines.join('\n');
}

export async function mockFetch(input: string, init: RequestInit): Promise<Response> {
  if (init.signal?.aborted) throw init.signal.reason;
  const db = read();
  const url = new URL(input, 'http://localhost');
  const path = url.pathname.replace(/^\/api\/v1/, '');
  const method = init.method || 'GET';
  const parts = path.split('/').filter(Boolean);
  const headers = new Headers(init.headers);
  const form = init.body instanceof FormData ? init.body : undefined;
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : {};
  let status = 200;
  let response: unknown;
  const key = headers.get('Idempotency-Key');
  const needsKey = method === 'POST' && path !== '/session' && !path.endsWith('/confirm');
  let fingerprint = `${method}:${path}:${JSON.stringify(body)}`;
  try {
    if (path === '/session' && method === 'POST') {
      if (!db.session || Date.parse(db.session.expires_at) <= Date.now())
        Object.assign(db, blank(), {
          session: { id: uuid(), expires_at: new Date(Date.now() + 7 * 86400000).toISOString() },
        });
      response = db.session;
    } else {
      if (!db.session || Date.parse(db.session.expires_at) <= Date.now())
        fail(401, 'SESSION_EXPIRED', '会话已过期，请重新确认资料处理说明。');
      if (path === '/session' && method === 'DELETE') {
        resetMock();
        return new Response(null, { status: 204 });
      }
      if (form) {
        const f = form.get('file') as File;
        fingerprint = `${method}:${path}:${form.get('model_id')}:${f.name}:${Array.from(new Uint8Array(await f.arrayBuffer())).join(',')}`;
      }
      if (needsKey) {
        if (!key || key.length < 16 || key.length > 128)
          fail(422, 'VALIDATION_ERROR', '缺少合法幂等键。');
        const previous = db.keys[key!];
        if (previous) {
          if (previous.fingerprint !== fingerprint)
            fail(409, 'IDEMPOTENCY_CONFLICT', '同一幂等键对应不同请求。');
          return Response.json(previous.body, { status: previous.status });
        }
      }
      if (db.scenario === 'rate-limit' && method !== 'GET') {
        db.scenario = 'success';
        save(db);
        fail(429, 'RATE_LIMITED', '演示：请求过于频繁，请 2 秒后重试。');
      }
      if (path === '/models') response = mockModels;
      else if (path === '/profiles' && method === 'POST') {
        const profile: Profile = {
          id: uuid(),
          version: 1,
          confirmed: false,
          content: body.content,
          created_at: now(),
        };
        db.profiles[profile.id] = [profile];
        response = profile;
        status = 201;
      } else if (path === '/documents' && method === 'POST' && form) {
        const file = form.get('file') as File;
        modelCheck(String(form.get('model_id')), 'profile_extract');
        if (file.size > 10 * 1024 * 1024) fail(413, 'FILE_TOO_LARGE', '文件超过 10 MiB。');
        if (!/\.(pdf|docx)$/i.test(file.name))
          fail(415, 'UNSUPPORTED_FILE_TYPE', '只支持文字 PDF / DOCX。');
        const profile: Profile = {
          ...(clone(profileExample) as Profile),
          id: uuid(),
          confirmed: false,
          created_at: now(),
        };
        response = {
          task_id: taskStart(
            db,
            'document_parse',
            String(form.get('model_id')),
            result(
              'profile',
              profile.id,
              1,
              null,
              /\.docx$/i.test(file.name) ? [DOCX_WARNING] : [],
            ),
            { profile },
          ).id,
        };
        status = 202;
      } else if (parts[0] === 'profiles' && parts[2] === 'messages') {
        const profile = latest(db.profiles[parts[1]]);
        if (method === 'GET') response = { items: db.messages[profile.id] || [] };
        else {
          modelCheck(body.model_id, 'profile_chat');
          if (body.base_version !== profile.version)
            fail(409, 'VERSION_CONFLICT', '资料已更新，请先读取最新版本。');
          if (
            Object.values(db.tasks).some(
              (p) => p.profile?.id === profile.id && !isTerminal(p.task.status),
            )
          )
            fail(409, 'PROFILE_BUSY', '该档案有正在处理的任务。');
          if (!body.content.trim() || body.content.length > 8000)
            fail(422, 'VALIDATION_ERROR', '每条对话需为 1–8,000 字符。', { content: '长度不合法' });
          if ((db.messages[profile.id] || []).filter((m) => m.role === 'user').length >= 50)
            fail(422, 'VALIDATION_ERROR', '已达到 50 条用户消息上限。');
          const message: Schema['Message'] = {
            id: uuid(),
            role: 'user',
            content: body.content,
            created_at: now(),
          };
          const assistant: Schema['Message'] = {
            id: uuid(),
            role: 'assistant',
            content:
              '演示：已保留你提供的原文。你负责的具体工作是什么？有哪些可核实的结果？经历的起止月份是什么？',
            created_at: now(),
          };
          const next = clone(profile);
          next.version++;
          next.confirmed = false;
          next.created_at = now();
          if (body.content === demoText && !profile.content.facts.length)
            next.content = clone(profileExample.content) as Profile['content'];
          else {
            const eid = uuid();
            next.content.evidence.push({
              id: eid,
              source_type: 'message',
              source_id: message.id,
              quote: body.content,
              locator: null,
            });
            next.content.facts.push({
              id: uuid(),
              kind: 'project',
              label: '用户描述（请编辑具体标签）',
              value: null,
              polarity: 'positive',
              application: 'claimed',
              start_month: null,
              end_month: null,
              completed: null,
              evidence_ids: [eid],
            });
          }
          response = {
            task_id: taskStart(
              db,
              'profile_chat',
              body.model_id,
              result('profile', next.id, next.version, assistant.content),
              { profile: next, base: profile.version, messages: [message, assistant] },
            ).id,
          };
          status = 202;
        }
      } else if (parts[0] === 'profiles' || (parts[0] === 'jobs' && parts.length > 1)) {
        const collection = parts[0] === 'profiles' ? db.profiles : db.jobs;
        const current = latest<Profile | Job>(
          collection[parts[1]],
          method === 'GET' ? url.searchParams.get('version') : null,
        );
        if (method === 'GET') response = current;
        else if (parts[2] === 'confirm') {
          if (body.version !== current.version) fail(409, 'VERSION_CONFLICT', '只能确认最新版本。');
          current.confirmed = true;
          response = current;
        } else if (method === 'PUT') {
          if (db.scenario === 'conflict') {
            db.scenario = 'success';
            save(db);
            fail(409, 'VERSION_CONFLICT', '演示：资料被其他操作更新，本地编辑仍保留。');
          }
          if (body.base_version !== current.version)
            fail(409, 'VERSION_CONFLICT', '资料已更新，本地编辑仍保留。');
          const next = {
            ...current,
            version: current.version + 1,
            confirmed: false,
            content: body.content,
            created_at: now(),
            ...('raw_text' in current ? { raw_text: body.raw_text } : {}),
          };
          (collection as Record<string, (Profile | Job)[]>)[parts[1]].push(next);
          response = next;
        } else fail(404, 'RESOURCE_NOT_FOUND', '不存在的接口。');
      } else if (path === '/jobs' && method === 'POST') {
        modelCheck(body.model_id, 'job_extract');
        if (
          !body.raw_text.trim() ||
          body.raw_text.length > 20000 ||
          body.company_context.length > 10000
        )
          fail(422, 'VALIDATION_ERROR', '请检查 JD 和公司背景长度。');
        const job: Job = {
          ...(clone(jobExample) as Job),
          id: uuid(),
          confirmed: false,
          raw_text: body.raw_text,
          created_at: now(),
        };
        job.content.company_context = body.company_context;
        if (body.raw_text !== demoJob) {
          job.content.title = body.raw_text.split('\n')[0].slice(0, 200);
          job.content.company_name = null;
          job.content.requirements = body.raw_text
            .split('\n')
            .filter((s: string) => s.trim())
            .slice(0, 100)
            .map((quote: string, i: number) => ({
              id: `r${i + 1}`,
              quote,
              category: 'other',
              importance: 'must',
              operator: 'manual_review',
              target: quote,
              subject: null,
              ignored: false,
              ignore_reason: null,
            }));
        }
        response = {
          task_id: taskStart(db, 'job_parse', body.model_id, result('job', job.id, 1), { job }).id,
        };
        status = 202;
      } else if (path === '/diagnoses' && method === 'POST') {
        modelCheck(body.model_id, 'diagnosis_report');
        const request = body as Schema['DiagnosisCreate'];
        if (
          !request.jobs.length ||
          request.jobs.length > 5 ||
          new Set(request.jobs.map((j) => j.id)).size !== request.jobs.length
        )
          fail(422, 'VALIDATION_ERROR', '每次选择 1–5 个不同岗位。');
        if (!latest(db.profiles[request.profile.id], String(request.profile.version)).confirmed)
          fail(422, 'UNCONFIRMED_VERSION', '请先确认档案版本。');
        request.jobs.forEach((ref) => {
          const job = latest(db.jobs[ref.id], String(ref.version));
          if (!job.confirmed) fail(422, 'UNCONFIRMED_VERSION', '请先确认全部 JD。');
          if (!job.content.requirements.some((r) => !r.ignored))
            fail(422, 'NO_SCORABLE_REQUIREMENTS', 'JD 无可评分要求。');
        });
        const id = uuid();
        const task = taskStart(db, 'diagnosis', request.model_id, result('diagnosis', id, null));
        db.diagnoses[id] = {
          id,
          task_id: task.id,
          status: 'queued',
          profile: request.profile,
          model_id: request.model_id,
          created_at: now(),
          items: request.jobs.map((job) => ({
            id: uuid(),
            job,
            status: 'pending',
            score_result: null,
            report: null,
            error: null,
            model_metadata: null,
          })),
        };
        response = { task_id: task.id, diagnosis_id: id };
        status = 202;
      } else if (parts[0] === 'tasks') {
        const pending = db.tasks[parts[1]] || fail(404, 'RESOURCE_NOT_FOUND', '任务不存在。');
        settle(db, pending);
        response = clone(pending.task);
        if (!isTerminal(pending.task.status)) (response as Task).result = null;
      } else if (parts[0] === 'diagnoses') {
        const diagnosis = db.diagnoses[parts[1]] || fail(404, 'RESOURCE_NOT_FOUND', '诊断不存在。');
        settle(db, db.tasks[diagnosis.task_id]);
        if (parts[2] === 'export') {
          if (!isTerminal(diagnosis.status) || !diagnosis.items.some((i) => i.score_result))
            fail(409, 'NOT_READY', '当前诊断没有可导出的已完成评分。');
          save(db);
          return new Response(markdown(db, diagnosis), {
            headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
          });
        }
        response = diagnosis;
      } else fail(404, 'RESOURCE_NOT_FOUND', '不存在的接口。');
    }
    if (needsKey && key) db.keys[key] = { fingerprint, body: clone(response), status };
    save(db);
    return Response.json(response, { status });
  } catch (error) {
    if (!(error instanceof MockFailure)) throw error;
    return Response.json(
      {
        error: { code: error.code, message: error.message, details: error.details },
        request_id: uuid(),
      },
      { status: error.status, headers: error.status === 429 ? { 'Retry-After': '2' } : {} },
    );
  }
}
