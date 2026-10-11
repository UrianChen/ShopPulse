import { t, useLanguage, locale, message } from './lib/i18n';
import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { Activity, ArrowRight, ChevronRight, CircleHelp, Database, FileBarChart2, Globe2, LayoutDashboard, Server, Settings2, Upload } from 'lucide-react';
import { api, ApiError } from './lib/api';
import type { Workspace } from './lib/api';
import { NewReport, ReportDetail, ReportList } from './features/reports/Reports';
import { Operations } from './features/Operations';
import { ModelSettings } from './features/models/ModelSettings';
import { Dashboard } from './features/dashboard/Dashboard';
import { DataCenter } from './features/imports/DataCenter';
import { setLanguage } from './lib/i18n';
import { version } from '../package.json';

type RecentReport = { id: string; title: string; status: string; created_at: string };
function ErrorNotice({ error }: { error: Error | null }) {
  useLanguage();
  return error && <div className="error-notice" role="alert">{message(error.message)}{error instanceof ApiError && <small>{error.code}</small>}</div>;
}

function WorkspaceHome() {
  useLanguage();
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: () => api<{ id: string }[]>('/datasets') });
  const reports = useQuery({ queryKey: ['home-reports'], queryFn: () => api<{ total: number; items: RecentReport[] }>('/reports?limit=4') });
  return <div className="home"><section className="page-heading"><div><h1>{t("工作台")}</h1><p>{t("从数据到决策。")}</p></div><Link className="primary" to="/data"><Upload size={16} />{t("导入数据")}</Link></section>
    <section className="home-hero"><div><span className="hero-kicker">{t("ShopPulse / 工作空间")}</span><h2>{t("经营表现，")}<br />{t("一目了然。")}</h2><Link className="primary" to="/dashboard">{t("查看经营看板")}<ArrowRight size={16} /></Link></div>
      <div className="home-totals"><Link to="/data"><span>{t("订单数据版本")}</span><strong>{datasets.data?.length ?? '—'}</strong><ArrowRight size={18} /></Link><Link to="/reports"><span>{t("经营周报")}</span><strong>{reports.data?.total ?? '—'}</strong><ArrowRight size={18} /></Link></div>
    </section>
    <section className="quick-actions" aria-label={t("快捷入口")}>{[
      { to: '/data', icon: Database, title: t("整理数据"), description: t("导入订单与成本") },
      { to: '/dashboard', icon: Activity, title: t("查看表现"), description: t("销售、毛利与商品趋势") },
      { to: '/reports/new', icon: FileBarChart2, title: t("生成周报"), description: t("分析变化，明确下一步") },
    ].map(({ to, icon: Icon, title, description }, index) => <Link className="panel quick-action" key={to} to={to}><div className="quick-action-top"><Icon size={22} /><span>0{index + 1}</span></div><h2>{title}</h2><p>{description}</p><ArrowRight size={18} /></Link>)}</section>
    <section className="panel home-reports"><div className="panel-title"><h2>{t("最近周报")}</h2><Link className="text-button" to="/reports">{t("查看全部")}<ArrowRight size={14} /></Link></div><ErrorNotice error={datasets.error ?? reports.error} />
      {reports.isPending ? <p className="empty-copy">{t("正在读取报告…")}</p> : reports.data?.items.length ? reports.data.items.map(r => <Link className="home-report-row" to={`/reports/${r.id}`} key={r.id}><span className="tile-icon"><FileBarChart2 size={18} /></span><div><strong>{r.title}</strong><small>{new Date(r.created_at).toLocaleDateString(locale())}</small></div><span className="import-state">{['ready','ready_with_warnings'].includes(r.status) ? t("已完成") : r.status === 'failed' ? t("执行失败") : t("分析中")}</span><ChevronRight size={16} /></Link>) : <div className="home-empty"><FileBarChart2 size={28} /><p>{t("还没有周报")}</p><Link className="text-button" to="/reports/new">{t("生成第一份周报")}</Link></div>}
    </section>
  </div>;
}

function Shell() {
  const language = useLanguage();
  const location = useLocation();
  const workspace = useQuery({ queryKey: ['workspace'], queryFn: () => api<Workspace>('/workspace') });
  const links = [{ to: '/', label: t("工作台"), icon: LayoutDashboard }, { to: '/data', label: t("数据中心"), icon: Database }, { to: '/dashboard', label: t("经营看板"), icon: Activity }, { to: '/reports', label: t("智能周报"), icon: FileBarChart2 }, { to: '/settings/models', label: t("模型设置"), icon: Settings2 }, { to: '/operations', label: t("运行管理"), icon: Server }];
  const current = links.find(l => l.to !== '/' && location.pathname.startsWith(l.to)) ?? links[0];
  return <div className="app-shell"><a className="skip-link" href="#main-content">{t("跳到主要内容")}</a><aside className="sidebar"><Link className="brand" to="/" aria-label="ShopPulse"><span className="brand-icon"><Activity size={23} /></span>ShopPulse<span className="brand-dot">.</span></Link>
    <div className="workspace-switch"><span className="workspace-avatar">S</span><strong>{workspace.data?.name ?? t("我的店铺")}</strong></div>
    <nav aria-label={t("主导航")}>{links.map(({to,label,icon:Icon}) => <NavLink key={to} to={to} end={to === '/'}><Icon size={19} /><span>{t(label)}</span></NavLink>)}</nav>
    <div className="sidebar-bottom"><span className="dot" />ShopPulse <span>{version}</span></div>
  </aside><div className="main-shell"><header className="topbar"><span className="breadcrumb">{current.label}</span><div className="language-control"><Globe2 size={16} /><div role="group" aria-label={t("界面语言")}><button type="button" lang="zh-CN" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button><button type="button" lang="en" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button></div></div></header>
    <main id="main-content" className="content" tabIndex={-1}><ErrorNotice error={workspace.error} /><Routes><Route path="/" element={<WorkspaceHome />} /><Route path="/data" element={<DataCenter />} /><Route path="/dashboard" element={<Dashboard />} /><Route path="/settings/models" element={<ModelSettings />} /><Route path="/operations" element={<Operations />} /><Route path="/reports" element={<ReportList />} /><Route path="/reports/new" element={<NewReport />} /><Route path="/reports/:reportId" element={<ReportDetail />} /><Route path="*" element={<div className="panel not-found"><CircleHelp size={32} /><h1>{t("页面不存在")}</h1><Link className="primary" to="/">{t("返回工作台")}</Link></div>} /></Routes></main>
  </div></div>;
}
export function App() {
  useLanguage(); return <Shell />; }
