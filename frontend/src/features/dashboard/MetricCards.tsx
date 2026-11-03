import { Activity } from 'lucide-react';
import { t, useLanguage } from '../../lib/i18n';
import { changeText } from './format';
import { labels, metricText } from './metrics';
import { MetricValue } from './MetricValue';
import type { Result } from './types';
import { cx } from '../../lib/cx';
import css from './dashboard.module.css';

const cards = [
  'net_sales',
  'paid_orders',
  'aov',
  'gross_profit',
  'gross_sales',
  'refund_amount',
  'gross_margin',
  'paid_units',
];

export function MetricCards({ result }: { result: Result }) {
  useLanguage();
  return (
    <section className={css.metricGrid}>
      {cards.map(k => (
        <article
          className={cx(css.metricCard, k === 'net_sales' && css.featured)}
          key={k}
          data-testid={`metric-${k}`}
        >
          <div className={css.metricLabel}>
            {t(labels[k])}
            <Activity size={14} />
          </div>
          <strong className={cx(css.metricValue, 'metric-value')}>
            <MetricValue metric={result.current.metrics[k]} result={result} />
          </strong>
          <div className={css.metricChange}>
            {changeText(result.comparison?.[k])}
            {result.comparison?.[k]?.quality === 'estimated' ? t(' · 估算') : ''}
          </div>
          <small className={css.metricBaseline}>
            {result.previous
              ? t('比较期 {0}', metricText(result.previous.metrics[k], result))
              : t('本期筛选范围')}
          </small>
        </article>
      ))}
    </section>
  );
}
