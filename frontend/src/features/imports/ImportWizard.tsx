import { t, useLanguage, message } from '../../lib/i18n';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { api } from '../../lib/api';
import { POLL, pollWhile } from '../../lib/queries';
import type { Paged } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { ImportState } from './ImportState';
import { keys } from './keys';
import { MappingSection } from './MappingSection';
import { OptionsSection } from './OptionsSection';
import { PublishedCard } from './PublishedCard';
import { QualitySection } from './QualitySection';
import type { Draft, Issue, UploadRecord, Version } from './types';
import { mappingText, useDraftForm } from './useDraftForm';
import { useImportActions } from './useImportActions';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

const WORKING = ['validating', 'publishing'];

/** Configure, validate and publish one import draft. */
export function ImportWizard({ id, onBack }: { id: string; onBack: () => void }) {
  useLanguage();
  const draft = useQuery({
    queryKey: keys.importDraft(id),
    queryFn: () => api<Draft>(`/imports/${id}`),
    refetchInterval: pollWhile<Draft>(d => WORKING.includes(d.status), POLL.fast),
  });
  const current = draft.data;
  const uploadId = current?.upload_id;
  const upload = useQuery({
    queryKey: keys.upload(uploadId ?? ''),
    enabled: !!uploadId,
    queryFn: () => api<UploadRecord>(`/uploads/${uploadId}`),
  });
  const costs = useQuery({
    queryKey: keys.costVersions,
    queryFn: () => api<Version[]>('/cost-versions'),
  });
  const form = useDraftForm(current);
  const { config, offset } = form;
  const problems = useQuery({
    queryKey: keys.importIssuePage(id, current?.validated_revision, current?.status, offset),
    enabled: !!current?.validated_revision,
    queryFn: () => api<Paged<Issue>>(`/imports/${id}/issues?offset=${offset}&limit=100`),
  });
  const { save, resolve, publish } = useImportActions(id, current, form);
  const error =
    draft.error ??
    upload.error ??
    costs.error ??
    save.error ??
    resolve.error ??
    publish.error ??
    problems.error;
  if (!current || !config)
    return (
      <>
        <ErrorNotice error={error} />
        <p className={css.muted}>{t('读取导入配置…')}</p>
      </>
    );
  const metadata = current.summary?.preview ?? upload.data?.metadata;
  const isOrder = current.kind === 'orders';
  const busy =
    WORKING.includes(current.status) || save.isPending || resolve.isPending || publish.isPending;
  const locked =
    ['published', 'publishing', 'deleted'].includes(current.status) ||
    upload.data?.source_available === false;
  const dirty =
    JSON.stringify(config) !== JSON.stringify(current.config) ||
    form.statusMapping !== mappingText(current.config.options.status_mapping);
  return (
    <div className={css.importWizard}>
      <button className={cx(ui.backLink, forms.backLink)} onClick={onBack}>
        <ArrowLeft size={15} />
        {t('返回数据中心')}
      </button>
      <div className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{current.name}</h1>
          <p>
            {isOrder ? t('订单明细') : t('商品成本')} {t('· 修订')} {current.revision}{' '}
            {t('· 发布后数据不可原地修改')}
          </p>
        </div>
        <ImportState value={current.status} />
      </div>
      <ErrorNotice error={error} />
      {current.error_message && (
        <div className={ui.errorNotice}>{message(current.error_message)}</div>
      )}
      {upload.data?.source_available === false && (
        <p className={ui.errorNotice}>
          {t('原文件已按保留策略清理，无法重新导入或核对原表。已发布的标准化数据和报告仍可使用。')}
        </p>
      )}
      {current.status === 'published' ? (
        <PublishedCard draft={current} onBack={onBack} />
      ) : (
        <>
          <MappingSection
            config={config}
            onChange={form.setConfig}
            metadata={metadata}
            isOrder={isOrder}
            disabled={busy || locked}
          />
          <OptionsSection
            config={config}
            onChange={form.setConfig}
            isOrder={isOrder}
            costs={costs.data}
            statusMapping={form.statusMapping}
            onStatusMapping={form.setStatusMapping}
            busy={busy}
            locked={locked}
            onSave={() => save.mutate()}
          />
          {current.summary && (
            <QualitySection
              status={current.status}
              summary={current.summary}
              issues={problems.data}
              form={form}
              busy={busy}
              dirty={dirty}
              onResolve={() => resolve.mutate(current.revision)}
              onPublish={() => publish.mutate(current.revision)}
            />
          )}
        </>
      )}
    </div>
  );
}
