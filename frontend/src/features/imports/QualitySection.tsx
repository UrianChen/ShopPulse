import { t, useLanguage } from '../../lib/i18n';
import { CheckCircle2 } from 'lucide-react';
import type { Paged } from '../../lib/types';
import { ImportState } from './ImportState';
import { IssueTable } from './IssueTable';
import { ResolutionBox } from './ResolutionBox';
import type { Issue, Summary } from './types';
import type { DraftForm } from './useDraftForm';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = {
  status: string;
  summary: Summary;
  issues: Paged<Issue> | undefined;
  form: DraftForm;
  busy: boolean;
  dirty: boolean;
  onResolve: () => void;
  onPublish: () => void;
};

/** Step 03: validation results, resolution decisions and publishing. */
export function QualitySection(props: Props) {
  useLanguage();
  const { status, summary, form, busy, dirty } = props;
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{t('03 · 处理数据质量问题')}</h2>
          <p>{t('排除或确认后会产生新的配置修订，并重新校验。')}</p>
        </div>
        <ImportState value={status} />
      </div>
      <div className={css.qualityStats}>
        <div>
          <strong>{summary.source_rows}</strong>
          <span>{t('原始数据行')}</span>
        </div>
        <div>
          <strong>{summary.included_rows}</strong>
          <span>{t('拟纳入行')}</span>
        </div>
        <div>
          <strong>{summary.errors}</strong>
          <span>{t('阻断问题')}</span>
        </div>
        <div>
          <strong>{summary.unacknowledged}</strong>
          <span>{t('待确认警告')}</span>
        </div>
      </div>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('已排除')}
        {summary.excluded_rows} {t('行 · 未支付')}
        {summary.unpaid_rows} {t('行 · 成本匹配')}
        {summary.cost_matched_rows} {t('行')}
      </p>
      <IssueTable issues={props.issues} offset={form.offset} onOffset={form.setOffset} />
      {status === 'review_required' && (
        <ResolutionBox summary={summary} form={form} busy={busy} onResolve={props.onResolve} />
      )}
      <div className={css.publishActions}>
        <div>
          <strong>{t('发布不可变数据版本')}</strong>
          <p>
            {dirty
              ? t('你有未保存的修改，请先保存并重新校验。')
              : t('后续修改需要创建新版本；有未解决阻断或警告时禁止发布。')}
          </p>
        </div>
        <button
          className={cx(css.primary, ui.primary)}
          disabled={status !== 'ready' || busy || dirty}
          onClick={props.onPublish}
        >
          <CheckCircle2 size={16} />
          {t('发布数据版本')}
        </button>
      </div>
    </section>
  );
}
