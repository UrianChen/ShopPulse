import { t, useLanguage } from '../../lib/i18n';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardCheck } from 'lucide-react';
import { api } from '../../lib/api';
import { keys } from '../../lib/queries';
import type { Paged } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { ActionRow } from './ActionRow';
import { allActions } from './constants';
import type { ActionItem } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './automation.module.css';

export function Actions() {
  useLanguage();
  const client = useQueryClient();
  const [status, setStatus] = useState('open');
  const actions = useQuery({
    queryKey: keys.actions(status),
    queryFn: () => api<Paged<ActionItem>>(`/actions?status=${status}&limit=50`),
  });
  return (
    <section className={css.automationSection}>
      <div className={ui.panelTitle}>
        <div>
          <h2>
            <ClipboardCheck size={19} />
            {t('建议跟进')}
          </h2>
          <p className={cx(ui.formHint, forms.formHint)}>
            {t('报告中的建议会成为行动项；之后的报告会用验证指标检查是否改善。')}
          </p>
        </div>
        <label className={cx(css.field, ui.field, forms.field, css.compact)}>
          {t('状态')}
          <select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="open">{t('待处理')}</option>
            <option value="done">{t('已完成')}</option>
            <option value="dismissed">{t('已忽略')}</option>
            <option value="all">{t('全部')}</option>
          </select>
        </label>
      </div>
      <ErrorNotice error={actions.error} />
      {actions.data?.items.length === 0 && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('没有符合条件的行动项。')}</p>
      )}
      {!!actions.data?.items.length && (
        <div className={cx(ui.panel, ui.actionList)}>
          {actions.data.items.map(item => (
            <ActionRow
              key={`${item.id}-${item.revision}`}
              item={item}
              showReport
              onChanged={() => void client.invalidateQueries({ queryKey: allActions })}
            />
          ))}
        </div>
      )}
    </section>
  );
}
