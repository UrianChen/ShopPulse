import { t, useLanguage } from '../../lib/i18n';
import type { OrderVersionDetail } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = { detail: OrderVersionDetail; onClose: () => void };

/** Frozen snapshot facts and the normalized order lines of a published dataset. */
export function DatasetDetail({ detail, onClose }: Props) {
  useLanguage();
  const { options } = detail.snapshot.config;
  return (
    <section className={cx(css.panel, ui.panel, css.datasetDetail, 'dataset-detail')}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{detail.name}</h2>
          <p>{t('标准化明细预览 · 金额以最小货币单位显示（CNY 为分）')}</p>
        </div>
        <button className={cx(css.textButton, ui.textButton, forms.textButton)} onClick={onClose}>
          {t('收起')}
        </button>
      </div>
      <div className={css.snapshotInfo}>
        <span>
          {t('覆盖：')}
          {options.coverage_start} {t('至')}
          {options.coverage_end_exclusive}
          {t('（不含）')}
        </span>
        <span>
          {t('数据截止：')}
          {options.source_as_of}
        </span>
        <span>
          {t('引擎：')}
          {detail.snapshot.engine_version} {t('· 文件 SHA-256：')}
          {detail.snapshot.file_sha256}
        </span>
      </div>
      <div className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}>
        <table>
          <thead>
            <tr>
              <th>{t('源行号')}</th>
              <th>{t('订单')}</th>
              <th>SKU</th>
              <th>{t('数量')}</th>
              <th>{t('实付（最小单位）')}</th>
              <th>{t('退款（最小单位）')}</th>
              <th>{t('单位成本（主单位）')}</th>
            </tr>
          </thead>
          <tbody>
            {detail.preview.map(r => (
              <tr key={r.source_row_number}>
                <td>{r.source_row_number}</td>
                <td>{r.order_id}</td>
                <td>{r.sku ?? t('未匹配')}</td>
                <td>{r.quantity}</td>
                <td>{r.line_paid_minor}</td>
                <td>{r.line_refund_minor ?? t('未知')}</td>
                <td>{r.unit_cost ?? t('缺失')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
