import { t, useLanguage } from '../../lib/i18n';
import { FileSpreadsheet } from 'lucide-react';
import { ImportState } from './ImportState';
import type { Draft } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = { imports: Draft[] | undefined; pending: boolean; onOpen: (id: string) => void };

export function ImportList({ imports, pending, onOpen }: Props) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{t('导入记录')}</h2>
          <p>{t('最近 100 次导入')}</p>
        </div>
        <FileSpreadsheet size={20} />
      </div>
      <div className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}>
        <table>
          <thead>
            <tr>
              <th>{t('名称')}</th>
              <th>{t('数据类型')}</th>
              <th>{t('状态')}</th>
              <th>{t('行数')}</th>
              <th>{t('操作')}</th>
            </tr>
          </thead>
          <tbody>
            {imports?.map(item => (
              <tr key={item.id}>
                <td>{item.name}</td>
                <td>{item.kind === 'orders' ? t('订单明细') : t('商品成本')}</td>
                <td>
                  <ImportState value={item.status} />
                </td>
                <td>{item.summary?.included_rows ?? '—'}</td>
                <td>
                  <button
                    className={cx(css.textButton, ui.textButton, forms.textButton)}
                    onClick={() => onOpen(item.id)}
                  >
                    {item.status === 'published' ? t('查看记录') : t('继续处理')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!pending && !imports?.length && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('暂无导入记录')}</p>
      )}
    </section>
  );
}
