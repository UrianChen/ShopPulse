import { locale, t, useLanguage } from '../../lib/i18n';
import type { Status } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';

const size = (value: number) =>
  value >= 1024 ** 3
    ? (value / 1024 ** 3).toFixed(1) + ' GiB'
    : (value / 1024 ** 2).toFixed(1) + ' MiB';

export function ServiceStatus({ status }: { status: Status }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('服务状态')}</h2>
      <div className={cx(css.opsStats, 'ops-stats')}>
        <div>
          <span>{t('队列等待')}</span>
          <strong>{status.jobs.queued ?? 0}</strong>
          <small>
            {t('最长等待')} {status.oldest_queued_seconds} {t('秒')}
          </small>
        </div>
        <div>
          <span>{t('在线 Worker')}</span>
          <strong>{status.workers.filter(w => w.online).length}</strong>
          <small>{t('最近 1 分钟')}</small>
        </div>
        <div>
          <span>{t('可用磁盘')}</span>
          <strong>{size(status.disk.free_bytes)}</strong>
          <small>
            {t('总计')} {size(status.disk.total_bytes)}
          </small>
        </div>
        <div>
          <span>{t('API 内存')}</span>
          <strong>{size(status.api_rss_bytes)}</strong>
        </div>
      </div>
      <details className={css.workerDetails}>
        <summary>{t('Worker 详情')}</summary>
        {status.workers.map(w => (
          <p className={cx(ui.formHint, forms.formHint)} key={w.id}>
            Worker {w.id.slice(0, 8)} · {w.online ? t('在线') : t('心跳过期')} · {size(w.rss_bytes)}{' '}
            · {new Date(w.heartbeat_at).toLocaleString(locale())}
          </p>
        ))}
      </details>
      <details>
        <summary>{t('任务状态与故障分类')}</summary>
        <pre>{JSON.stringify({ jobs: status.jobs, failures: status.failures }, null, 2)}</pre>
      </details>
    </section>
  );
}
