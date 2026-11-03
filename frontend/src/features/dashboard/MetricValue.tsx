import { t, useLanguage } from '../../lib/i18n';
import { reasons } from './format';
import type { Metric } from './format';
import { metricText } from './metrics';
import type { Result } from './types';
import css from './dashboard.module.css';

export function MetricValue({ metric, result }: { metric: Metric; result: Result }) {
  useLanguage();
  return (
    <>
      <span>{metricText(metric, result)}</span>
      {metric.quality === 'estimated' && <small className={css.estimate}>{t('估算')}</small>}
      {metric.value === null && (
        <small className={css.unavailableReason}>
          {t(reasons[metric.unavailable_reason ?? ''] ?? '不可用')}
        </small>
      )}
    </>
  );
}
