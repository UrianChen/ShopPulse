import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { locale, t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { AuditEntry } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';

const PAGE_SIZE = 50;

export function AuditLog() {
  useLanguage();
  const [offset, setOffset] = useState(0);
  const audit = useQuery({
    queryKey: [...keys.operationsAudit, offset],
    queryFn: () => api<AuditEntry[]>(`/operations/audit?offset=${offset}`),
  });
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('操作审计')}</h2>
      <button className={cx(ui.textButton, forms.textButton)} onClick={() => void audit.refetch()}>
        {t('刷新记录')}
      </button>
      {/* Keyboard users can scroll the wide table. */}
      <div
        className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}
        role="region"
        aria-label={t('操作审计')}
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th>{t('时间')}</th>
              <th>{t('操作')}</th>
              <th>{t('对象')}</th>
              <th>{t('元数据')}</th>
            </tr>
          </thead>
          <tbody>
            {audit.data?.map(a => (
              <tr key={a.id}>
                <td>{new Date(a.created_at).toLocaleString(locale())}</td>
                <td>{a.action}</td>
                <td className={css.mono} title={a.target_id}>
                  {a.target_id?.slice(0, 8)}
                </td>
                <td>
                  <details>
                    <summary>{t('详情')}</summary>
                    <pre>{JSON.stringify(a.details, null, 2)}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={cx(ui.pagination, forms.pagination)}>
        <button
          className={cx(ui.secondary, forms.secondary)}
          disabled={!offset}
          onClick={() => setOffset(offset - PAGE_SIZE)}
        >
          {t('上一页')}
        </button>
        <button
          className={cx(ui.secondary, forms.secondary)}
          disabled={(audit.data?.length ?? 0) < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          {t('下一页')}
        </button>
      </div>
    </section>
  );
}
