import { t, useLanguage } from '../../lib/i18n';
import { metricNames } from './labels';
import type { Finding, OnEvidence, Recommendation, Sentence } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './reports.module.css';

/** Server-rendered sentences, each with links to the evidence its values came from. */
export function Sentences({ values, onEvidence }: { values: Sentence[]; onEvidence: OnEvidence }) {
  useLanguage();
  return (
    <div className={css.reportSentences}>
      {values.map((s, i) => (
        <p key={i}>
          {s.text}{' '}
          {s.evidence_refs.map((id, n) => (
            <button className={css.evidenceLink} key={id} onClick={() => onEvidence(id)}>
              {s.evidence_refs.length > 1 ? t('证据 {0}', n + 1) : t('查看证据')}
            </button>
          ))}
        </p>
      ))}
    </div>
  );
}

export function Advice({
  findings,
  recommendations,
  onEvidence,
}: {
  findings: Finding[];
  recommendations: Recommendation[];
  onEvidence: OnEvidence;
}) {
  useLanguage();
  return (
    <>
      {findings.map(f => (
        <div className={css.reportFinding} key={f.id}>
          <h3>{f.title}</h3>
          <Sentences values={[f.observation, ...(f.supporting ?? [])]} onEvidence={onEvidence} />
          {f.supported_hypotheses?.map(h => (
            <p className={cx(css.hypothesis, css.hypothesisSupported)} key={h.id}>
              <b>{t('数据支持的假设')}</b>
              {h.text ?? h.id}{' '}
              <button className={css.evidenceLink} onClick={() => onEvidence(h.evidence_id)}>
                {t('查看检验')}
              </button>
            </p>
          ))}
          {f.hypotheses.map((h, i) => (
            <p className={css.hypothesis} key={i}>
              <b>{t('待验证假设')}</b>
              {h}
            </p>
          ))}
        </div>
      ))}
      <div className={css.reportAdvice}>
        {recommendations.map((r, i) => (
          <div key={i}>
            <span className={cx(css.subtleBadge, ui.subtleBadge)}>
              {{ high: t('优先核查'), medium: t('建议跟进'), low: t('持续观察') }[r.priority]}
            </span>
            <p>{r.action}</p>
            <small>
              {t('预计工作量：')}
              {{ small: t('小'), medium: t('中'), large: t('大') }[r.effort]} {t('· 验证指标：')}
              {t(metricNames[r.verification_metric] ?? r.verification_metric)} {t('· 建议复查：')}
              {r.suggested_review_window === 'next_month' ? t('下月') : t('下周')}
            </small>
            {[
              ...new Set(
                r.evidence_refs ??
                  findings
                    .filter(f => r.rationale_finding_ids?.includes(f.id))
                    .flatMap(f => f.evidence_refs),
              ),
            ].map((id, n, all) => (
              <button className={css.evidenceLink} key={id} onClick={() => onEvidence(id)}>
                {all.length > 1 ? t('证据 {0}', n + 1) : t('查看依据')}
              </button>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
