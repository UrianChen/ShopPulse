import { t, useLanguage } from '../../lib/i18n';
import { Contributions, Trend } from '../dashboard/Dashboard';
import { changeText, formatMetric } from '../dashboard/format';
import { Sentences } from './Advice';
import { qualityNames, ruleNames } from './labels';
import type { Content, OnEvidence } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

/** Summary, metric cards, charts and the product table of a report. */
export function Overview({ content: c, onEvidence }: { content: Content; onEvidence: OnEvidence }) {
  useLanguage();
  const money = { currency: c.metrics.currency, exponent: c.metrics.currency_exponent };
  return (
    <>
      <section className={cx(css.panel, ui.panel, 'report-overview')}>
        <div className={cx(css.panelTitle, ui.panelTitle)}>
          <div>
            <h2>{t('经营概览')}</h2>
          </div>
        </div>
        <Sentences values={c.summary} onEvidence={onEvidence} />
      </section>
      <section className={css.reportMetrics}>
        {c.metric_cards.slice(0, 6).map(card => (
          <div
            className={cx(css.panel, ui.panel)}
            key={card.key}
            data-testid={`report-metric-${card.key}`}
          >
            <span>{t(card.label)}</span>
            <strong>{formatMetric(card.metric, money.currency, money.exponent)}</strong>
            <small>
              {card.metric.quality === 'estimated' ? t('估算 · ') : ''}
              {card.metric.value === null
                ? t('数据不足或分母为零')
                : changeText(c.metrics.comparison?.[card.key])}
            </small>
            <button className={css.evidenceLink} onClick={() => onEvidence(card.evidence_id)}>
              {t('计算依据')}
            </button>
          </div>
        ))}
      </section>
      <div className={css.reportCharts}>
        <Trend result={c.metrics} />
        <Contributions result={c.metrics} />
      </div>
      <section className={cx(css.panel, ui.panel)}>
        <h2>{t('商品表现')}</h2>
        <p className={cx(ui.formHint, forms.formHint)}>{t('净销售额前 10 名')}</p>
        <div className={cx(ui.tableScroll, forms.tableScroll)}>
          <table>
            <thead>
              <tr>
                <th>{t('SKU / 商品')}</th>
                <th>{t('净销售额')}</th>
                <th>{t('商品毛利')}</th>
                <th>{t('支付件数')}</th>
              </tr>
            </thead>
            <tbody>
              {c.products.map((p, i) => (
                <tr key={i}>
                  <td>
                    {p.sku ?? t('未映射 SKU')}
                    <small className={css.reportProductName}>{p.product_name}</small>
                  </td>
                  {['net_sales', 'gross_profit', 'paid_units'].map(k => (
                    <td key={k}>
                      {formatMetric(p.current.metrics[k], money.currency, money.exponent)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

const CHECK_STATES: Record<string, string> = {
  clear: '未触发',
  triggered: '已触发',
  insufficient_data: '样本或数据不足',
  insufficient_baseline: '历史基线不足',
};

export function Anomalies({ content: c }: { content: Content }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('异常与数据限制')}</h2>
      {c.anomalies.findings.length ? (
        c.anomalies.findings.map((f, i) => (
          <div className={css.reportFinding} key={i}>
            <h3>{t(ruleNames[f.code])}</h3>
            <p>{f.limitation}</p>
            <details>
              <summary>{t('查看阈值、实际值与样本')}</summary>
              <pre>{JSON.stringify(f.values, null, 2)}</pre>
            </details>
          </div>
        ))
      ) : (
        <p className={cx(ui.formHint, forms.formHint)}>
          {t('未触发异常规则；请同时关注数据限制。')}
        </p>
      )}
      <div className={css.ruleChecks}>
        {c.anomalies.checks.map(check => (
          <p key={check.code}>
            <strong>{t(ruleNames[check.code])}</strong>
            <span>{t(CHECK_STATES[check.state])}</span>
          </p>
        ))}
      </div>
      {c.warnings.length > 0 && (
        <p className={cx(ui.reportWarning, 'report-warning')}>
          {t('数据质量标记：')}
          {c.warnings.map(code => t(qualityNames[code] ?? code)).join('；')}
          {t('。请结合证据中的质量结果解释指标。')}
        </p>
      )}
      <ul className={css.reportLimitations}>
        {c.limitations.map(l => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </section>
  );
}
