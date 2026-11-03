import { useState } from 'react';
import { lastDay } from '../../lib/dates';
import { locale, t, useLanguage } from '../../lib/i18n';
import { labels, metricText } from './metrics';
import { MetricValue } from './MetricValue';
import type { Result } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

export function Trend({ result }: { result: Result }) {
  useLanguage();
  const [hover, setHover] = useState<number | null>(null);
  const [series, setSeries] = useState('net_sales');
  const points = result.trend;
  const nums = points.map(p =>
    p.metrics[series].value === null ? null : Number(p.metrics[series].value),
  );
  const values = nums.filter((n): n is number => n !== null);
  const min = Math.min(0, ...values),
    max = Math.max(1, ...values),
    range = max - min;
  const x = (i: number) => 65 + (i * 640) / Math.max(1, points.length - 1);
  const y = (n: number) => 215 - ((n - min) / range) * 165;
  let path = '',
    connected = false;
  nums.forEach((n, i) => {
    if (n === null) connected = false;
    else {
      path += `${connected ? 'L' : 'M'} ${x(i)} ${y(n)} `;
      connected = true;
    }
  });
  const selected = points[hover ?? points.length - 1];
  return (
    <section className={cx(css.panel, ui.panel, css.trendPanel)}>
      <div className={cx(css.panelTitle, ui.panelTitle)}>
        <div>
          <h2>{t('经营趋势')}</h2>
          <p>
            {result.query.granularity === 'day'
              ? t('按店铺自然日')
              : t('按周一至周日，边缘周按筛选范围')}{' '}
            {t('· 空缺数据不补零')}
          </p>
        </div>
        <select aria-label={t('趋势指标')} value={series} onChange={e => setSeries(e.target.value)}>
          {['net_sales', 'gross_sales', 'gross_profit', 'paid_orders'].map(k => (
            <option value={k} key={k}>
              {t(labels[k])}
            </option>
          ))}
        </select>
      </div>
      <figure className={css.trendFigure}>
        <svg viewBox="0 0 740 265" role="img" aria-label={t('{0}趋势图', t(labels[series]))}>
          {[0, 0.5, 1].map(f => {
            const n = min + range * f;
            return (
              <g key={f}>
                <line x1="65" x2="705" y1={y(n)} y2={y(n)} stroke="#e8eee8" strokeDasharray="4 4" />
                <text x="55" y={y(n) + 4} textAnchor="end" className={css.axisLabel}>
                  {new Intl.NumberFormat(locale(), {
                    notation: 'compact',
                    maximumFractionDigits: 1,
                  }).format(n / (series === 'paid_orders' ? 1 : 10 ** result.currency_exponent))}
                </text>
              </g>
            );
          })}
          <path d={path} stroke="#426c4e" strokeWidth="2.5" fill="none" />
          {nums.map((n, i) =>
            n === null ? null : (
              <circle
                key={points[i].start}
                cx={x(i)}
                cy={y(n)}
                r={hover === i ? 5 : 3}
                fill="#648d54"
                tabIndex={0}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                aria-label={`${points[i].start} ${t(labels[series])} ${metricText(points[i].metrics[series], result)}`}
              >
                <title>
                  {points[i].start}：{metricText(points[i].metrics[series], result)}
                </title>
              </circle>
            ),
          )}
          <text x="65" y="247" className={css.axisLabel}>
            {points[0]?.start}
          </text>
          <text x="705" y="247" textAnchor="end" className={css.axisLabel}>
            {points.at(-1)?.start}
          </text>
        </svg>
        <figcaption>
          {selected && (
            <>
              <span>
                {selected.start}
                {result.query.granularity === 'week'
                  ? t(' 至 {0}', lastDay(selected.end_exclusive))
                  : ''}
              </span>
              <strong>
                {t(labels[series])}{' '}
                <MetricValue metric={selected.metrics[series]} result={result} />
              </strong>
              <span>{selected.coverage_complete ? t('完整覆盖') : t('覆盖不完整')}</span>
            </>
          )}
        </figcaption>
      </figure>
    </section>
  );
}
