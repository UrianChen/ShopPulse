import { t, useLanguage } from '../../lib/i18n';
import { labels, money } from './metrics';
import { MetricValue } from './MetricValue';
import type { Result } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

/** Profit figures restricted to rows with a matched cost, shown when some costs are missing. */
export function MatchedSubset({ result }: { result: Result }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel, css.matchedSubset)}>
      <div>
        <h2>{t('已匹配成本商品 · 单独核算')}</h2>
        <p>
          {t('缺失')}
          {result.current.quality.missing_cost_rows} {t('行 /')}
          {result.current.quality.missing_cost_skus} {t('个 SKU，涉及实付')}
          {money(result.current.quality.missing_cost_paid_minor, result)}
          {t('。已匹配')}
          {result.matched_cost_subset.row_count} {t('条明细，以下三项严格使用该子集。')}
        </p>
      </div>
      <div>
        {['net_sales', 'net_cogs', 'gross_profit'].map(k => (
          <span key={k}>
            {t(labels[k])}
            <strong data-testid={`subset-${k}`}>
              <MetricValue metric={result.matched_cost_subset.metrics[k]} result={result} />
            </strong>
          </span>
        ))}
      </div>
    </section>
  );
}
