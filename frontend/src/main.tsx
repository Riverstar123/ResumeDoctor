import { StrictMode, Component, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppProvider } from './state';
import { Shell } from './components/Shell';
import { Empty } from './components/ui';
import { IntakePage } from './pages/IntakePage';
import { ProfilePage } from './pages/ProfilePage';
import { JobsPage } from './pages/JobsPage';
import { ReportPage, HistoryPage } from './pages/ReportPage';
import './styles.css';

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="empty" role="alert">
        <h1>页面暂时无法显示</h1>
        <p>请刷新后重试。已提交的资料可由原链接重新读取。</p>
        <button className="button" onClick={() => location.reload()}>
          刷新页面
        </button>
      </div>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AppProvider>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<IntakePage />} />
              <Route path="profiles/:id" element={<ProfilePage />} />
              <Route
                path="profile"
                element={
                  <Empty title="还没有档案" to="/">
                    上传简历或描述经历，先创建一份档案。
                  </Empty>
                }
              />
              <Route path="jobs" element={<JobsPage />} />
              <Route path="diagnoses/:id" element={<ReportPage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route
                path="*"
                element={
                  <Empty title="没有找到这个页面" to="/" action="返回输入页">
                    请检查地址，或从输入页重新开始。
                  </Empty>
                }
              />
            </Route>
          </Routes>
        </AppProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
