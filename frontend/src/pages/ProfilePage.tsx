import { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useApp } from '../state';
import { useAction, useLoad, useTask } from '../hooks';
import { validateProfile, type Issues } from '../validation';
import type { Profile, Task } from '../types';
import { ProfileEditor } from '../components/ProfileEditor';
import {
  ErrorNotice,
  Heading,
  Loading,
  TaskProgress,
  TaskWarnings,
  ValidationErrors,
  terminalTask,
} from '../components/ui';

export function ProfilePage() {
  const { id = '' } = useParams();
  const app = useApp();
  const load = useLoad((signal) => api.profile(id, undefined, signal), id);
  useEffect(() => {
    if (load.data) app.patch({ profileId: load.data.id });
  }, [load.data?.id]);
  return (
    <>
      <Heading eyebrow="02 / 确认档案" title="每段经历，都有出处">
        核对经历摘要，有误的地方点开修改。确认后即可选择岗位。
      </Heading>
      <ErrorNotice error={load.error} retry={load.reload} />
      {load.loading && <Loading />}
      {load.data && (
        <ProfileForm key={`${id}:${load.data.version}`} initial={load.data} reload={load.reload} />
      )}
    </>
  );
}
function documentWarnings(task: Task | undefined, profileId: string): string[] {
  return task?.kind === 'document_parse' &&
    task.status === 'succeeded' &&
    task.result?.resource_type === 'profile' &&
    task.result.resource_id === profileId
    ? (task.result.warnings ?? [])
    : [];
}

function ProfileForm({ initial, reload }: { initial: Profile; reload: () => void }) {
  const [resource, setResource] = useState(initial);
  const [draft, setDraft] = useState(structuredClone(initial.content));
  const [errors, setErrors] = useState<Issues>({});
  const [latest, setLatest] = useState<Profile>();
  const [params, setParams] = useSearchParams();
  const action = useAction();
  const app = useApp();
  const dirty = JSON.stringify(draft) !== JSON.stringify(resource.content);
  const reviewCount = draft.facts.filter(
    (fact) =>
      !fact.label.trim() ||
      !fact.evidence_ids.length ||
      Boolean(fact.unverified_attributes?.length),
  ).length;
  const taskId = params.get('task');
  const progress = useTask(taskId);
  // useTask resets in an effect; ignore a previous task during an ID transition.
  const result = progress.task?.id === taskId ? progress.task : undefined;
  const settledTask = terminalTask(result?.status);
  const remembered = app.workspace.profileWarningTasks[resource.id];
  const warningTaskId = remembered && !remembered.dismissed ? remembered.id : null;
  const storedWarning = useTask(warningTaskId !== taskId ? warningTaskId : null);
  const warningRequest = warningTaskId === taskId ? progress : storedWarning;
  const warningTask = warningRequest.task?.id === warningTaskId ? warningRequest.task : undefined;
  const warnings = documentWarnings(warningTask, resource.id);
  useEffect(() => {
    // Also adopt an older/bookmarked ?task= URL, but only for its actual profile.
    // An acknowledged task stays acknowledged when that URL is revisited.
    if (taskId && documentWarnings(result, resource.id).length) {
      app.rememberProfileWarningTask(resource.id, taskId);
    }
  }, [taskId, result, resource.id, app.rememberProfileWarningTask]);
  // Only an in-flight task writes to this profile; a finished or unreadable one must not lock editing.
  const locked = action.busy || (Boolean(taskId) && !settledTask && !progress.error);
  const handledTask = useRef('');
  useEffect(() => {
    if (!taskId || !result || !settledTask) return;
    // Parsing notes have their own per-profile lifetime; chat completion below
    // may clear its URL without deleting the outstanding document notice.
    if (documentWarnings(result, resource.id).length) return;
    // A failed task keeps its panel so the error stays readable until dismissed.
    if (result.status === 'failed') return;
    if (handledTask.current === result.id) return;
    handledTask.current = result.id;
    setParams({});
    reload();
  }, [taskId, result?.id, result?.status]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const save = () => {
    const problems = validateProfile(draft);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void action.run(async () => {
      const next = await api.saveProfile(resource.id, {
        base_version: resource.version,
        content: draft,
      });
      setResource(next);
      setDraft(structuredClone(next.content));
      setLatest(undefined);
    });
  };
  const confirm = () => {
    const problems = validateProfile(draft);
    setErrors(problems);
    if (Object.keys(problems).length) return;
    void action.run(async () => {
      const next = await api.confirmProfile(resource.id, resource.version);
      setResource(next);
    });
  };
  return (
    <>
      <TaskWarnings
        warnings={warnings}
        onDismiss={() => {
          app.dismissProfileWarnings(resource.id);
          if (taskId === warningTaskId) {
            setParams(
              (previous) => {
                const next = new URLSearchParams(previous);
                next.delete('task');
                return next;
              },
              { replace: true },
            );
          }
        }}
      />
      {warningTaskId && warningTaskId !== taskId && (
        <ErrorNotice error={storedWarning.error} retry={storedWarning.retry} />
      )}
      <section className="panel">
        <div className="section-heading">
          <div className="row">
            <h2>我的档案</h2>
            <span className="tag">v{resource.version}</span>
            <span
              className={`badge ${resource.confirmed && !dirty ? 'status-met' : 'status-unknown'}`}
            >
              {dirty ? '有未保存修改' : resource.confirmed ? '已确认' : '待确认草稿'}
            </span>
          </div>
          <button
            className="text-button"
            disabled={locked}
            onClick={() => void action.run(async () => setLatest(await api.profile(resource.id)))}
          >
            读取最新版本
          </button>
        </div>
        {latest && (
          <div className="notice">
            <strong>服务端最新版本 v{latest.version}</strong>
            <p>
              {latest.content.overview || '（无概述）'} · {latest.content.facts.length} 条事实
            </p>
            <p>本地编辑仍保留。替换前请核对内容，此操作会放弃当前未保存修改。</p>
            <button
              className="button secondary small"
              onClick={() => {
                setResource(latest);
                setDraft(structuredClone(latest.content));
                setLatest(undefined);
                setErrors({});
                action.clearError();
              }}
            >
              用最新版本替换本地草稿
            </button>
          </div>
        )}
        <ValidationErrors errors={errors} />
        <div className={`notice ${reviewCount ? 'warning' : 'success'}`}>
          <strong>{reviewCount ? `有 ${reviewCount} 条需要核对` : '未发现需要确认的内容'}</strong>
          <p>
            读取到 {draft.facts.length} 条事实、{draft.evidence.length} 条证据。
            {reviewCount ? '需要核对的事实已自动展开，其余已折叠。' : '下方列表可展开逐条查看。'}
          </p>
        </div>
        <ProfileEditor value={draft} disabled={locked} onChange={setDraft} />
        <ErrorNotice error={action.error} />
        <div className="editor-footer profile-confirmation">
          <p>
            {dirty
              ? '保存会创建新草稿版本，需要再次确认。'
              : draft.facts.some((fact) => fact.unverified_attributes?.length)
                ? '仍有待核对信息；确认档案不会将这些候选计为满足。'
                : resource.confirmed
                  ? '该版本已确认，可以选择目标岗位。'
                  : '确认后这版档案将用于评分；之后修改会生成新版本。'}
          </p>
          <div className="actions">
            <button
              className="button secondary"
              disabled={locked || !dirty || action.cooldown > 0}
              onClick={save}
            >
              {action.busy ? '正在保存…' : '保存新版本'}
            </button>
            <button
              className="button"
              disabled={
                locked || dirty || resource.confirmed || !draft.facts.length || action.cooldown > 0
              }
              onClick={confirm}
            >
              确认档案 v{resource.version}
            </button>
            {resource.confirmed && !dirty && (
              <Link className="button" to="/jobs">
                选择目标岗位 →
              </Link>
            )}
          </div>
        </div>
      </section>
      {taskId && (!settledTask || result?.status === 'failed') && (
        <TaskProgress
          id={taskId}
          state={progress}
          onComplete={() => undefined}
          onDismiss={() => setParams({})}
        />
      )}
    </>
  );
}
