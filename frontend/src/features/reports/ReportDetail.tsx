import { useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, BookOpen, LoaderCircle, ShieldCheck } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { lastDay } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import { keys, POLL, pollWhile } from '../../lib/queries';
import { Advice } from './Advice';
import { EvidenceDrawer } from './EvidenceDrawer';
import { Exports } from './Exports';
import { ActionFollowups, MerchantNotes, ReportActions } from './Followups';
import { HistoryPanel, Hypotheses, Rechecks } from './Hypotheses';
import { DONE, limitedConsent, modes, states, toolNames } from './labels';
import { Anomalies, Overview } from './Overview';
import { Questions } from './Questions';
import { RunLog } from './RunLog';
import type { Content, OnEvidence, Report, Run } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

function Body({
  report: r,
  content: c,
  onEvidence,
}: {
  report: Report;
  content: Content;
  onEvidence: OnEvidence;
}) {
  useLanguage();
  const finished = DONE.includes(r.status);
  return (
    <>
      <Overview content={c} onEvidence={onEvidence} />
      <Anomalies content={c} />
      <section className={cx(css.panel, ui.panel)}>
        <h2>{t('经营观察与行动建议')}</h2>
        <p className={cx(ui.formHint, forms.formHint)}>{t('原因是待验证假设，建议需人工判断。')}</p>
        <Advice findings={c.findings} recommendations={c.recommendations} onEvidence={onEvidence} />
      </section>
      {(!!c.hypotheses?.length || !!c.ruled_out?.length) && (
        <Hypotheses content={c} onEvidence={onEvidence} />
      )}
      {!!c.hypothesis_recheck?.length && (
        <Rechecks items={c.hypothesis_recheck} onEvidence={onEvidence} />
      )}
      {c.history && c.history.windows.length > 0 && (
        <HistoryPanel history={c.history} result={c.metrics} onEvidence={onEvidence} />
      )}
      {!!c.action_followups?.length && (
        <ActionFollowups items={c.action_followups} result={c.metrics} />
      )}
      {!!c.merchant_notes?.length && <MerchantNotes items={c.merchant_notes} />}
      {r.status !== 'failed' && finished && <ReportActions reportId={r.id} />}
      <section className={cx(css.panel, ui.panel)}>
        <h2>{t('证据附录')}</h2>
        <div className={css.evidenceList}>
          {c.evidence_index.map(ev => (
            <button key={ev.evidence_id} onClick={() => onEvidence(ev.evidence_id)}>
              <BookOpen size={15} />
              <strong>{t(toolNames[ev.tool])}</strong>
              <span>{ev.evidence_id.slice(0, 8)}</span>
              <ArrowRight size={14} />
            </button>
          ))}
        </div>
        <details className={css.reportSnapshot}>
          <summary>{t('冻结版本与指标口径')}</summary>
          <pre>{JSON.stringify(c.snapshot, null, 2)}</pre>
        </details>
      </section>
      {finished && (
        <>
          <Exports reportId={r.id} />
          <Questions reportId={r.id} onEvidence={onEvidence} limitedConsent={limitedConsent(c)} />
        </>
      )}
    </>
  );
}

export function ReportDetail() {
  const language = useLanguage();
  const { reportId = '' } = useParams();
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const closeEvidence = useCallback(() => setEvidenceId(null), []);
  const report = useQuery({
    queryKey: keys.report(reportId),
    queryFn: () => api<Report>(`/reports/${reportId}`),
    refetchInterval: pollWhile<Report>(data => !DONE.includes(data.status), POLL.fast),
  });
  const status = report.data?.status;
  const runs = useQuery({
    // The status is part of the key so the run list refreshes when the report finishes.
    queryKey: [...keys.reportRuns(reportId), status],
    queryFn: () => api<Run[]>(`/reports/${reportId}/runs`),
    refetchInterval: DONE.includes(status ?? '') ? false : POLL.normal,
  });
  const r = report.data;
  const c = r?.content;
  return (
    <div className={css.reports}>
      <Link className={cx(ui.backLink, forms.backLink)} to="/reports">
        <ArrowLeft size={15} />
        {t('返回周报中心')}
      </Link>
      <ErrorNotice error={report.error} />
      {r && (
        <>
          <section className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
            <div>
              <h1>{r.title}</h1>
              <p>
                {r.query.start} {t('至')}
                {lastDay(r.query.end_exclusive)} {t('· 修订')} {r.revision} {t('· 数据版本')}{' '}
                {r.dataset_id.slice(0, 8)}
              </p>
            </div>
            <Link className={cx(ui.secondary, forms.secondary)} to={`/reports/new?parent=${r.id}`}>
              {t('创建新修订')}
            </Link>
          </section>
          <div className={cx(css.reportStatus, 'report-status')} aria-live="polite">
            <ShieldCheck size={18} />
            <strong>{t(modes[c?.generation_mode ?? ''] ?? '正在准备报告')}</strong>
            <span>{t(states[r.status])}</span>
            {!DONE.includes(r.status) && <LoaderCircle size={16} className={ui.spin} />}
          </div>
          {c?.model_error_code && c.model_error_code !== 'NO_MODEL' && (
            <div className={cx(ui.reportWarning, 'report-warning')}>
              {t('模型分析未通过或暂不可用（')}
              {c.model_error_code}
              {t('），当前保留确定性摘要。可检查模型配置后创建新修订。')}
            </div>
          )}
          {r.status === 'failed' && (
            <div role="alert" className={ui.errorNotice}>
              {t('报告未完成：')}
              {r.error_code}
              {t('。可创建新修订重试。')}
            </div>
          )}
          {c && language === 'en' && (
            <p className={css.originalLanguageNote}>
              Report content is preserved in its original language.
            </p>
          )}
          {c && <Body report={r} content={c} onEvidence={setEvidenceId} />}
          <RunLog reportId={r.id} runs={runs.data} error={runs.error} />
        </>
      )}
      {evidenceId && (
        <EvidenceDrawer
          reportId={reportId}
          evidenceId={evidenceId}
          result={c?.metrics}
          onEvidence={setEvidenceId}
          onClose={closeEvidence}
        />
      )}
    </div>
  );
}
