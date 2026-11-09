import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { isMock } from '../api';
import { useApp } from '../state';
import { useAction } from '../hooks';
import { usePointerGlow } from '../effects';
import { ConfirmDialog, ErrorNotice, Loading } from './ui';
import { Landing } from './Landing';
import { IconLogo, IconMoon, IconSun, IconSystem, IconTrash } from './Icons';
import type { Scenario } from '../api/mock';
import { useTheme, type ThemePreference } from '../theme';

const themeOptions: { value: ThemePreference; label: string; icon: typeof IconSun }[] = [
  { value: 'system', label: '跟随系统', icon: IconSystem },
  { value: 'light', label: '浅色', icon: IconSun },
  { value: 'dark', label: '深色', icon: IconMoon },
];

function focusConsentPanel(panel: HTMLElement | null) {
  panel?.focus({ preventScroll: true });
  panel?.scrollIntoView({ block: 'start', behavior: 'instant' });
}

export function Shell() {
  const theme = useTheme();
  const app = useApp();
  const action = useAction();
  const navigate = useNavigate();
  const location = useLocation();
  const [consent, setConsent] = useState(false);
  const [consentPrompt, setConsentPrompt] = useState(false);
  const consentPanel = useRef<HTMLElement>(null);
  const deepLinkNeedsConsent = !app.ready && !app.loading && location.pathname !== '/';
  const [deleting, setDeleting] = useState(false);
  const [scenario, setScenario] = useState<Scenario>('success');
  const notice = import.meta.env.VITE_PROCESSING_NOTICE?.trim();
  const retentionNotice = import.meta.env.VITE_RETENTION_NOTICE?.trim();
  const demo = isMock || app.models.some((m) => m.provider === 'fake');
  const firstRoute = useRef(true);
  const startedHere = useRef(false);
  usePointerGlow();
  useEffect(() => {
    // After consenting from the bottom of the landing page, show the workspace
    // from its top rather than at the old scroll position.
    if (!app.ready || !startedHere.current) return;
    startedHere.current = false;
    window.scrollTo({ top: 0, behavior: 'instant' });
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [app.ready]);
  useEffect(() => {
    // Move focus to the new page for assistive technology without letting the
    // focus scroll hide the header; route changes start at the top instead.
    if (!firstRoute.current) window.scrollTo({ top: 0, behavior: 'instant' });
    firstRoute.current = false;
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [location.pathname]);
  useEffect(() => {
    if (deepLinkNeedsConsent) focusConsentPanel(consentPanel.current);
  }, [deepLinkNeedsConsent, location.pathname]);
  const requireConsent = (event: MouseEvent<HTMLAnchorElement>) => {
    if (app.ready) return;
    event.preventDefault();
    setConsentPrompt(true);
    focusConsentPanel(consentPanel.current);
  };
  return (
    <div className="app-shell">
      <div className="ambient" aria-hidden="true">
        <div className="ambient-blob b1" />
        <div className="ambient-blob b2" />
        <div className="ambient-blob b3" />
        <div className="ambient-blob b4" />
        <div className="ambient-grid" />
        <div className="ambient-meteors">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="ambient-spot" />
        <div className="ambient-noise" />
      </div>
      <a className="skip-link" href="#main-content">
        跳转至主要内容
      </a>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" to="/">
            <span className="brand-mark" aria-hidden="true">
              <IconLogo />
            </span>
            <span className="brand-text">
              ResumeDoctor<small>让经历有据可循</small>
            </span>
          </Link>
          <nav className="step-nav" aria-label="主导航">
            <NavLink to="/" end onClick={requireConsent}>
              <span className="step-index">01</span> <span className="step-label">导入经历</span>
            </NavLink>
            <NavLink
              to={app.workspace.profileId ? `/profiles/${app.workspace.profileId}` : '/profile'}
              onClick={requireConsent}
            >
              <span className="step-index">02</span> <span className="step-label">确认档案</span>
            </NavLink>
            <NavLink to="/jobs" onClick={requireConsent}>
              <span className="step-index">03</span> <span className="step-label">目标岗位</span>
            </NavLink>
            <NavLink to="/history" onClick={requireConsent}>
              <span className="step-index">04</span> <span className="step-label">诊断报告</span>
            </NavLink>
          </nav>
          <div className="header-tools">
            <div className="theme-switch" role="group" aria-label="外观模式">
              {themeOptions.map(({ value, label, icon: ThemeIcon }) => (
                <button
                  key={value}
                  type="button"
                  aria-label={label}
                  title={label}
                  aria-pressed={theme.preference === value}
                  onClick={() => theme.changeTheme(value)}
                >
                  <ThemeIcon />
                </button>
              ))}
            </div>
            {app.ready && (
              <span className="session-chip">
                <span className="session-dot" aria-hidden="true" />
                匿名会话
                <span className="session-mode">{demo ? '演示数据' : '在线服务'}</span>
              </span>
            )}
            {app.ready && (
              <button type="button" className="delete-link" onClick={() => setDeleting(true)}>
                <IconTrash />
                <span>删除本会话资料</span>
              </button>
            )}
          </div>
        </div>
      </header>
      {demo && (
        <div className="demo-banner">
          <div className="demo-banner-inner">
            <div className="demo-banner-text">
              <span>
                <strong>演示数据</strong> ·{' '}
                {isMock
                  ? '仅在本标签页模拟接口；上传不解析真实文件，自定义材料不执行真实评分。请使用合成资料。'
                  : '后端使用 fake 模型；结果仅供流程演示。'}
              </span>
            </div>
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
        </div>
      )}
      <main id="main-content" tabIndex={-1}>
        {!app.ready ? (
          <Landing>
            <section
              className="panel consent-panel"
              ref={consentPanel}
              tabIndex={-1}
              aria-labelledby="consent-title"
            >
              <p className="eyebrow">开始之前</p>
              <h2 id="consent-title">你的资料，由你掌握</h2>
              <div role="status">
                {(deepLinkNeedsConsent || (consentPrompt && !app.loading)) && (
                  <p className="notice warning">请先阅读并同意资料处理说明，再继续。</p>
                )}
              </div>
              <ul className="privacy-list">
                <li>匿名会话有效期为 7 天，无需注册。</li>
                <li>资料用于提取、匹配和生成建议；你可以随时删除本会话全部资料。</li>
                <li>
                  {retentionNotice ||
                    '原始文件解析结束后删除，最迟 24 小时清理；结构化资料随会话过期或删除清理。'}
                </li>
                <li>分数只说明覆盖了多少要求，不代表录用概率。</li>
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
                  onClick={() => {
                    setConsentPrompt(false);
                    startedHere.current = true;
                    void app.start();
                  }}
                >
                  同意并开始 <span aria-hidden="true">→</span>
                </button>
              )}
            </section>
          </Landing>
        ) : (
          <>
            {Boolean(app.error) && (
              <p className="notice warning">
                AI 模型列表暂时无法读取，已有报告和基础诊断仍可使用。
                <button className="text-button" onClick={app.reload}>
                  重新读取模型列表
                </button>
              </p>
            )}
            <Outlet />
          </>
        )}
      </main>
      <footer className="page-footer">
        只依据你提供的材料。缺少证据 ≠ 不具备能力。<span>资料确认后才会用于诊断。</span>
      </footer>
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
            // The landing page also lives at "/": show it from the top.
            window.scrollTo({ top: 0, behavior: 'instant' });
          })
        }
      >
        <p>档案、对话、岗位、报告与运行中的任务将一并删除，旧链接将失效。此操作无法撤销。</p>
        <ErrorNotice error={action.error} />
      </ConfirmDialog>
    </div>
  );
}
