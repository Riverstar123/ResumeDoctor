import { useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, isMock } from '../api';
import { useApp } from '../state';
import { useAction } from '../hooks';
import { emptyProfile, validateFile } from '../validation';
import { ErrorNotice, Heading, ModelPicker, TaskProgress, useCanModel } from '../components/ui';

type IntakeRequest =
  | { mode: 'file'; file: File; modelId: string }
  | { mode: 'chat'; profileId: string; baseVersion: number; content: string; modelId: string };

export function IntakePage() {
  const [mode, setMode] = useState<'file' | 'chat'>('file');
  const [file, setFile] = useState<File>();
  const [text, setText] = useState('');
  const [fileError, setFileError] = useState('');
  const createdProfile = useRef<string | undefined>(undefined);
  const app = useApp();
  const action = useAction();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const taskId = params.get('task');
  const canModel = useCanModel(mode === 'file' ? 'profile_extract' : 'profile_chat');
  const busy = action.busy || Boolean(taskId);
  const chooseFile = (next?: File) => {
    setFile(next);
    setFileError(next ? validateFile(next) : '');
    action.clearError();
  };
  const submit = () =>
    void action.run(
      async (key, request: IntakeRequest | null) => {
        if (!request) return;
        if (request.mode === 'file') {
          const accepted = await api.upload(request.file, request.modelId, key);
          setParams({ task: accepted.task_id });
          return;
        }
        const accepted = await api.sendMessage(
          request.profileId,
          {
            base_version: request.baseVersion,
            content: request.content,
            model_id: request.modelId,
          },
          `${key}:message`,
        );
        app.patch({ profileId: request.profileId });
        setParams({ task: accepted.task_id });
      },
      JSON.stringify([mode, file?.name, file?.size, file?.lastModified, text, app.modelId]),
      async (key): Promise<IntakeRequest | null> => {
        if (mode === 'file') {
          if (!file) return null;
          const message = validateFile(file);
          if (message) {
            setFileError(message);
            return null;
          }
          return { mode: 'file', file, modelId: app.modelId };
        }
        if (!text.trim()) return null;
        // Resolve the profile version once. Re-reading it on a retry would send a
        // different base_version under the same Idempotency-Key (409 conflict).
        let profileId = createdProfile.current;
        if (!profileId) {
          const created = await api.createProfile(emptyProfile(), `${key}:profile`);
          createdProfile.current = created.id;
          profileId = created.id;
        }
        const latest = await api.profile(profileId);
        return {
          mode: 'chat',
          profileId,
          baseVersion: latest.version,
          content: text,
          modelId: app.modelId,
        };
      },
    );
  return (
    <>
      <Heading eyebrow="01 / 整理经历" title="从真实经历开始">
        选择你习惯的方式，我们一起把经历整理成有依据的档案。
      </Heading>
      <div className="intake-grid">
        <section className="panel intake-panel">
          <div className="segmented" role="group" aria-label="输入方式">
            <button aria-pressed={mode === 'file'} disabled={busy} onClick={() => setMode('file')}>
              上传简历
            </button>
            <button aria-pressed={mode === 'chat'} disabled={busy} onClick={() => setMode('chat')}>
              对话整理
            </button>
          </div>
          {mode === 'file' ? (
            <>
              <div
                className={`dropzone ${fileError ? 'invalid' : ''}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!busy) chooseFile(e.dataTransfer.files[0]);
                }}
              >
                <span className="document-symbol" aria-hidden="true">
                  ↑
                </span>
                <h2>{file ? file.name : '把简历放在这里'}</h2>
                <p>
                  {file
                    ? `${(file.size / 1024).toFixed(1)} KiB · 已选取，可重新选择`
                    : '拖入文件，或点击选择简历'}
                </p>
                <label className="button secondary file-button">
                  {file ? '更换文件' : '选择文件'}
                  <input
                    type="file"
                    aria-label="选择简历文件"
                    accept=".pdf,.docx"
                    disabled={busy}
                    onChange={(e) => chooseFile(e.target.files?.[0])}
                  />
                </label>
                <small>文字 PDF / DOCX · 最大 10 MiB · 最多 20 页</small>
              </div>
              {fileError && (
                <p className="field-error" role="alert">
                  {fileError}
                </p>
              )}
              <p className="hint">
                扫描件暂不支持。文件内容与页数由服务端校验；解析失败可切换对话。
              </p>
            </>
          ) : (
            <>
              <h2>说说你做过的事</h2>
              <p className="muted">
                可以从项目、工作或学习经历开始。不确定的内容留空，不需要编造成果数字。
              </p>
              <label className="field">
                经历描述
                <textarea
                  value={text}
                  disabled={busy}
                  rows={8}
                  maxLength={8000}
                  placeholder="我在什么项目里，承担了哪些工作，用到了什么技能？有什么可以核实的结果？"
                  onChange={(e) => setText(e.target.value)}
                />
              </label>
              <div className="row">
                <small>{text.length.toLocaleString()} / 8,000 字符</small>
                {isMock && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => void import('../api/mock').then((m) => setText(m.demoText))}
                  >
                    填入合成示例
                  </button>
                )}
              </div>
            </>
          )}
          <ModelPicker
            capability={mode === 'file' ? 'profile_extract' : 'profile_chat'}
            disabled={busy}
          />
          <ErrorNotice error={action.error} />
          <button
            className="button wide"
            disabled={
              busy ||
              action.cooldown > 0 ||
              !canModel ||
              (mode === 'file' ? !file || Boolean(fileError) : !text.trim())
            }
            onClick={submit}
          >
            {action.busy
              ? '正在提交…'
              : action.cooldown
                ? `${action.cooldown} 秒后可重试`
                : mode === 'file'
                  ? '上传并整理档案'
                  : '发送并生成草稿'}
            <span aria-hidden="true">→</span>
          </button>
        </section>
        <aside className="intake-aside">
          <div className="paper-illustration" aria-hidden="true">
            <span className="paper-tag">EXPERIENCE / EVIDENCE</span>
            <div className="paper-title">
              你的经历
              <br />
              <em>值得被看见。</em>
            </div>
            <div className="paper-lines">
              <i />
              <i />
              <i />
            </div>
            <span className="paper-stamp">
              有据可循
              <br />
              RESUME DOCTOR
            </span>
          </div>
          <h3>先核对，再诊断</h3>
          <p>提取结果只是草稿。教育、工作、项目、技能及其原文证据，都可以在下一步检查和修改。</p>
          <div className="aside-divider" />
          <h3>每一次修改，都有新版本</h3>
          <p>只有你确认的版本才用于诊断。补充经历后，旧报告仍保留原来的依据。</p>
          {app.workspace.profileId && (
            <Link className="text-link" to={`/profiles/${app.workspace.profileId}`}>
              继续已有档案 →
            </Link>
          )}
        </aside>
      </div>
      {taskId && (
        <TaskProgress
          id={taskId}
          onComplete={(task) => {
            if (task.result?.resource_type === 'profile') {
              app.patch({ profileId: task.result.resource_id });
              // Associate parsing notes with this profile as well as the initial
              // URL, so ordinary navigation and later chat tasks cannot lose them.
              if (task.result.warnings?.length) {
                app.rememberProfileWarningTask(task.result.resource_id, task.id);
              }
              const note = task.result.warnings?.length
                ? `?task=${encodeURIComponent(task.id)}`
                : '';
              navigate(`/profiles/${task.result.resource_id}${note}`, { replace: true });
            }
          }}
          onDismiss={() => setParams({})}
        />
      )}
    </>
  );
}
