import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { lastDay } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import { ActionRow, followupStates, noteKinds } from '../automation/Automation';
import type { ActionItem } from '../automation/Automation';
import type { Result } from '../dashboard/Dashboard';
import { formatMetric } from '../dashboard/format';
import { followupReasons, metricNames, signedPercent } from './labels';
import type { Followup, MerchantNote } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

/** Earlier recommendations measured with their verification metric. */
export function ActionFollowups({ items, result }: { items: Followup[]; result: Result }) {
  useLanguage();
  const money = (metric: Followup['baseline']) =>
    metric ? formatMetric(metric, result.currency, result.currency_exponent) : '—';
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('上期建议跟进')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('用每条建议的验证指标，对比提出建议的报告与本期的数值。改善不代表因果。')}
      </p>
      <div className={cx(ui.tableScroll, forms.tableScroll)}>
        <table className={css.followupTable}>
          <thead>
            <tr>
              <th>{t('建议')}</th>
              <th>{t('验证指标')}</th>
              <th>{t('提出时')}</th>
              <th>{t('本期')}</th>
              <th>{t('变化')}</th>
              <th>{t('结论')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map(f => (
              <tr key={f.action_id}>
                <td>
                  {f.action_text}
                  <small className={css.reportProductName}>
                    {f.source_period[0]} {t('至')}
                    {lastDay(f.source_period[1])}
                  </small>
                </td>
                <td>{t(metricNames[f.verification_metric] ?? f.verification_metric)}</td>
                <td>{money(f.baseline)}</td>
                <td>{money(f.current)}</td>
                <td>{f.change_rate ? signedPercent(f.change_rate) : '—'}</td>
                <td>
                  <b className={ui[`followup-${f.state}`]}>{t(followupStates[f.state])}</b>
                  {f.reason && (
                    <small className={css.reportProductName}>
                      {t(followupReasons[f.reason] ?? f.reason)}
                    </small>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function MerchantNotes({ items }: { items: MerchantNote[] }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('商家备注')}</h2>
      <ul className={ui.noteList}>
        {items.map(n => (
          <li key={n.id}>
            <span className={cx(css.subtleBadge, ui.subtleBadge)}>
              {t(noteKinds[n.kind] ?? n.kind)}
            </span>
            <span>
              {n.start} {t('至')} {lastDay(n.end_exclusive)}
            </span>
            <span>{n.text}</span>
            <span />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ReportActions({ reportId }: { reportId: string }) {
  useLanguage();
  const client = useQueryClient();
  const actions = useQuery({
    queryKey: keys.reportActions(reportId),
    queryFn: () => api<ActionItem[]>(`/reports/${reportId}/actions`),
  });
  if (!actions.data?.length) return null;
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('行动项')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('标记处理状态；之后的报告会按验证指标检查效果。全部行动项见')}
        <Link to="/automation">{t('自动化')}</Link>
        {t('。')}
      </p>
      <ErrorNotice error={actions.error} />
      <div className={ui.actionList}>
        {actions.data.map(item => (
          <ActionRow
            key={`${item.id}-${item.revision}`}
            item={item}
            onChanged={() =>
              void client.invalidateQueries({ queryKey: keys.reportActions(reportId) })
            }
          />
        ))}
      </div>
    </section>
  );
}
