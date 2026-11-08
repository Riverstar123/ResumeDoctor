import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { ApiError, isTerminal } from '../api/client';
import { useAction, useLoad, useTask } from '../hooks';
import { useApp } from '../state';
import type { Diagnosis, DiagnosisItem, Job, Profile, Schema } from '../types';
import { ProfileEditor } from '../components/ProfileEditor';
import {
  ErrorNotice,
  Heading,
  Loading,
  ModelPicker,
  Status,
  ValidationErrors,
  useCanModel,
} from '../components/ui';
import { validateProfile, type Issues } from '../validation';

type Focus = Schema['DiagnosisFocus'];
type Context = {
  diagnosis: Diagnosis;
  item: DiagnosisItem;
  job: Job;
  profile: Profile;
  identity?: string;
};
const focusKey = (focus: Focus) =>
  JSON.stringify([focus.diagnosis_id, focus.item_id, focus.requirement_id]);
const flowError = (message: string) => new ApiError(422, 'INVALID_DIAGNOSIS_FOCUS', message);

export function FollowUpPage() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const focus: Focus = {
    diagnosis_id: params.get('diagnosis') || '',
    item_id: params.get('item') || '',
    requirement_id: params.get('requirement') || '',
  };
  const identity = `${id}:${focusKey(focus)}`;
  const load = useLoad(async (signal): Promise<Context> => {
    if (!id || !focus.diagnosis_id || !focus.item_id || !focus.requirement_id)
      throw flowError('缺少岗位上下文，请从报告中的具体要求进入补充。');
    const diagnosis = await api.diagnosis(focus.diagnosis_id, signal);
    const item = diagnosis.items.find((value) => value.id === focus.item_id);
    if (diagnosis.profile.id !== id || !item?.score_result)
      throw flowError('这份诊断与当前档案不匹配，或该岗位尚无评分。');
    const assessment = item.score_result.assessments.find(
      (value) => value.requirement_id === focus.requirement_id,
    );
    if (!assessment || assessment.status === 'met')
      throw flowError('这项要求不是可补充的诊断缺口，请返回报告选择。');
    const [job, profile] = await Promise.all([
      api.job(item.job.id, item.job.version, signal),
      api.profile(id, undefined, signal),
    ]);
    if (
      !job.content.requirements.some(
        (value) => value.id === focus.requirement_id && !value.ignored,
      ) ||
      profile.version < diagnosis.profile.version
    )
      throw flowError('无法读取这项要求对应的本次使用的版本。');
    return { diagnosis, item, job, profile, identity };
  }, identity);
  return (
    <>
      <Heading eyebrow="补充证据 / 针对岗位" title="围绕岗位，补齐真实证据">
        从报告中的具体要求出发。只补充确实做过的事；没有做过，也可以如实说明。
      </Heading>
      <ErrorNotice error={load.error} retry={load.reload} />
      {load.loading && <Loading text="正在读取岗位要求和档案版本…" />}
      {load.data?.identity === identity && (
        <FollowUpWorkspace key={identity} context={load.data} focus={focus} />
      )}
    </>
  );
}

export function FollowUpWorkspace({ context, focus }: { context: Context; focus: Focus }) {
  const { diagnosis, item, job } = context;
  const requirement = job.content.requirements.find((value) => value.id === focus.requirement_id)!;
  const assessment = item.score_result!.assessments.find(
    (value) => value.requirement_id === focus.requirement_id,
  )!;
  const app = useApp();
  const cacheKey = `${context.profile.id}:${focusKey(focus)}`;
  const restored = useRef(app.followUpDrafts.get(cacheKey)).current;
  const [resource, setResource] = useState(restored?.resource ?? context.profile);
  const [draft, setDraft] = useState(structuredClone(restored?.draft ?? context.profile.content));
  const [answer, setAnswer] = useState(restored?.answer ?? '');
  const [question, setQuestion] = useState(restored?.question ?? '');
  const [latest, setLatest] = useState<Profile | undefined>(
    restored && restored.resource.version < context.profile.version ? context.profile : undefined,
  );
  const [errors, setErrors] = useState<Issues>({});
  const [resultError, setResultError] = useState<unknown>();
  const [resultNotice, setResultNotice] = useState('');
  const [resultRevision, setResultRevision] = useState(0);
  const [readingResult, setReadingResult] = useState(false);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const chatAction = useAction();
  const editAction = useAction();
  const diagnoseAction = useAction();
  const canChat = useCanModel('profile_chat');
  const canDiagnose = useCanModel('diagnosis_report');
  const taskId = params.get('task');
  const progress = useTask(taskId);
  const task = progress.task?.id === taskId ? progress.task : undefined;
  const waiting = Boolean(taskId) && (!task || !isTerminal(task.status));
  const dirty = JSON.stringify(draft) !== JSON.stringify(resource.content);
  const busy =
    chatAction.busy || editAction.busy || diagnoseAction.busy || waiting || readingResult;
  const applied = useRef(restored?.appliedTaskId ?? '');
  const submitted = useRef('');
  const editorState = useRef({ resource, dirty });
  editorState.current = { resource, dirty };
  const questionRef = useRef<HTMLDivElement>(null);
  const baselineUrl = `/diagnoses/${diagnosis.id}?job=${encodeURIComponent(job.id)}`;

  useEffect(() => {
    if (restored?.taskId && !params.get('task')) {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set('task', restored.taskId!);
          return next;
        },
        { replace: true },
      );
    }
  }, []);

  useEffect(() => {
    // Keep the task reference after completion too: returning via the report
    // loses its query parameter, but must retain the already generated question.
    if (dirty || answer.length || taskId || question) {
      app.followUpDrafts.set(cacheKey, {
        resource,
        draft,
        answer,
        question,
        taskId,
        appliedTaskId: applied.current,
      });
    } else {
      app.followUpDrafts.delete(cacheKey);
    }
  }, [app.followUpDrafts, cacheKey, resource, draft, answer, question, taskId]);

  useEffect(() => {
    if (!dirty && !answer.trim()) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, answer]);

  useEffect(() => {
    if (!task || task.status !== 'succeeded' || applied.current === task.id) return;
    const result = task.result;
    if (
      task.kind !== 'profile_chat' ||
      result?.resource_type !== 'profile' ||
      result.resource_id !== resource.id ||
      !result.version ||
      !result.diagnosis_focus ||
      focusKey(result.diagnosis_focus) !== focusKey(focus)
    ) {
      setResultError(flowError('此任务不属于当前岗位要求，未应用其结果。请返回报告重新进入。'));
      return;
    }
    const canAdopt = () => {
      const current = editorState.current;
      if (result.version! < current.resource.version) {
        applied.current = task.id;
        setResultError(undefined);
        setResultNotice(
          `该任务对应档案 v${result.version}；已保留当前较新的 v${current.resource.version}，没有回退档案。`,
        );
        return false;
      }
      if (current.dirty) {
        setResultError(
          flowError(
            '当前有未保存的档案修改，任务结果未覆盖它们。请先保存，或读取最新版本并明确选择替换。',
          ),
        );
        return false;
      }
      return true;
    };
    if (!canAdopt()) return;
    const controller = new AbortController();
    setReadingResult(true);
    setResultError(undefined);
    // Read the exact result version, even if another tab has already saved a newer draft.
    api
      .profile(resource.id, result.version, controller.signal)
      .then((profile) => {
        if (controller.signal.aborted || !canAdopt()) return;
        applied.current = task.id;
        setResource(profile);
        setDraft(structuredClone(profile.content));
        setLatest(undefined);
        setErrors({});
        setResultNotice('');
        setQuestion(result.assistant_message || '本轮没有进一步问题，请核对当前档案。');
        if (!result.questions_only) setAnswer('');
        app.patch({ profileId: profile.id });
        // Focus only a newly completed action, never an unrelated report or a page load.
        if (submitted.current === task.id) questionRef.current?.focus();
      })
      .catch((error) => {
        if (!controller.signal.aborted) setResultError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setReadingResult(false);
      });
    return () => {
      controller.abort();
      setReadingResult(false);
    };
  }, [task?.id, task?.status, resultRevision, resource.id, focusKey(focus)]);

  const clearTask = () => {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('task');
        return next;
      },
      { replace: true },
    );
    setResultError(undefined);
    setResultNotice('');
  };
  const clearFinishedTask = () => {
    if (task && isTerminal(task.status)) clearTask();
  };

  const send = (questionsOnly: boolean) => {
    const body: Schema['MessageCreate'] = {
      base_version: resource.version,
      content: questionsOnly ? '请围绕这项岗位要求提出补充问题。' : answer,
      model_id: app.modelId,
      diagnosis_focus: focus,
      questions_only: questionsOnly,
    };
    void chatAction.run(
      async (key, frozen) => {
        const accepted = await api.sendMessage(resource.id, frozen, key);
        submitted.current = accepted.task_id;
        setResultError(undefined);
        setParams((previous) => {
          const next = new URLSearchParams(previous);
          next.set('task', accepted.task_id);
          return next;
        });
      },
      JSON.stringify(body),
      () => body,
    );
  };

  const save = () => {
    const problems = validateProfile(draft);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void editAction.run(async () => {
      const profile = await api.saveProfile(resource.id, {
        base_version: resource.version,
        content: draft,
      });
      setResource(profile);
      setDraft(structuredClone(profile.content));
      setLatest(undefined);
      clearFinishedTask();
    });
  };
  const confirm = () => {
    const problems = validateProfile(draft);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void editAction.run(async () => {
      setResource(await api.confirmProfile(resource.id, resource.version));
      clearFinishedTask();
    });
  };
  const diagnose = () =>
    void diagnoseAction.run(
      async (key, frozen) => {
        const next = await api.diagnose(frozen, key);
        app.patch({
          diagnosisIds: [
            next.diagnosis_id,
            ...app.workspace.diagnosisIds.filter((id) => id !== next.diagnosis_id),
          ],
        });
        navigate(
          `/diagnoses/${next.diagnosis_id}?before=${diagnosis.id}&job=${encodeURIComponent(job.id)}`,
        );
      },
      JSON.stringify([resource.id, resource.version, item.job, app.modelId]),
      () => ({
        profile: { id: resource.id, version: resource.version },
        jobs: [item.job],
        model_id: app.modelId,
      }),
    );

  return (
    <div className="follow-up-workspace">
      {restored && (
        <p className="notice">
          已恢复本页暂存的问题和填写内容，尚未自动提交。刷新或结束会话会清除暂存。
        </p>
      )}
      <section className="panel follow-up-target">
        <div className="section-heading">
          <div>
            <p className="eyebrow">本次补充目标</p>
            <h2>{job.content.title}</h2>
          </div>
          <Status value={assessment.status} assessment />
        </div>
        <blockquote>{requirement.quote}</blockquote>
        <p>{assessment.reason}</p>
        <p className="hint">
          原报告：档案 v{diagnosis.profile.version} · JD v{item.job.version}。当前档案：v
          {resource.version}。
        </p>
        <p className="notice">
          岗位要求用于引导问题，不是你的经历证据。没有做过或暂时无法核实的内容可以明确说明，不必编造成果。
        </p>
        <Link to={baselineUrl} className="text-link">
          查看原报告与证据 →
        </Link>
      </section>

      <section className="panel follow-up-questions">
        <div className="section-heading">
          <h2>先问清楚，再补充</h2>
        </div>
        <p className="hint">
          先生成针对这项要求的问题；此操作不会修改档案。回答后形成草稿，仍需你核对与确认。
        </p>
        <ModelPicker capability="profile_chat" disabled={busy} />
        <button
          className="button secondary"
          disabled={busy || dirty || !canChat || chatAction.cooldown > 0}
          onClick={() => send(true)}
        >
          生成岗位定向问题
        </button>
        <div
          className="follow-up-question"
          ref={questionRef}
          tabIndex={-1}
          aria-label="本轮岗位追问"
          aria-live="polite"
        >
          {question && (
            <>
              <h3>本轮岗位追问</h3>
              <p>{question}</p>
            </>
          )}
        </div>
        {taskId && (
          <div className="notice" aria-live="polite">
            <Status value={task?.status || 'queued'} />
            <p>{waiting ? '正在围绕岗位处理本轮内容，刷新可恢复进度。' : '本轮处理已结束。'}</p>
            {waiting && !progress.error && <Loading text="等待问题或档案草稿返回…" />}
            <ErrorNotice error={progress.error} retry={progress.retry} />
            {progress.error instanceof ApiError && progress.error.status === 404 && (
              <button className="text-button" onClick={clearTask}>
                关闭无法访问的任务
              </button>
            )}
            {task?.error && (
              <ErrorNotice
                error={new ApiError(422, task.error.code, task.error.message, task.error.details)}
              />
            )}
          </div>
        )}
        <ErrorNotice error={resultError} retry={() => setResultRevision((value) => value + 1)} />
        {resultNotice && <p className="notice warning">{resultNotice}</p>}
        <label className="field">
          你的真实补充
          <textarea
            rows={5}
            maxLength={8000}
            value={answer}
            disabled={busy || dirty}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="说明你实际做过什么、具体负责哪部分、用到什么工具、有哪些可核实的结果。没有做过也可以如实回答。"
          />
        </label>
        <p className="hint">
          {answer.length} / 8,000 字符{dirty ? ' · 请先保存下方档案修改。' : ''}
        </p>
        <ErrorNotice error={chatAction.error} />
        <button
          className="button"
          disabled={busy || dirty || !canChat || !answer.trim() || chatAction.cooldown > 0}
          onClick={() => send(false)}
        >
          {chatAction.busy ? '正在提交…' : '提交补充并整理草稿'}
        </button>
      </section>

      <section className="panel follow-up-draft">
        <div className="section-heading">
          <h2>核对当前档案 · v{resource.version}</h2>
          <span className={`badge status-${resource.confirmed && !dirty ? 'met' : 'unknown'}`}>
            {dirty ? '有未保存修改' : resource.confirmed ? '已确认' : '待确认草稿'}
          </span>
        </div>
        <p className="hint">
          核对新增事实与引用原文。保存和确认只处理当前档案，原报告保留原来的材料。
        </p>
        <button
          className="text-button"
          disabled={busy}
          onClick={() => void editAction.run(async () => setLatest(await api.profile(resource.id)))}
        >
          读取最新档案版本
        </button>
        {latest && (
          <div className="notice">
            <p>服务端最新为 v{latest.version}；替换会放弃当前未保存的档案编辑。</p>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setResource(latest);
                setDraft(structuredClone(latest.content));
                setLatest(undefined);
                setErrors({});
                editAction.clearError();
                clearFinishedTask();
              }}
            >
              用最新版本替换当前草稿
            </button>
          </div>
        )}
        <ValidationErrors errors={errors} />
        <details open={!resource.confirmed} className="follow-up-profile-details">
          <summary>查看并核对事实与证据</summary>
          <ProfileEditor value={draft} disabled={busy} onChange={setDraft} />
        </details>
        <ErrorNotice error={editAction.error} />
        <div className="actions">
          <button
            className="button secondary"
            disabled={busy || !dirty || editAction.cooldown > 0}
            onClick={save}
          >
            保存补充后的档案
          </button>
          <button
            className="button"
            disabled={
              busy || dirty || resource.confirmed || !draft.facts.length || editAction.cooldown > 0
            }
            onClick={confirm}
          >
            确认补充档案 v{resource.version}
          </button>
        </div>
      </section>

      <section className="panel follow-up-rerun">
        <h2>用原岗位要求查看变化</h2>
        <p>
          使用已确认档案 v{resource.version} 与原 JD v{item.job.version}{' '}
          重新诊断，随后查看补充前后的状态和证据。
        </p>
        {resource.version <= diagnosis.profile.version && (
          <p className="hint">档案尚未形成新版本。先补充并确认事实，再比较变化。</p>
        )}
        <ModelPicker capability="diagnosis_report" disabled={busy} />
        <ErrorNotice error={diagnoseAction.error} />
        <button
          className="button"
          disabled={
            busy ||
            dirty ||
            Boolean(answer.trim()) ||
            !resource.confirmed ||
            resource.version <= diagnosis.profile.version ||
            !canDiagnose ||
            diagnoseAction.cooldown > 0
          }
          onClick={diagnose}
        >
          用原 JD 重新诊断并比较
        </button>
        {answer.trim() && <p className="hint">上方还有未提交的回答，请先提交，或清空后再诊断。</p>}
      </section>
    </div>
  );
}
