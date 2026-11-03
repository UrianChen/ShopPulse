import { t, useLanguage, locale } from '../../lib/i18n';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { BellRing, CalendarClock, Play, Plus, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { keys } from '../../lib/queries';
import { lastDay } from '../../lib/dates';
import type { DatasetVersion, ModelConfig } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { formats, stateText, weekdays } from './constants';
import { ScheduleForm } from './ScheduleForm';
import type { Schedule } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './automation.module.css';

export function Schedules() {
  useLanguage();
  const client = useQueryClient();
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<unknown>(null);
  const schedules = useQuery({
    queryKey: keys.schedules,
    queryFn: () => api<Schedule[]>('/schedules'),
  });
  const versions = useQuery({
    queryKey: keys.datasets,
    queryFn: () => api<DatasetVersion[]>('/datasets'),
  });
  const models = useQuery({
    queryKey: keys.modelConfigs,
    queryFn: () => api<ModelConfig[]>('/model-configs'),
  });
  function refresh() {
    void client.invalidateQueries({ queryKey: keys.schedules });
  }
  async function run(item: Schedule) {
    setError(null);
    setNotice('');
    try {
      const result = await api<{ status: string; report_id: string | null }>(
        `/schedules/${item.id}/run`,
        { method: 'POST' },
      );
      setNotice(stateText(result.status));
      refresh();
    } catch (failure) {
      setError(failure);
    }
  }
  async function remove(item: Schedule) {
    setError(null);
    try {
      await api(`/schedules/${item.id}`, { method: 'DELETE' });
      refresh();
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <section className={css.automationSection}>
      <div className={ui.panelTitle}>
        <div>
          <h2>
            <CalendarClock size={19} />
            {t('定时周报')}
          </h2>
          <p className={cx(ui.formHint, forms.formHint)}>
            {t('按计划自动生成新一期报告，并可推送到群机器人。')}
          </p>
        </div>
        <button className={ui.primary} disabled={!!editing} onClick={() => setEditing('new')}>
          <Plus size={16} />
          {t('新建定时周报')}
        </button>
      </div>
      <ErrorNotice error={schedules.error ?? error} />
      {notice && (
        <p className={cx(ui.reportWarning, 'report-warning')} role="status">
          {notice}
        </p>
      )}
      {editing && (
        <ScheduleForm
          key={editing === 'new' ? 'new' : editing.id}
          item={editing === 'new' ? undefined : editing}
          versions={versions.data ?? []}
          models={models.data ?? []}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {schedules.data?.length === 0 && !editing && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('还没有定时周报。')}</p>
      )}
      <div className={css.scheduleList}>
        {schedules.data?.map(item => (
          <article className={cx(ui.panel, css.scheduleCard)} key={item.id}>
            <div>
              <h3>
                {item.name}
                {!item.enabled && <span className={ui.subtleBadge}>{t('已停用')}</span>}
                {item.has_webhook && (
                  <span className={ui.subtleBadge}>
                    <BellRing size={12} />
                    {t(formats[item.webhook_format])}
                  </span>
                )}
              </h3>
              <p>
                {t(
                  '每{0} {1}:00（{2}）',
                  t(weekdays[item.weekday]),
                  String(item.hour).padStart(2, '0'),
                  item.timezone,
                )}{' '}
                · {t('分析最近 {0} 天', item.period_days)}
              </p>
              <small>
                {t('下次执行：')}
                {item.next_run_at
                  ? new Date(item.next_run_at).toLocaleString(locale())
                  : '—'} · {t('上次结果：')}
                {stateText(item.last_status)}
                {item.last_report_id && (
                  <>
                    {' '}
                    · <Link to={`/reports/${item.last_report_id}`}>{t('查看最近报告')}</Link>
                  </>
                )}
              </small>
              {item.next_period && (
                <small>
                  {t('下一期范围：')}
                  {item.next_period.start} {t('至')} {lastDay(item.next_period.end_exclusive)}
                </small>
              )}
            </div>
            <div className={cx(ui.formActions, forms.formActions)}>
              <button className={cx(ui.secondary, forms.secondary)} onClick={() => void run(item)}>
                <Play size={15} />
                {t('立即运行')}
              </button>
              <button
                className={cx(ui.secondary, forms.secondary)}
                disabled={!!editing}
                onClick={() => setEditing(item)}
              >
                {t('编辑')}
              </button>
              <button
                className={cx(ui.textButton, forms.textButton)}
                onClick={() => void remove(item)}
              >
                <Trash2 size={15} />
                {t('删除')}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
