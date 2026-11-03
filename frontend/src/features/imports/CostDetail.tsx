import { t, useLanguage } from '../../lib/i18n';
import type { CostVersionDetail } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = { detail: CostVersionDetail; onClose: () => void };

/** The first rows of a published cost version. */
export function CostDetail({ detail, onClose }: Props) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel, css.costDetail, 'cost-detail')}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{detail.name}</h2>
          <p>{t('不可变成本版本 · 前 20 行 · 金额为主货币单位')}</p>
        </div>
        <button className={cx(css.textButton, ui.textButton, forms.textButton)} onClick={onClose}>
          {t('收起')}
        </button>
      </div>
      <div className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}>
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>{t('单位成本')}</th>
              <th>{t('币种')}</th>
              <th>{t('生效时间')}</th>
              <th>{t('失效时间（不含）')}</th>
            </tr>
          </thead>
          <tbody>
            {detail.preview.map((r, i) => (
              <tr key={i}>
                <td>{r.sku}</td>
                <td>{r.unit_cost}</td>
                <td>{r.currency}</td>
                <td>{r.effective_from}</td>
                <td>{r.effective_to ?? t('持续有效')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
