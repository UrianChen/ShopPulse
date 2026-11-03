import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, ArrowRight, ChevronRight, Database, FileBarChart2, Upload } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { locale, t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { Paged, Schema } from '../../lib/types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './home.module.css';

type RecentReport = Schema<'Report'>;

export function WorkspaceHome() {
  useLanguage();
  const datasets = useQuery({
    queryKey: keys.datasets,
    queryFn: () => api<{ id: string }[]>('/datasets'),
  });
  const reports = useQuery({
    queryKey: keys.homeReports,
    queryFn: () => api<Paged<RecentReport>>('/reports?limit=4'),
  });
  return (
    <div>
      <section className={cx(ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('工作台')}</h1>
          <p>{t('从数据到决策。')}</p>
        </div>
        <Link className={ui.primary} to="/data">
          <Upload size={16} />
          {t('导入数据')}
        </Link>
      </section>
      <section className={css.homeHero}>
        <div>
          <span className={css.heroKicker}>{t('ShopPulse / 工作空间')}</span>
          <h2>
            {t('经营表现，')}
            <br />
            {t('一目了然。')}
          </h2>
          <Link className={ui.primary} to="/dashboard">
            {t('查看经营看板')}
            <ArrowRight size={16} />
          </Link>
        </div>
        <div className={css.homeTotals}>
          <Link to="/data">
            <span>{t('订单数据版本')}</span>
            <strong>{datasets.data?.length ?? '—'}</strong>
            <ArrowRight size={18} />
          </Link>
          <Link to="/reports">
            <span>{t('经营周报')}</span>
            <strong>{reports.data?.total ?? '—'}</strong>
            <ArrowRight size={18} />
          </Link>
        </div>
      </section>
      <section className={css.quickActions} aria-label={t('快捷入口')}>
        {[
          { to: '/data', icon: Database, title: t('整理数据'), description: t('导入订单与成本') },
          {
            to: '/dashboard',
            icon: Activity,
            title: t('查看表现'),
            description: t('销售、毛利与商品趋势'),
          },
          {
            to: '/reports/new',
            icon: FileBarChart2,
            title: t('生成周报'),
            description: t('分析变化，明确下一步'),
          },
        ].map(({ to, icon: Icon, title, description }, index) => (
          <Link className={cx(ui.panel, css.quickAction)} key={to} to={to}>
            <div className={css.quickActionTop}>
              <Icon size={22} />
              <span>0{index + 1}</span>
            </div>
            <h2>{title}</h2>
            <p>{description}</p>
            <ArrowRight size={18} />
          </Link>
        ))}
      </section>
      <section className={cx(ui.panel, css.homeReports)}>
        <div className={cx(css.panelTitle, ui.panelTitle)}>
          <h2>{t('最近周报')}</h2>
          <Link className={ui.textButton} to="/reports">
            {t('查看全部')}
            <ArrowRight size={14} />
          </Link>
        </div>
        <ErrorNotice error={datasets.error ?? reports.error} />
        {reports.isPending ? (
          <p className={ui.emptyCopy}>{t('正在读取报告…')}</p>
        ) : reports.data?.items.length ? (
          reports.data.items.map(r => (
            <Link className={css.homeReportRow} to={`/reports/${r.id}`} key={r.id}>
              <span className={ui.tileIcon}>
                <FileBarChart2 size={18} />
              </span>
              <div>
                <strong>{r.title}</strong>
                <small>{new Date(r.created_at).toLocaleDateString(locale())}</small>
              </div>
              <span className={cx(ui.importState, 'import-state')}>
                {['ready', 'ready_with_warnings'].includes(r.status)
                  ? t('已完成')
                  : r.status === 'failed'
                    ? t('执行失败')
                    : t('分析中')}
              </span>
              <ChevronRight size={16} />
            </Link>
          ))
        ) : (
          <div className={css.homeEmpty}>
            <FileBarChart2 size={28} />
            <p>{t('还没有周报')}</p>
            <Link className={ui.textButton} to="/reports/new">
              {t('生成第一份周报')}
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
