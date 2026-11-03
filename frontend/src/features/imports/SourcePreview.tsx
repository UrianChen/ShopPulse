import { t, useLanguage } from '../../lib/i18n';
import type { Preview } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

export function SourcePreview({ data }: { data?: Preview | null }) {
  useLanguage();
  if (!data) return null;
  return (
    <details className={cx(css.sourcePreview, 'source-preview')}>
      <summary>
        {t('查看源表预览 ·')}
        {data.row_count} {t('行 · 最多显示前 10 行')}
      </summary>
      <div className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}>
        <table>
          <thead>
            <tr>
              <th>{t('行号')}</th>
              {data.columns.map(c => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.preview.map(row => (
              <tr key={row.row_number}>
                <td>{row.row_number}</td>
                {data.columns.map(c => (
                  <td key={c}>{row.values[c]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('未识别的列在预览中隐藏。原文件仅保存在你的后端，不会发送给模型。')}
      </p>
    </details>
  );
}
