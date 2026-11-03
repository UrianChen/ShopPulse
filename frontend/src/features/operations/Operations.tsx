import { useQuery } from '@tanstack/react-query';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { keys, POLL } from '../../lib/queries';
import { AuditLog } from './AuditLog';
import { CleanupPanel } from './CleanupPanel';
import { JobsTable } from './JobsTable';
import { ServiceStatus } from './ServiceStatus';
import { SettingsForm } from './SettingsForm';
import type { Config, Status, Task } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';
import '../../styles/tables.css';

export function Operations() {
  useLanguage();
  const config = useQuery({
    queryKey: keys.operationsSettings,
    queryFn: () => api<Config>('/operations/settings'),
  });
  const state = useQuery({
    queryKey: keys.operationsStatus,
    queryFn: () => api<Status>('/operations/status'),
    refetchInterval: 5000,
  });
  const jobs = useQuery({
    queryKey: keys.operationsJobs,
    queryFn: () => api<Task[]>('/jobs'),
    refetchInterval: POLL.slow,
  });
  return (
    <div className={css.operations}>
      <section className={cx(ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('运行管理')}</h1>
          <p>{t('任务、存储与店铺设置。')}</p>
        </div>
      </section>
      {(config.isPending || state.isPending) && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)} role="status">
          {t('读取中…')}
        </p>
      )}
      <ErrorNotice error={config.error ?? state.error ?? jobs.error} />
      {state.data && <ServiceStatus status={state.data} />}
      {config.data && <SettingsForm key={config.data.revision} initial={config.data} />}
      <JobsTable jobs={jobs.data} />
      <CleanupPanel />
      <AuditLog />
      <section className={cx(css.panel, ui.panel)}>
        <h2>{t('备份与恢复')}</h2>
        <p>{t('使用 scripts/backup.py 备份数据，密钥需独立保管。')}</p>
        <p className={cx(ui.formHint, forms.formHint)}>
          {t('操作见 README.md。备份时服务会短暂停止。')}
        </p>
      </section>
    </div>
  );
}
