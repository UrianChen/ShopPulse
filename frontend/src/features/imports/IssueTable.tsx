import { t, useLanguage, message } from '../../lib/i18n';
import type { Paged } from '../../lib/types';
import type { Issue } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

const PAGE = 100;

type Props = { issues: Paged<Issue> | undefined; offset: number; onOffset: (next: number) => void };

/** Validation issues, one page of 100 at a time. */
export function IssueTable({ issues, offset, onOffset }: Props) {
  useLanguage();
  return (
    <>
      {!!issues?.items.length && (
        <div className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}>
          <table>
            <thead>
              <tr>
                <th>{t('行号')}</th>
                <th>{t('等级')}</th>
                <th>{t('规则')}</th>
                <th>{t('处理建议')}</th>
              </tr>
            </thead>
            <tbody>
              {issues.items.map((i, n) => (
                <tr key={`${i.code}-${i.row_number}-${n}`}>
                  <td>{i.row_number || t('配置')}</td>
                  <td>
                    <span className={i.severity === 'error' ? css.issueError : css.issueWarning}>
                      {i.severity === 'error'
                        ? t('阻断')
                        : i.acknowledged
                          ? t('已确认')
                          : t('警告')}
                    </span>
                  </td>
                  <td>
                    <code>{i.code}</code>
                  </td>
                  <td>{message(i.message)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {issues && issues.total > PAGE && (
        <div className={cx(ui.pagination, forms.pagination)}>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={offset === 0}
            onClick={() => onOffset(offset - PAGE)}
          >
            {t('上一页')}
          </button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE, issues.total)} / {issues.total}
          </span>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={offset + PAGE >= issues.total}
            onClick={() => onOffset(offset + PAGE)}
          >
            {t('下一页')}
          </button>
        </div>
      )}
    </>
  );
}
