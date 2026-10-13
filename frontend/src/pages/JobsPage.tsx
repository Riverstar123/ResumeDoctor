import { useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, isMock } from '../api';
import { useApp } from '../state';
import { useAction, useLoad } from '../hooks';
import type { Job } from '../types';
import { JobEditor } from '../components/JobEditor';
import {
  Empty,
  ErrorNotice,
  Heading,
  Loading,
  ModelPicker,
  TaskProgress,
  useCanModel,
} from '../components/ui';

export function JobsPage() {
  const { workspace } = useApp();
  return (
    <>
      <Heading eyebrow="03 / 选择目标" title="让目标岗位更清楚">
        每个岗位独立评分。粘贴 JD、核对要求，选择 1–5 个已确认岗位开始诊断。
      </Heading>
      {!workspace.profileId ? (
        <Empty title="先准备你的经历" to="/">
          创建并确认档案，再添加目标岗位。
        </Empty>
      ) : (
        <JobsWorkspace profileId={workspace.profileId} />
      )}
    </>
  );
}
function JobsWorkspace({ profileId }: { profileId: string }) {
  const app = useApp();
  const action = useAction();
  const diagnose = useAction();
  const navigate = useNavigate();
  const [raw, setRaw] = useState('');
  const [company, setCompany] = useState('');
  const [editing, setEditing] = useState('');
  const [dirty, setDirty] = useState(false);
  const [addedJob, setAddedJob] = useState('');
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const [updates, setUpdates] = useState<Record<string, Job>>({});
  const [params, setParams] = useSearchParams();
  const taskId = params.get('task');
  const profile = useLoad((signal) => api.profile(profileId, undefined, signal), profileId);
  const jobs = useLoad(
    (signal) => Promise.all(app.workspace.jobIds.map((id) => api.job(id, undefined, signal))),
    app.workspace.jobIds.join(','),
    // Adding a job changes the key; keeping the previous list mounted means the
    // open JD editor is not unmounted (and does not drop unsaved edits).
    { keepPreviousData: true },
  );
  const list = (jobs.data || []).map((j) => updates[j.id] || j);
  const selected = list.filter((j) => app.workspace.selectedJobIds.includes(j.id));
  const canExtract = useCanModel('job_extract');
  const canDiagnose = useCanModel('diagnosis_report');
  const busy = action.busy || Boolean(taskId);
  const addJob = () =>
    void action.run(
      async (key) => {
        const task = await api.createJob(
          { raw_text: raw, company_context: company, model_id: app.modelId },
          key,
        );
        setParams({ task: task.task_id });
      },
      JSON.stringify([raw, company, app.modelId]),
    );
  const start = () =>
    void diagnose.run(
      async (key) => {
        if (!profile.data) return;
        const result = await api.diagnose(
          {
            profile: { id: profile.data.id, version: profile.data.version },
            jobs: selected.map((j) => ({ id: j.id, version: j.version })),
            model_id: app.modelId,
          },
          key,
        );
        app.patch({
          diagnosisIds: [
            result.diagnosis_id,
            ...app.workspace.diagnosisIds.filter((id) => id !== result.diagnosis_id),
          ],
        });
        navigate(`/diagnoses/${result.diagnosis_id}`);
      },
      JSON.stringify([profile.data?.version, selected.map((j) => [j.id, j.version]), app.modelId]),
    );
  return (
    <>
      <ErrorNotice error={profile.error} retry={profile.reload} />
      <ErrorNotice error={jobs.error} retry={jobs.reload} />
      {profile.loading || jobs.loading ? <Loading /> : null}
      {profile.data && (
        <div className={`notice ${profile.data.confirmed ? 'success' : 'warning'}`}>
          <strong>
            当前档案 v{profile.data.version} · {profile.data.confirmed ? '已确认' : '尚未确认'}
          </strong>
          <span> {profile.data.content.facts.length} 条事实</span>
          <Link className="text-link" to={`/profiles/${profileId}`}>
            查看 / 确认档案 →
          </Link>
        </div>
      )}
      <div className="jobs-grid">
        <section className="panel">
          <div className="section-heading">
            <h2>添加目标岗位</h2>
            <span className="tag">最多选择 5 个</span>
          </div>
          <label className="field">
            职位描述（JD）
            <textarea
              rows={7}
              maxLength={20000}
              value={raw}
              disabled={busy}
              onChange={(e) => setRaw(e.target.value)}
              placeholder="粘贴完整职位描述，保留技能、经验、学历等要求的原文。"
            />
          </label>
          <div className="row">
            <small>{raw.length.toLocaleString()} / 20,000 字符</small>
            {isMock && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void import('../api/mock').then((m) => setRaw(m.demoJob))}
              >
                填入示例 JD
              </button>
            )}
          </div>
          <label className="field">
            公司背景（可选）
            <textarea
              rows={3}
              maxLength={10000}
              value={company}
              disabled={busy}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="团队、业务或产品背景，仅用于解释建议，不自动计分。"
            />
          </label>
          <small>{company.length.toLocaleString()} / 10,000 字符</small>
          <ModelPicker capability="job_extract" disabled={busy} />
          <ErrorNotice error={action.error} />
          <button
            className="button wide"
            disabled={busy || dirty || !raw.trim() || !canExtract || action.cooldown > 0}
            onClick={addJob}
          >
            {action.busy
              ? '正在提交…'
              : action.cooldown
                ? `${action.cooldown} 秒后重试`
                : '提取岗位要求'}{' '}
            <span aria-hidden="true">→</span>
          </button>
          {dirty && <p className="hint">当前 JD 有未保存的修改。先保存新版本，再提取新的岗位。</p>}
          {taskId && (
            <TaskProgress
              id={taskId}
              onComplete={(task) => {
                if (task.result?.resource_type === 'job') {
                  const id = task.result.resource_id;
                  app.patch({
                    jobIds: [...new Set([...app.workspace.jobIds, id])],
                    selectedJobIds:
                      app.workspace.selectedJobIds.length < 5
                        ? [...new Set([...app.workspace.selectedJobIds, id])]
                        : app.workspace.selectedJobIds,
                  });
                  setParams({});
                  setRaw('');
                  setCompany('');
                  // Do not steal the editor while it holds unsaved edits: the user
                  // may have started typing while this task was still running.
                  if (dirtyRef.current) setAddedJob(id);
                  else setEditing(id);
                }
              }}
              onDismiss={() => setParams({})}
            />
          )}
        </section>
        <aside className="panel job-list">
          <div className="section-heading">
            <h2>本次诊断</h2>
            <span className="count">{selected.length} / 5</span>
          </div>
          {!list.length && <p className="empty-inline">还没有岗位。添加 JD 后，逐项检查并确认。</p>}
          {list.map((job) => (
            <div className={`job-list-item ${editing === job.id ? 'active' : ''}`} key={job.id}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  aria-label={`选择 ${job.content.title}`}
                  checked={app.workspace.selectedJobIds.includes(job.id)}
                  disabled={
                    diagnose.busy ||
                    (!app.workspace.selectedJobIds.includes(job.id) && selected.length >= 5)
                  }
                  onChange={(e) =>
                    app.patch({
                      selectedJobIds: e.target.checked
                        ? [...app.workspace.selectedJobIds, job.id]
                        : app.workspace.selectedJobIds.filter((id) => id !== job.id),
                    })
                  }
                />
                <span>
                  <strong>{job.content.title}</strong>
                  <small>
                    v{job.version} · {job.confirmed ? '已确认' : '待确认'} ·{' '}
                    {job.content.requirements.length} 条要求
                  </small>
                </span>
              </label>
              <button
                className="text-button"
                disabled={dirty && editing !== job.id}
                onClick={() => setEditing(job.id)}
              >
                核对要求
              </button>
            </div>
          ))}
          <ModelPicker capability="diagnosis_report" disabled={diagnose.busy} />
          <ErrorNotice error={diagnose.error} />
          <p className="hint">
            {dirty
              ? '请先保存当前 JD 的修改。'
              : selected.some((j) => !j.confirmed)
                ? '所选岗位尚未全部确认。'
                : '每个岗位使用各自的要求，分数互不影响。'}
          </p>
          <button
            className="button wide"
            disabled={
              diagnose.busy ||
              diagnose.cooldown > 0 ||
              busy ||
              dirty ||
              !canDiagnose ||
              !profile.data?.confirmed ||
              !selected.length ||
              selected.length > 5 ||
              selected.some((j) => !j.confirmed) ||
              Boolean(jobs.error)
            }
            onClick={start}
          >
            {diagnose.busy
              ? '正在创建诊断…'
              : diagnose.cooldown
                ? `${diagnose.cooldown} 秒后重试`
                : `开始诊断 ${selected.length || ''} 个岗位`}
          </button>
        </aside>
      </div>
      {addedJob && editing !== addedJob && (
        <div className="notice warning">
          <strong>新岗位已完成提取，但当前 JD 还有未保存的修改</strong>
          <p>
            {list.find((j) => j.id === addedJob)?.content.title || '新岗位'}
            已加入本次诊断。你的修改已保留，切换岗位会放弃它们。
          </p>
          <button
            className="button secondary small"
            onClick={() => {
              setDirty(false);
              setEditing(addedJob);
              setAddedJob('');
            }}
          >
            跳到新岗位并放弃当前修改
          </button>
        </div>
      )}
      {list.find((j) => j.id === editing) && (
        <JobEditor
          key={editing}
          initial={list.find((j) => j.id === editing)!}
          onSaved={(job) => setUpdates((previous) => ({ ...previous, [job.id]: job }))}
          onDirty={setDirty}
        />
      )}
    </>
  );
}
