import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { message, t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { Plan } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';

const labels: Record<string, string> = {
  sources: '过期原文件',
  exports: '导出文件',
  orphans: '孤立文件',
  uploads: '上传记录及原文件',
  costs: '成本版本',
  datasets: '订单版本',
  reports: '报告及证据/追问',
  imports: '导入记录',
  snapshots: '指标缓存',
};

/** Retention cleanup and single-object deletion, both previewed before a typed confirmation. */
export function CleanupPanel() {
  useLanguage();
  const client = useQueryClient();
  const [kind, setKind] = useState('report');
  const [target, setTarget] = useState('');
  const [plan, setPlan] = useState<{ data: Plan; path: string } | null>(null);
  const [confirm, setConfirm] = useState('');
  const [result, setResult] = useState('');
  const preview = useMutation({
    mutationFn: (path: string) => api<Plan>(path).then(data => ({ data, path })),
    onSuccess: p => {
      setPlan(p);
      setConfirm('');
      setResult('');
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      api<{ pending_files: number }>(plan!.path, {
        method: 'POST',
        body: JSON.stringify({
          token: plan!.data.token,
          confirmation: confirm === t('确认删除') ? '确认删除' : confirm,
        }),
      }),
    onSuccess: r => {
      setPlan(null);
      setConfirm('');
      setResult(
        r.pending_files
          ? t('数据库已更新，{0} 个文件待下次孤立清理重试。', r.pending_files)
          : t('操作已完成。'),
      );
      void client.invalidateQueries({ queryKey: keys.operationsAudit });
      void client.invalidateQueries({ queryKey: keys.operationsJobs });
    },
  });
  const changeTarget = () => {
    setPlan(null);
    setConfirm('');
  };
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('清理与删除')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('删除会影响关联报告及导出，请先核对预览。仅在任务空闲时执行。')}
      </p>
      <button
        className={cx(ui.secondary, forms.secondary)}
        onClick={() => preview.mutate('/operations/cleanup')}
      >
        {t('预览到期清理')}
      </button>
      <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
        <label className={cx(ui.field, forms.field)}>
          {t('删除对象类型')}
          <select
            value={kind}
            onChange={e => {
              setKind(e.target.value);
              changeTarget();
            }}
          >
            <option value="report">{t('报告')}</option>
            <option value="dataset">{t('订单版本')}</option>
            <option value="cost">{t('成本版本及关联订单')}</option>
            <option value="upload">{t('上传及所有关联数据')}</option>
          </select>
        </label>
        <label className={cx(ui.field, forms.field)}>
          {t('对象 ID')}
          <input
            value={target}
            onChange={e => {
              setTarget(e.target.value);
              changeTarget();
            }}
            placeholder={t('从数据详情或报告地址复制 UUID')}
          />
        </label>
      </div>
      <button
        className={cx(ui.secondary, forms.secondary)}
        disabled={!target.trim() || preview.isPending}
        onClick={() =>
          preview.mutate(`/operations/deletion/${kind}/${encodeURIComponent(target.trim())}`)
        }
      >
        {t('预览删除影响')}
      </button>
      {plan && (
        <div className={cx(css.deletionPreview, 'deletion-preview')}>
          <h3>{t('请核对本次影响')}</h3>
          <ul>
            {Object.entries(plan.data.counts).map(([key, count]) => (
              <li key={key}>
                {t(labels[key] ?? key)}：{count}
              </li>
            ))}
          </ul>
          <label className={cx(ui.field, forms.field)}>
            {t('输入“确认删除”以执行')}
            <input value={confirm} onChange={e => setConfirm(e.target.value)} />
          </label>
          <button
            className={ui.danger}
            disabled={confirm !== t('确认删除') || remove.isPending}
            onClick={() => remove.mutate()}
          >
            {t('执行已预览操作')}
          </button>
          <button className={cx(ui.secondary, forms.secondary)} onClick={() => setPlan(null)}>
            {t('返回')}
          </button>
        </div>
      )}
      <ErrorNotice error={preview.error ?? remove.error} />
      {result && <p role="status">{message(result)}</p>}
    </section>
  );
}
