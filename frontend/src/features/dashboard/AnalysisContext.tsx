import { CalendarDays, CheckCircle2 } from 'lucide-react';
import { lastDay } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import type { Result } from './types';
import css from './dashboard.module.css';

export function AnalysisContext({ result }: { result: Result }) {
  useLanguage();
  return (
    <div className={css.analysisContext}>
      <CalendarDays size={16} />
      <strong>
        {result.periods.current[0]} — {lastDay(result.periods.current[1])}
      </strong>
      <span>
        {result.timezone} · {result.currency} ·{' '}
        {result.query.skus.length ? `SKU：${result.query.skus.join('、')}` : t('全部商品')}
      </span>
      <span className={css.snapshotReady}>
        <CheckCircle2 size={13} />
        {t('计算已完成')}
      </span>
    </div>
  );
}
