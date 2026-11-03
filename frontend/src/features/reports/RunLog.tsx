import { useEffect, useState } from 'react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { t, useLanguage } from '../../lib/i18n';
import { stepText } from './labels';
import type { Run, Step } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

export const ACTIVE_RUN = ['computing', 'analyzing'];

function useLiveSteps(reportId: string, runId?: string) {
  // Server-sent events stream the trajectory while the model works; polling remains the fallback.
  const [live, setLive] = useState<{ runId?: string; steps: Step[] }>({ steps: [] });
  useEffect(() => {
    if (!runId || typeof EventSource === 'undefined') return;
    const source = new EventSource(`/api/v1/reports/${reportId}/runs/${runId}/events`);
    source.addEventListener('step', event => {
      const data = JSON.parse((event as MessageEvent<string>).data) as {
        index: number;
        step: Step;
      };
      setLive(previous => ({
        runId,
        steps: [
          ...(previous.runId === runId ? previous.steps : []).slice(0, data.index),
          data.step,
        ],
      }));
    });
    source.addEventListener('done', () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
  }, [reportId, runId]);
  // Steps streamed for an earlier run never leak into the current one.
  return live.runId === runId ? live.steps : [];
}

export function RunLog({
  reportId,
  runs,
  error,
}: {
  reportId: string;
  runs: Run[] | undefined;
  error: unknown;
}) {
  useLanguage();
  const activeRun = runs?.find(run => ACTIVE_RUN.includes(run.status));
  const liveSteps = useLiveSteps(reportId, activeRun?.id);
  return (
    <section className={cx(css.panel, ui.panel, css.reportRun)}>
      <h2>{t('运行记录')}</h2>
      <ErrorNotice error={error} />
      {runs?.map(run => {
        const active = run.id === activeRun?.id;
        const steps = active && liveSteps.length > run.steps.length ? liveSteps : run.steps;
        return (
          <details key={run.id} open={active}>
            <summary>
              {run.id.slice(0, 8)} · {run.status} {run.error_code && `· ${run.error_code}`}
            </summary>
            <ol className={css.trajectory} aria-live={active ? 'polite' : undefined}>
              {steps.map((s, i) => (
                <li key={i} className={s.ok === false || s.error ? css.stepError : undefined}>
                  {stepText(s)}
                </li>
              ))}
            </ol>
            {run.trace_id && (
              <p className={cx(ui.formHint, forms.formHint)}>Trace {run.trace_id}</p>
            )}
            <pre>{JSON.stringify(run.usage, null, 2)}</pre>
          </details>
        );
      })}
    </section>
  );
}
