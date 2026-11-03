import { lastDay } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import { changeText } from './format';
import { labels } from './metrics';
import { MetricValue } from './MetricValue';
import type { Result } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

const extra = [
  'net_cogs',
  'gross_aov',
  'refund_amount_rate',
  'refunded_order_rate',
  'cost_line_coverage',
  'cost_amount_coverage',
];

export function MetricDefinitions({ result }: { result: Result }) {
  useLanguage();
  return (
    <details className={cx(css.panel, ui.panel, css.metricDefinitions)}>
      <summary>{t('更多指标与计算口径')}</summary>
      <div className={cx(css.extraMetrics, 'extra-metrics')}>
        {extra.map(k => (
          <div key={k}>
            <span>{t(labels[k])}</span>
            <strong>
              <MetricValue metric={result.current.metrics[k]} result={result} />
            </strong>
            <small>{changeText(result.comparison?.[k])}</small>
          </div>
        ))}
      </div>
      <p>
        {t('退款为截至')}
        {result.source_as_of}{' '}
        {t('的累计值，归属原支付周期，并非期间现金退款；近期订单的退款观察时间可能更短。')}
      </p>
      <p>
        {t(
          '商品毛利按上传金额口径计算，未扣平台佣金、运费、广告、人工和税费。成本逐行 ROUND_HALF_UP 后汇总；未知回库按不回转成本估算。',
        )}
      </p>
      <p>
        {t('源版本排除')}
        {result.excluded_rows} {t('行（全文件范围）。本期')}
        {result.current.row_count} {t('条明细，')}
        {result.current.coverage_complete ? t('完整覆盖') : t('覆盖不完整')}
        {t('。数据版本')}
        {result.dataset_id} {t('· 指标引擎')}
        {result.engine_version}。
      </p>
      {result.periods.previous && (
        <p>
          {t('比较范围：')}
          {result.periods.previous[0]} {t('至')}
          {lastDay(result.periods.previous[1])}，
          {result.previous?.coverage_complete ? t('完整覆盖') : t('覆盖不完整')}
          {t('。自定义比较可不等长，请结合天数解释差异。')}
        </p>
      )}
    </details>
  );
}
