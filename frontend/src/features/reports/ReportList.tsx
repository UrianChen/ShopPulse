import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, BookOpen, FileBarChart2, Plus } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { lastDay } from '../../lib/dates';
import { locale, t, useLanguage } from '../../lib/i18n';
import { keys, pollWhile } from '../../lib/queries';
import type { Paged } from '../../lib/types';
import { DONE, modes, states } from './labels';
import type { ReportSummary } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

export function ReportList() {
  useLanguage();
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: keys.reportList(offset),
    queryFn: () => api<Paged<ReportSummary>>(`/reports?offset=${offset}`),
    refetchInterval: pollWhile<Paged<ReportSummary>>(data =>
      data.items.some(r => !DONE.includes(r.status)),
    ),
  });
  return (
    <div className={css.reports}>
      <section className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('智能周报')}</h1>
          <p>{t('查看分析，追溯依据。')}</p>
        </div>
        <Link className={cx(css.primary, ui.primary)} to="/reports/new">
          <Plus size={16} />
          {t('生成周报')}
        </Link>
      </section>

      <ErrorNotice error={list.error} />
      {!list.data?.total ? (
        <section className={cx(css.panel, ui.panel, css.reportEmpty)}>
          <BookOpen size={32} />
          <h2>{list.isPending ? t('正在读取报告…') : t('从第一份经营周报开始')}</h2>
          <p>{t('选择订单数据与分析周期。')}</p>
          <Link className={cx(css.primary, ui.primary)} to="/reports/new">
            {t('生成第一份周报')}
            <ArrowRight size={15} />
          </Link>
        </section>
      ) : (
        <section className={css.reportList}>
          {list.data.items.map(r => (
            <Link
              to={`/reports/${r.id}`}
              className={cx(css.panel, ui.panel, css.reportListItem)}
              key={r.id}
            >
              <span className={cx(css.tileIcon, ui.tileIcon)}>
                <FileBarChart2 size={23} />
              </span>
              <div>
                <h2>{r.title}</h2>
                <p>
                  {r.query.start} {t('至')}
                  {lastDay(r.query.end_exclusive)} {t('· 修订')} {r.revision} ·{' '}
                  {new Date(r.created_at).toLocaleString(locale())}
                </p>
                <small>
                  {t(modes[r.generation_mode ?? ''] ?? '准备分析')} · {t(states[r.status])}
                </small>
              </div>
              <ArrowRight size={18} />
            </Link>
          ))}
        </section>
      )}
      {list.data && list.data.total > 20 && (
        <div className={cx(ui.pagination, forms.pagination)}>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={!offset}
            onClick={() => setOffset(offset - 20)}
          >
            {t('上一页')}
          </button>
          <span>
            {t('共')}
            {list.data.total} {t('份报告')}
          </span>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={offset + 20 >= list.data.total}
            onClick={() => setOffset(offset + 20)}
          >
            {t('下一页')}
          </button>
        </div>
      )}
    </div>
  );
}
