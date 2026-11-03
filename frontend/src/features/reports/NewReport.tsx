import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { DatasetVersion, ModelConfig } from '../../lib/types';
import { ReportForm } from './ReportForm';
import type { Report } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './reports.module.css';

export function NewReport() {
  useLanguage();
  const [params] = useSearchParams();
  const parentId = params.get('parent');
  const start = params.get('start');
  const preset = start
    ? {
        start,
        end: params.get('end') ?? '',
        comparison: params.get('comparison') ?? 'previous',
        skus: params.get('skus') ?? '',
      }
    : undefined;
  const parent = useQuery({
    queryKey: keys.report(parentId ?? ''),
    enabled: !!parentId,
    queryFn: () => api<Report>(`/reports/${parentId}`),
  });
  const versions = useQuery({
    queryKey: keys.datasets,
    queryFn: () => api<DatasetVersion[]>('/datasets'),
  });
  const models = useQuery({
    queryKey: keys.modelConfigs,
    queryFn: () => api<ModelConfig[]>('/model-configs'),
  });
  const parentDatasetId = parent.data?.dataset_id;
  const parentDataset = useQuery({
    queryKey: keys.dataset(parentDatasetId ?? ''),
    enabled: !!parentDatasetId,
    queryFn: () => api<DatasetVersion>(`/datasets/${parentDatasetId}`),
  });
  if (
    versions.isPending ||
    models.isPending ||
    (parentId && (parent.isPending || parentDataset.isPending))
  )
    return <p>{t('正在读取已发布数据…')}</p>;
  const error = versions.error ?? models.error ?? parent.error ?? parentDataset.error;
  if (error) return <ErrorNotice error={error} />;
  if (!versions.data?.length)
    return (
      <section className={cx(css.panel, ui.panel, css.reportEmpty)}>
        <h1>{t('先准备一份订单数据')}</h1>
        <p>{t('周报使用数据中心已发布的版本。')}</p>
        <Link className={cx(css.primary, ui.primary)} to="/data">
          {t('前往数据中心')}
        </Link>
      </section>
    );
  const choices =
    parentDataset.data && !versions.data.some(v => v.id === parentDataset.data.id)
      ? [parentDataset.data, ...versions.data]
      : versions.data;
  return (
    <ReportForm
      versions={choices}
      models={models.data ?? []}
      parent={parent.data}
      preset={preset}
    />
  );
}
