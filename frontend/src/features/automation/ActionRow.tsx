import { t, useLanguage } from '../../lib/i18n';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { ErrorNotice } from '../../components/ErrorNotice';
import { followupStates, metricNames, priorityNames, statusNames } from './constants';
import type { ActionItem } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './automation.module.css';

export function ActionRow({
  item,
  onChanged,
  showReport = false,
}: {
  item: ActionItem;
  onChanged: () => void;
  showReport?: boolean;
}) {
  useLanguage();
  const [note, setNote] = useState(item.note ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function save(patch: { status?: string; note?: string }) {
    setPending(true);
    setError(null);
    try {
      await api(`/actions/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ revision: item.revision, ...patch }),
      });
      onChanged();
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className={cx(css.actionRow, item.status === 'dismissed' && css.statusDismissed)}>
      <div className={css.actionMain}>
        <span className={ui.subtleBadge}>{t(priorityNames[item.priority] ?? item.priority)}</span>
        <p>{item.text}</p>
        <small>
          {t('验证指标：')}
          {t(metricNames[item.verification_metric] ?? item.verification_metric)}
          {item.evaluation && (
            <>
              {' '}
              · {t('最近评估：')}
              <b className={ui[`followup-${item.evaluation.state}`]}>
                {t(followupStates[item.evaluation.state])}
              </b>
            </>
          )}
          {showReport && item.report_title && (
            <>
              {' '}
              · <Link to={`/reports/${item.report_id}`}>{item.report_title}</Link>
            </>
          )}
        </small>
      </div>
      <div className={css.actionControls}>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('状态')}
          <select
            value={item.status}
            disabled={pending}
            onChange={e => void save({ status: e.target.value })}
          >
            {Object.entries(statusNames).map(([key, label]) => (
              <option key={key} value={key}>
                {t(label)}
              </option>
            ))}
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('备注')}
          <input
            maxLength={500}
            value={note}
            disabled={pending}
            onChange={e => setNote(e.target.value)}
            placeholder={t('记录处理情况')}
          />
        </label>
        <button
          type="button"
          className={cx(ui.secondary, forms.secondary)}
          disabled={pending || note === (item.note ?? '')}
          onClick={() => void save({ note })}
        >
          {t('保存备注')}
        </button>
      </div>
      <ErrorNotice error={error} />
    </div>
  );
}
