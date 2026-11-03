import { lazy, Suspense } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import {
  Activity,
  CalendarClock,
  CircleHelp,
  Database,
  FileBarChart2,
  Globe2,
  LayoutDashboard,
  Server,
  Settings2,
} from 'lucide-react';
import { ErrorNotice } from './components/ErrorNotice';
import { WorkspaceHome } from './features/home/WorkspaceHome';
import { api } from './lib/api';
import { setLanguage, t, useLanguage } from './lib/i18n';
import { keys } from './lib/queries';
import type { Workspace } from './lib/types';
import { version } from '../package.json';
import { cx } from './lib/cx';
import ui from './components/ui.module.css';
import css from './App.module.css';

// Pages load on first visit, so the first screen does not download every feature.
const DataCenter = lazy(() =>
  import('./features/imports/DataCenter').then(m => ({ default: m.DataCenter })),
);
const Dashboard = lazy(() =>
  import('./features/dashboard/Dashboard').then(m => ({ default: m.Dashboard })),
);
const ModelSettings = lazy(() =>
  import('./features/models/ModelSettings').then(m => ({ default: m.ModelSettings })),
);
const Operations = lazy(() =>
  import('./features/Operations').then(m => ({ default: m.Operations })),
);
const Automation = lazy(() =>
  import('./features/automation/Automation').then(m => ({ default: m.Automation })),
);
const ReportList = lazy(() =>
  import('./features/reports/Reports').then(m => ({ default: m.ReportList })),
);
const NewReport = lazy(() =>
  import('./features/reports/Reports').then(m => ({ default: m.NewReport })),
);
const ReportDetail = lazy(() =>
  import('./features/reports/Reports').then(m => ({ default: m.ReportDetail })),
);

function Shell() {
  const language = useLanguage();
  const location = useLocation();
  const workspace = useQuery({
    queryKey: keys.workspace,
    queryFn: () => api<Workspace>('/workspace'),
  });
  const links = [
    { to: '/', label: t('工作台'), icon: LayoutDashboard },
    { to: '/data', label: t('数据中心'), icon: Database },
    { to: '/dashboard', label: t('经营看板'), icon: Activity },
    { to: '/reports', label: t('智能周报'), icon: FileBarChart2 },
    { to: '/automation', label: t('自动化'), icon: CalendarClock },
    { to: '/settings/models', label: t('模型设置'), icon: Settings2 },
    { to: '/operations', label: t('运行管理'), icon: Server },
  ];
  const current = links.find(l => l.to !== '/' && location.pathname.startsWith(l.to)) ?? links[0];
  return (
    <div className={css.appShell}>
      <a className={css.skipLink} href="#main-content">
        {t('跳到主要内容')}
      </a>
      <aside className={css.sidebar}>
        <Link className={css.brand} to="/" aria-label="ShopPulse">
          <span className={css.brandIcon}>
            <Activity size={23} />
          </span>
          ShopPulse<span className={css.brandDot}>.</span>
        </Link>
        <div className={css.workspaceSwitch}>
          <span className={css.workspaceAvatar}>S</span>
          <strong>{workspace.data?.name ?? t('我的店铺')}</strong>
        </div>
        <nav aria-label={t('主导航')}>
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => (isActive ? css.active : undefined)}
            >
              <Icon size={19} />
              <span>{t(label)}</span>
            </NavLink>
          ))}
        </nav>
        <div className={css.sidebarBottom}>
          <span className={css.dot} />
          ShopPulse <span>{version}</span>
        </div>
      </aside>
      <div className={css.mainShell}>
        <header className={css.topbar}>
          <span className={css.breadcrumb}>{current.label}</span>
          <div className={css.languageControl}>
            <Globe2 size={16} />
            <div role="group" aria-label={t('界面语言')}>
              <button
                type="button"
                lang="zh-CN"
                aria-pressed={language === 'zh'}
                onClick={() => setLanguage('zh')}
              >
                中文
              </button>
              <button
                type="button"
                lang="en"
                aria-pressed={language === 'en'}
                onClick={() => setLanguage('en')}
              >
                EN
              </button>
            </div>
          </div>
        </header>
        <main id="main-content" className={css.content} tabIndex={-1}>
          <ErrorNotice error={workspace.error} />
          <Suspense fallback={<p className={ui.emptyCopy}>{t('读取中…')}</p>}>
            <Routes>
              <Route path="/" element={<WorkspaceHome />} />
              <Route path="/data" element={<DataCenter />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/settings/models" element={<ModelSettings />} />
              <Route path="/operations" element={<Operations />} />
              <Route path="/automation" element={<Automation />} />
              <Route path="/reports" element={<ReportList />} />
              <Route path="/reports/new" element={<NewReport />} />
              <Route path="/reports/:reportId" element={<ReportDetail />} />
              <Route
                path="*"
                element={
                  <div className={cx(ui.panel, css.notFound)}>
                    <CircleHelp size={32} />
                    <h1>{t('页面不存在')}</h1>
                    <Link className={ui.primary} to="/">
                      {t('返回工作台')}
                    </Link>
                  </div>
                }
              />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
export function App() {
  useLanguage();
  return <Shell />;
}
