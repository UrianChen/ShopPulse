import { t, useLanguage } from '../../lib/i18n';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { api } from '../../lib/api';
import { ErrorNotice } from '../../components/ErrorNotice';
import { CostDetail } from './CostDetail';
import { DatasetDetail } from './DatasetDetail';
import { ImportList } from './ImportList';
import { ImportWizard } from './ImportWizard';
import { keys } from './keys';
import { UploadPanel } from './UploadPanel';
import { VersionList } from './VersionList';
import type { CostVersionDetail, Draft, OrderVersionDetail, Version } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';
import '../../styles/tables.css';

const LIST_POLL = 5000;

export function DataCenter() {
  useLanguage();
  const [params, setParams] = useSearchParams();
  const id = params.get('import');
  const imports = useQuery({
    queryKey: keys.imports,
    queryFn: () => api<Draft[]>('/imports'),
    refetchInterval: LIST_POLL,
  });
  const datasets = useQuery({
    queryKey: keys.datasets,
    queryFn: () => api<Version[]>('/datasets'),
    refetchInterval: LIST_POLL,
  });
  const costs = useQuery({
    queryKey: keys.costVersions,
    queryFn: () => api<Version[]>('/cost-versions'),
    refetchInterval: LIST_POLL,
  });
  const [newUpload, setNewUpload] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [costDetailId, setCostDetailId] = useState<string | null>(null);
  const costDetail = useQuery({
    queryKey: keys.costVersion(costDetailId ?? ''),
    enabled: !!costDetailId,
    queryFn: () => api<CostVersionDetail>(`/cost-versions/${costDetailId}`),
  });
  const detail = useQuery({
    queryKey: keys.dataset(detailId ?? ''),
    enabled: !!detailId,
    queryFn: () => api<OrderVersionDetail>(`/datasets/${detailId}`),
  });
  const client = useQueryClient();
  function back() {
    setParams({});
    setNewUpload(false);
    void client.invalidateQueries({ queryKey: keys.datasets });
    void client.invalidateQueries({ queryKey: keys.costVersions });
    void client.invalidateQueries({ queryKey: keys.imports });
  }
  if (id) return <ImportWizard key={id} id={id} onBack={back} />;
  const versionsPending = datasets.isPending || costs.isPending;
  return (
    <div className={css.dataCenter}>
      <div className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('数据中心')}</h1>
          <p>{t('管理订单与成本数据。')}</p>
        </div>
        <button className={cx(css.primary, ui.primary)} onClick={() => setNewUpload(!newUpload)}>
          <Plus size={16} />
          {newUpload ? t('收起上传') : t('导入数据')}
        </button>
      </div>

      {(newUpload || imports.data?.length === 0) && (
        <UploadPanel
          onCreated={next => {
            setParams({ import: next });
            void client.invalidateQueries({ queryKey: keys.imports });
          }}
        />
      )}
      {(imports.isPending || versionsPending) && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)} role="status">
          {t('读取中…')}
        </p>
      )}
      <ErrorNotice
        error={imports.error ?? datasets.error ?? costs.error ?? detail.error ?? costDetail.error}
      />
      <ImportList
        imports={imports.data}
        pending={imports.isPending}
        onOpen={item => setParams({ import: item })}
      />
      <div className={css.versionGrid}>
        <VersionList
          title={t('已发布订单版本')}
          versions={datasets.data ?? []}
          pending={versionsPending}
          onOpen={version => {
            setDetailId(version);
            setCostDetailId(null);
          }}
        />
        <VersionList
          title={t('已发布成本版本')}
          versions={costs.data ?? []}
          pending={versionsPending}
          onOpen={version => {
            setCostDetailId(version);
            setDetailId(null);
          }}
        />
      </div>
      {(detail.data?.source_available === false || costDetail.data?.source_available === false) && (
        <p className={ui.errorNotice}>
          {t('原文件已清理，无法核对原表。以下标准化数据与文件哈希仍保留。')}
        </p>
      )}
      {detail.data && <DatasetDetail detail={detail.data} onClose={() => setDetailId(null)} />}
      {costDetail.data && (
        <CostDetail detail={costDetail.data} onClose={() => setCostDetailId(null)} />
      )}
    </div>
  );
}
