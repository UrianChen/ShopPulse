import { lastDay } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import type { Result } from '../dashboard/Dashboard';
import { formatMetric } from '../dashboard/format';
import { directions, hypothesisReasons, hypothesisStates, metricNames } from './labels';
import type { Content, History, HistoryWindow, OnEvidence, Recheck } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

export function StateBadge({ state }: { state: string }) {
  useLanguage();
  return <b className={css[`hypothesis-state-${state}`]}>{t(hypothesisStates[state] ?? state)}</b>;
}

export function Hypotheses({
  content: c,
  onEvidence,
}: {
  content: Content;
  onEvidence: OnEvidence;
}) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('假设检验')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('每条假设都由服务端运行检验并判定；数据支持只表示数据与假设一致，不证明因果。')}
      </p>
      <ul className={cx(css.hypothesisList, 'hypothesis-list')}>
        {(c.hypotheses ?? []).map(h => (
          <li key={h.id}>
            <StateBadge state={h.state} />
            <span>{h.statement ?? h.id}</span>
            <small>
              {h.wave === 0 ? t('服务端提出') : t('模型提出 · 第 {0} 轮', h.wave)}
              {h.quality === 'estimated' ? ` · ${t('基于估算值')}` : ''}
              {h.reason ? ` · ${t(hypothesisReasons[h.reason] ?? h.reason)}` : ''}
            </small>
            <button className={css.evidenceLink} onClick={() => onEvidence(h.evidence_id)}>
              {t('查看检验')}
            </button>
          </li>
        ))}
      </ul>
      {!!c.ruled_out?.length && (
        <>
          <h3>{t('已排除的原因')}</h3>
          <ul className={cx(css.hypothesisList, 'hypothesis-list')}>
            {c.ruled_out.map(r => (
              <li key={r.hypothesis_id}>
                <StateBadge state="refuted" />
                <span>
                  {r.statement ?? r.hypothesis_id}
                  <small className={css.reportProductName}>{r.text}</small>
                </span>
                <span />
                {r.evidence_refs.slice(0, 2).map((id, n) => (
                  <button className={css.evidenceLink} key={id} onClick={() => onEvidence(id)}>
                    {t('证据 {0}', n + 1)}
                  </button>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function Rechecks({ items, onEvidence }: { items: Recheck[]; onEvidence: OnEvidence }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('上期结论复核')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('用相同的检验条件在本期数据上重新判定上一份报告的假设。')}
      </p>
      <div className={cx(ui.tableScroll, forms.tableScroll)}>
        <table className={css.followupTable}>
          <thead>
            <tr>
              <th>{t('上期假设')}</th>
              <th>{t('上期结论')}</th>
              <th>{t('本期结论')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map(h => (
              <tr key={h.id}>
                <td>{h.statement ?? h.id}</td>
                <td>{t(hypothesisStates[h.previous_state] ?? h.previous_state)}</td>
                <td>
                  <StateBadge state={h.state} />
                  {h.reason && (
                    <small className={css.reportProductName}>
                      {t(hypothesisReasons[h.reason] ?? h.reason)}
                    </small>
                  )}
                  <button className={css.evidenceLink} onClick={() => onEvidence(h.evidence_id)}>
                    {t('查看检验')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const HISTORY_KEYS = ['net_sales', 'paid_orders', 'aov', 'refund_amount_rate'];

/** Earlier windows, newest first; windows without full coverage show a dash. */
export function HistoryTable({ windows, result }: { windows: HistoryWindow[]; result: Result }) {
  useLanguage();
  return (
    <div className={cx(ui.tableScroll, forms.tableScroll)}>
      <table>
        <thead>
          <tr>
            <th>{t('窗口')}</th>
            {HISTORY_KEYS.map(k => (
              <th key={k}>{t(metricNames[k] ?? k)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {windows.map(w => (
            <tr key={w.start}>
              <td>
                {w.start} {t('至')}
                {lastDay(w.end_exclusive)}
              </td>
              {HISTORY_KEYS.map(k => (
                <td key={k}>
                  {w.coverage_complete
                    ? formatMetric(w.metrics[k], result.currency, result.currency_exponent)
                    : '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryPanel({
  history,
  result,
  onEvidence,
}: {
  history: History;
  result: Result;
  onEvidence: OnEvidence;
}) {
  useLanguage();
  const streak = history.streaks.net_sales;
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={cx(css.panelTitle, ui.panelTitle)}>
        <div>
          <h2>{t('历史窗口')}</h2>
          <p>
            {t(
              '本期之前每 {0} 天一个窗口，最近的在前；覆盖不完整的窗口不计算。',
              history.window_days,
            )}
          </p>
        </div>
        <button className={css.evidenceLink} onClick={() => onEvidence(history.evidence_id)}>
          {t('计算依据')}
        </button>
      </div>
      {streak && streak.direction !== 'flat' && streak.periods >= 2 && (
        <p className={cx(ui.reportWarning, 'report-warning')}>
          {t('净销售额已连续 {0} 期{1}。', streak.periods, t(directions[streak.direction]))}
        </p>
      )}
      <HistoryTable windows={history.windows} result={result} />
    </section>
  );
}
