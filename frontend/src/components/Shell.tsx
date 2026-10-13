import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { isMock } from '../api';
import { useApp } from '../state';
import { useAction } from '../hooks';
import { ConfirmDialog, ErrorNotice, Loading } from './ui';
import type { Scenario } from '../api/mock';

export function Shell() {
  const app = useApp();
  const action = useAction();
  const navigate = useNavigate();
  const location = useLocation();
  const [consent, setConsent] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [scenario, setScenario] = useState<Scenario>('success');
  const notice = import.meta.env.VITE_PROCESSING_NOTICE?.trim();
  useEffect(() => {
    document.getElementById('main-content')?.focus();
  }, [location.pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳转至主要内容
      </a>
      <aside className="sidebar">
        <Link className="brand" to="/">
          <span className="brand-symbol" aria-hidden="true">
            r<span>+</span>
          </span>
          <span>
            ResumeDoctor<small>让经历有据可循</small>
          </span>
        </Link>
        <div className="nav-caption">我的诊断工作台</div>
        <nav aria-label="主导航">
          <NavLink to="/" end>
            <span>01</span>导入经历
          </NavLink>
          <NavLink
            to={app.workspace.profileId ? `/profiles/${app.workspace.profileId}` : '/profile'}
          >
            <span>02</span>确认档案
          </NavLink>
          <NavLink to="/jobs">
            <span>03</span>目标岗位
          </NavLink>
          <NavLink to="/history">
            <span>04</span>诊断报告
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <span className="mini-cross" aria-hidden="true">
            ＋
          </span>
          <h3>依据事实，发现下一步。</h3>
          <p>
            每一分都有证据，
            <br />
            每一步由你确认。
          </p>
        </div>
        {app.ready && (
          <button className="delete-link" onClick={() => setDeleting(true)}>
            删除本会话资料
          </button>
        )}
        <small className="sidebar-footer">ResumeDoctor / M1 Web</small>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            简历诊断 <span className="muted">/ 个人工作台</span>
          </span>
          <div className="topbar-right">
            <span className="session-dot" />
            匿名会话{' '}
            <span className="tag">
              {isMock || app.models.some((m) => m.provider === 'fake') ? '演示数据' : 'API 模式'}
            </span>
          </div>
        </header>
        {(isMock || app.models.some((m) => m.provider === 'fake')) && (
          <div className="demo-banner">
            <span>
              <strong>演示数据</strong> ·{' '}
              {isMock
                ? '仅在本标签页模拟接口；上传不解析真实文件，自定义材料不执行真实评分。请使用合成资料。'
                : '后端使用 fake 模型；结果仅供流程演示。'}
            </span>
            {isMock && (
              <label>
                模拟场景{' '}
                <select
                  aria-label="模拟场景"
                  value={scenario}
                  onChange={(e) => {
                    const v = e.target.value as Scenario;
                    setScenario(v);
                    void import('../api/mock').then((m) => m.setScenario(v));
                  }}
                >
                  <option value="success">正常完成</option>
                  <option value="partial">部分成功 / 仅评分</option>
                  <option value="failed">诊断全部失败</option>
                  <option value="parse-failed">提取失败</option>
                  <option value="conflict">下次保存冲突</option>
                  <option value="rate-limit">下次请求限流</option>
                </select>
              </label>
            )}
          </div>
        )}
        <main id="main-content" tabIndex={-1}>
          {!app.ready ? (
            <div className="consent-layout">
              <div>
                <p className="eyebrow">YOUR EXPERIENCE, WITH EVIDENCE</p>
                <h1>
                  让你的经历，
                  <br />
                  更接近理想岗位。
                </h1>
                <p className="lead">
                  从一份简历或一段对话开始。逐项核对经历与岗位要求，找到有依据的修改方向。
                </p>
                <div className="intro-steps">
                  <span>01 / 整理真实经历</span>
                  <span>02 / 确认目标岗位</span>
                  <span>03 / 获得行动建议</span>
                </div>
              </div>
              <section className="panel consent-panel">
                <p className="eyebrow">开始之前</p>
                <h2>你的资料，由你掌握</h2>
                <ul className="privacy-list">
                  <li>匿名会话有效期为 7 天，无需注册。</li>
                  <li>资料用于提取、匹配和生成建议；你可以随时删除本会话全部资料。</li>
                  <li>
                    原始文件解析结束后删除，最迟 24 小时清理；结构化资料随会话过期或删除清理。
                  </li>
                  <li>分数表示材料覆盖度，不代表录用概率。</li>
                </ul>
                <div className="notice">
                  {isMock
                    ? '本地演示：不向外部模型传输资料。模拟数据存储在本标签页，关闭标签页后清除。请勿输入真实个人资料。'
                    : notice ||
                      '服务端尚未配置公开的供应商与资料处理说明。请在前端配置 VITE_PROCESSING_NOTICE 后启用输入。'}
                </div>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  我已阅读并同意上述资料处理说明
                </label>
                <ErrorNotice
                  error={app.error}
                  retry={app.workspace.session ? app.reload : undefined}
                />
                {app.loading ? (
                  <Loading text="正在连接会话…" />
                ) : (
                  <button
                    className="button wide"
                    disabled={!consent || (!isMock && !notice)}
                    onClick={() => void app.start()}
                  >
                    同意并开始 <span aria-hidden="true">→</span>
                  </button>
                )}
              </section>
            </div>
          ) : (
            <Outlet />
          )}
        </main>
        <footer className="page-footer">
          只依据你提供的材料。缺少证据 ≠ 不具备能力。<span>资料确认后才会用于诊断。</span>
        </footer>
      </div>
      <ConfirmDialog
        open={deleting}
        title="删除本会话全部资料？"
        busy={action.busy}
        onCancel={() => setDeleting(false)}
        onConfirm={() =>
          void action.run(async () => {
            await app.remove();
            setDeleting(false);
            setConsent(false);
            navigate('/');
          })
        }
      >
        <p>档案、对话、岗位、报告与运行中的任务将一并删除，旧链接将失效。此操作无法撤销。</p>
        <ErrorNotice error={action.error} />
      </ConfirmDialog>
    </div>
  );
}
