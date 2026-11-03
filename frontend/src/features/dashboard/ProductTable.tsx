import { t, useLanguage } from '../../lib/i18n';
import { labels, metricText, money } from './metrics';
import { MetricValue } from './MetricValue';
import type { ProductOrder, ProductPage, Result } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

export const PAGE_SIZE = 20;

type Props = {
  result: Result;
  page: ProductPage | undefined;
  loading: boolean;
  order: ProductOrder;
  offset: number;
  onOrder: (order: ProductOrder) => void;
  onOffset: (offset: number) => void;
  onSku: (sku: string) => void;
};

export function ProductTable({
  result,
  page,
  loading,
  order,
  offset,
  onOrder,
  onOffset,
  onSku,
}: Props) {
  useLanguage();
  const change = (next: Partial<ProductOrder>) => {
    onOrder({ ...order, ...next });
    onOffset(0);
  };
  return (
    <section className={cx(css.panel, ui.panel, css.productPanel, 'product-panel')}>
      <div className={cx(css.panelTitle, ui.panelTitle)}>
        <div>
          <h2>{t('商品表现')}</h2>
          <p>{t('点击 SKU 筛选；各商品订单量不可相加。')}</p>
        </div>
        <span>
          {page?.total ?? '—'} {t('个商品分组')}
        </span>
      </div>
      <div className={css.productControls}>
        <label>
          {t('排序')}
          <select
            aria-label={t('商品排序')}
            value={order.sort}
            onChange={e => change({ sort: e.target.value })}
          >
            {['net_sales', 'gross_profit', 'refund_amount', 'paid_units'].map(k => (
              <option value={k} key={k}>
                {t(labels[k])}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('方向')}
          <select
            aria-label={t('排序方向')}
            value={order.direction}
            onChange={e => change({ direction: e.target.value })}
          >
            <option value="desc">{t('从高到低')}</option>
            <option value="asc">{t('从低到高')}</option>
          </select>
        </label>
        <label>
          {t('查看')}
          <select
            aria-label={t('商品条件')}
            value={order.focus}
            onChange={e => change({ focus: e.target.value })}
          >
            <option value="all">{t('全部')}</option>
            <option value="negative_profit">{t('负毛利')}</option>
            <option value="refunded">{t('发生退款')}</option>
          </select>
        </label>
      </div>
      <div className={ui.tableScroll}>
        <table>
          <thead>
            <tr>
              <th>{t('商品 / SKU')}</th>
              <th>{t('净销售额')}</th>
              <th>{t('支付件数 / 订单')}</th>
              <th>{t('累计退款')}</th>
              <th>{t('商品毛利')}</th>
              <th>{t('销售变动贡献')}</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((p, i) => (
              <tr key={p.sku ?? `unmapped-${i}`}>
                <td>
                  <strong>{p.product_name}</strong>
                  {p.sku ? (
                    <button
                      className={cx(ui.textButton, css.skuFilterLink)}
                      onClick={() => onSku(p.sku!)}
                    >
                      {p.sku}
                    </button>
                  ) : (
                    <small>{t('未映射 SKU')}</small>
                  )}
                </td>
                <td>
                  <MetricValue metric={p.current.metrics.net_sales} result={result} />
                </td>
                <td>
                  {metricText(p.current.metrics.paid_units, result)} /{' '}
                  {metricText(p.current.metrics.paid_orders, result)}
                </td>
                <td>
                  <MetricValue metric={p.current.metrics.refund_amount} result={result} />
                </td>
                <td>
                  <MetricValue metric={p.current.metrics.gross_profit} result={result} />
                </td>
                <td>{money(p.sales_contribution_minor, result)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loading ? (
        <p className={ui.emptyCopy}>{t('正在读取商品结果…')}</p>
      ) : page?.total === 0 ? (
        <p className={ui.emptyCopy}>{t('当前范围或商品条件下没有记录。')}</p>
      ) : null}
      {page && page.total > PAGE_SIZE && (
        <div className={ui.pagination}>
          <button
            className={cx(css.secondary, ui.secondary)}
            disabled={offset === 0}
            onClick={() => onOffset(offset - PAGE_SIZE)}
          >
            {t('上一页')}
          </button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} / {page.total}
          </span>
          <button
            className={cx(css.secondary, ui.secondary)}
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => onOffset(offset + PAGE_SIZE)}
          >
            {t('下一页')}
          </button>
        </div>
      )}
    </section>
  );
}
