import { TrendingUp } from 'lucide-react';
import { t, useLanguage } from '../../lib/i18n';
import { money } from './metrics';
import type { Result } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

export function Contributions({ result }: { result: Result }) {
  useLanguage();
  const c = result.contributions;
  const rows = [...c.gainers, ...c.decliners];
  const max = Math.max(1, ...rows.map(r => Math.abs(Number(r.sales_contribution_minor))));
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={cx(css.panelTitle, ui.panelTitle)}>
        <div>
          <h2>{t('销售变化贡献')}</h2>
          <p>
            {t('增减贡献前 5 名 · 合计')}
            {money(c.total_minor, result)}
          </p>
        </div>
        <TrendingUp size={20} />
      </div>
      {!c.available ? (
        <p className={css.chartEmpty}>{t('需要两期完整且净销售可用的数据，才能比较商品贡献。')}</p>
      ) : rows.length ? (
        <div className={css.contributionList}>
          {rows.map(r => (
            <div className={css.contributionRow} key={r.sku ?? 'unmapped'}>
              <div>
                <span>{r.sku ?? t('未映射 SKU')}</span>
                <strong>{money(r.sales_contribution_minor, result)}</strong>
              </div>
              <div className={css.contributionTrack}>
                <span
                  className={Number(r.sales_contribution_minor) < 0 ? css.negative : undefined}
                  style={{
                    width: `${(Math.abs(Number(r.sales_contribution_minor)) / max) * 100}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className={css.chartEmpty}>{t('两期商品净销售额没有变化。')}</p>
      )}
      {c.effects && (
        <div className={css.effects}>
          <span>
            {t('订单量效应')}
            <strong>{money(c.effects.order_effect_minor, result)}</strong>
          </span>
          <span>
            {t('客单价效应')}
            <strong>{money(c.effects.aov_effect_minor, result)}</strong>
          </span>
          <p>{t('描述性金额分解，不代表促销、价格或需求变化的因果结论。')}</p>
        </div>
      )}
    </section>
  );
}
