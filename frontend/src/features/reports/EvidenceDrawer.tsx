import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { Result } from '../dashboard/Dashboard';
import { EvidenceView } from './EvidenceViews';
import type { OnEvidence } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './reports.module.css';

export type EvidenceRecord = {
  evidence_id: string;
  tool: string;
  args?: Record<string, unknown>;
  payload: Record<string, unknown>;
  result_hash?: string;
};

/** Modal drawer for one evidence record; opening another record replaces the content. */
export function EvidenceDrawer({
  reportId,
  evidenceId,
  result,
  onEvidence,
  onClose,
}: {
  reportId: string;
  evidenceId: string;
  result: Result | undefined;
  onEvidence: OnEvidence;
  onClose: () => void;
}) {
  useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  const evidence = useQuery({
    queryKey: keys.reportEvidence(reportId, evidenceId),
    queryFn: () => api<EvidenceRecord>(`/reports/${reportId}/evidence/${evidenceId}`),
  });
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    // Clicking the backdrop closes the drawer; Escape and the close button are the
    // keyboard paths, so this pointer shortcut is attached outside JSX.
    const backdrop = (event: MouseEvent) => {
      if (event.target === element) onClose();
    };
    element.addEventListener('click', backdrop);
    return () => element.removeEventListener('click', backdrop);
  }, [onClose]);
  return (
    <dialog
      ref={dialog}
      className={css.evidenceOverlay}
      aria-label={t('计算证据')}
      onCancel={onClose}
    >
      <section className={css.evidenceDrawer}>
        <div className={cx(css.panelTitle, ui.panelTitle)}>
          <div>
            <h2>{t('计算证据')}</h2>
            <p>{evidenceId}</p>
          </div>
          <button className={css.iconButton} aria-label={t('关闭证据')} onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <ErrorNotice error={evidence.error} />
        {evidence.isPending ? (
          <p>{t('读取中…')}</p>
        ) : (
          evidence.data && (
            <>
              <EvidenceView record={evidence.data} result={result} onEvidence={onEvidence} />
              <details open={!EvidenceView.handles(evidence.data.tool)}>
                <summary>{t('原始证据数据')}</summary>
                <pre>{JSON.stringify(evidence.data, null, 2)}</pre>
              </details>
            </>
          )
        )}
      </section>
    </dialog>
  );
}
