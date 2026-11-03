import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { Task } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';

const statusName: Record<string, string> = {
  queued: '排队',
  running: '运行',
  succeeded: '完成',
  failed: '失败',
  cancelled: '取消',
};

export function JobsTable({ jobs }: { jobs: Task[] | undefined }) {
  useLanguage();
  const client = useQueryClient();
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api(`/operations/jobs/${id}/${action}`, { method: 'POST' }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.operationsJobs });
      void client.invalidateQueries({ queryKey: keys.operationsAudit });
    },
  });
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('最近任务')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>{t('取消后，已发送的模型请求仍可能计费。')}</p>
      {/* Keyboard users can scroll the wide table. */}
      <div
        className={cx(css.tableScroll, ui.tableScroll, forms.tableScroll)}
        role="region"
        aria-label={t('最近任务')}
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th>{t('任务')}</th>
              <th>{t('状态')}</th>
              <th>{t('尝试')}</th>
              <th>{t('操作')}</th>
            </tr>
          </thead>
          <tbody>
            {jobs?.map(j => (
              <tr key={j.id}>
                <td>
                  {j.type}
                  <small className={css.mono} title={j.id}>
                    {j.id.slice(0, 8)}
                  </small>
                </td>
                <td>
                  {t(statusName[j.status])}
                  <small>{j.error_code}</small>
                </td>
                <td>{j.attempt}</td>
                <td>
                  {['queued', 'running'].includes(j.status) ? (
                    <button
                      className={cx(ui.textButton, forms.textButton)}
                      disabled={act.isPending}
                      onClick={() => act.mutate({ id: j.id, action: 'cancel' })}
                    >
                      {t('取消任务')}
                    </button>
                  ) : ['failed', 'cancelled'].includes(j.status) &&
                    j.error_code !== 'RESOURCE_DELETED' ? (
                    <button
                      className={cx(ui.textButton, forms.textButton)}
                      disabled={act.isPending}
                      onClick={() => act.mutate({ id: j.id, action: 'retry' })}
                    >
                      {t('重试任务')}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorNotice error={act.error} />
    </section>
  );
}
