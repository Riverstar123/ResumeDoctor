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
  ModelPicker,
  TaskProgress,
  TaskWarnings,
  ValidationErrors,
  terminalTask,
  useCanModel,
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
        检查结构化事实与原文对应关系。未知内容可以留空，确认后再用于诊断。
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
  const [chat, setChat] = useState('');
  const [params, setParams] = useSearchParams();
  const action = useAction();
  const chatAction = useAction();
  const app = useApp();
  const canModel = useCanModel('profile_chat');
  const history = useLoad(
    (signal) => api.messages(resource.id, signal),
    `${resource.id}:${resource.version}`,
  );
  const dirty = JSON.stringify(draft) !== JSON.stringify(resource.content);
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
  const locked =
    action.busy || chatAction.busy || (Boolean(taskId) && !settledTask && !progress.error);
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
    setChat('');
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
        <ProfileEditor value={draft} disabled={locked} onChange={setDraft} />
        <ErrorNotice error={action.error} />
        <div className="editor-footer">
          <p>
            {dirty
              ? '保存会创建新草稿版本，需要再次确认。'
              : resource.confirmed
                ? '该版本已确认，可以选择目标岗位。'
                : '确认表示你已核对这些事实与证据。'}
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
      <section className="panel chat-panel">
        <div className="section-heading">
          <h2>通过对话补充经历</h2>
          <span className="tag">
            {history.data?.items.filter((m) => m.role === 'user').length || 0} / 50 轮
          </span>
        </div>
        <p className="muted">每轮会生成新草稿，最多提出 3 个追问。已有报告仍使用之前的确认版本。</p>
        <ErrorNotice error={history.error} retry={history.reload} />
        <div className="messages">
          {history.data?.items.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <strong>{message.role === 'user' ? '你' : '整理助手'}</strong>
              <p>{message.content}</p>
            </article>
          ))}
        </div>
        <label className="field">
          补充经历
          <textarea
            rows={4}
            maxLength={8000}
            disabled={locked || dirty}
            value={chat}
            onChange={(e) => setChat(e.target.value)}
            placeholder="补充你的具体角色、工作内容、真实结果或起止月份…"
          />
        </label>
        <small>
          {chat.length} / 8,000 字符{dirty ? ' · 请先保存上方编辑，再发送补充。' : ''}
        </small>
        <ModelPicker capability="profile_chat" disabled={locked} />
        <ErrorNotice error={chatAction.error} />
        <button
          className="button"
          disabled={
            locked ||
            dirty ||
            !chat.trim() ||
            !canModel ||
            chatAction.cooldown > 0 ||
            (history.data?.items.filter((m) => m.role === 'user').length || 0) >= 50
          }
          onClick={() =>
            void chatAction.run(
              async (key) => {
                const accepted = await api.sendMessage(
                  resource.id,
                  { base_version: resource.version, content: chat, model_id: app.modelId },
                  key,
                );
                setParams({ task: accepted.task_id });
              },
              JSON.stringify([resource.version, chat, app.modelId]),
            )
          }
        >
          {chatAction.busy
            ? '正在提交…'
            : chatAction.cooldown
              ? `${chatAction.cooldown} 秒后重试`
              : '发送补充'}
        </button>
        {taskId && (!settledTask || result?.status === 'failed') && (
          <TaskProgress
            id={taskId}
            state={progress}
            onComplete={() => undefined}
            onDismiss={() => setParams({})}
          />
        )}
      </section>
    </>
  );
}
