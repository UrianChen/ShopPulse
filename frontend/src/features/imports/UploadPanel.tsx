import { t, useLanguage, message } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Download, FileSpreadsheet, LoaderCircle, UploadCloud } from 'lucide-react';
import { api } from '../../lib/api';
import { POLL, pollWhile } from '../../lib/queries';
import type { Body } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { keys } from './keys';
import { SourcePreview } from './SourcePreview';
import type { Draft, Kind, UploadRecord } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

export function UploadPanel({ onCreated }: { onCreated: (id: string) => void }) {
  useLanguage();
  const [kind, setKind] = useState<Kind>('orders');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [uploadId, setUploadId] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error(t('请选择 CSV 或 XLSX 文件。'));
      if (file.size > 20 * 1024 * 1024) throw new Error(t('文件超过 20 MiB，请拆分后上传。'));
      const body = new FormData();
      body.append('file', file);
      body.append('kind', kind);
      return api<{ upload_id: string }>('/uploads', {
        method: 'POST',
        body,
        signal: AbortSignal.timeout(120000),
      });
    },
    onSuccess: result => setUploadId(result.upload_id),
  });
  const record = useQuery({
    queryKey: keys.upload(uploadId ?? ''),
    enabled: !!uploadId,
    queryFn: () => api<UploadRecord>(`/uploads/${uploadId}`),
    refetchInterval: pollWhile<UploadRecord>(r => r.status === 'parsing', POLL.fast),
  });
  const create = useMutation({
    mutationFn: (body: Body<'NewImport'>) =>
      api<Draft>('/imports', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: result => onCreated(result.id),
  });
  const busy = upload.isPending || record.data?.status === 'parsing' || create.isPending;
  function chooseKind(next: Kind) {
    setKind(next);
    setUploadId(null);
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    upload.mutate();
  }
  return (
    <section className={cx(css.panel, ui.panel, css.importUpload)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{t('导入数据')}</h2>
          <p>{t('建议先导入成本，再导入订单。')}</p>
        </div>
        <UploadCloud size={23} />
      </div>
      <form onSubmit={submit}>
        <div className={css.kindSwitch}>
          <button
            type="button"
            className={kind === 'orders' ? css.selected : undefined}
            disabled={busy}
            onClick={() => chooseKind('orders')}
          >
            {t('订单明细')}
          </button>
          <button
            type="button"
            className={kind === 'costs' ? css.selected : undefined}
            disabled={busy}
            onClick={() => chooseKind('costs')}
          >
            {t('商品成本')}
          </button>
        </div>
        <label className={css.fileDrop}>
          <FileSpreadsheet size={32} />
          <strong>{file?.name ?? t('选择 CSV 或 Excel 文件')}</strong>
          <span>{t('最大 20 MiB · 最多 100,000 行 · .csv / .xlsx')}</span>
          <input
            aria-label={t('选择数据文件')}
            type="file"
            accept=".csv,.xlsx"
            disabled={busy}
            onChange={e => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setName(f?.name ?? '');
              setUploadId(null);
            }}
          />
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('导入名称')}
          <input
            aria-label={t('导入名称')}
            value={name}
            onChange={e => setName(e.target.value)}
            maxLength={120}
            required
          />
        </label>
        <div className={cx(ui.formActions, forms.formActions)}>
          <button className={cx(css.primary, ui.primary)} disabled={!file || busy} type="submit">
            {busy ? <LoaderCircle size={15} className={ui.spin} /> : <UploadCloud size={15} />}
            {busy ? t('正在解析…') : t('上传并预览')}
          </button>
          {record.data && ['ready', 'failed'].includes(record.data.status) && (
            <button
              type="button"
              className={cx(ui.secondary, forms.secondary)}
              disabled={create.isPending}
              onClick={() =>
                create.mutate({
                  upload_id: record.data.id,
                  name: name.trim() || (file?.name ?? ''),
                })
              }
            >
              {t('配置字段与口径')}
            </button>
          )}
        </div>
      </form>
      <ErrorNotice error={upload.error ?? record.error ?? create.error} />
      {record.data?.error_message && (
        <div className={ui.errorNotice}>
          {message(record.data.error_message)}
          <br />
          {t('可继续配置编码、标题行或工作表后重新校验。')}
        </div>
      )}
      <SourcePreview data={record.data?.metadata} />
      <div className={css.sampleLinks}>
        <span>{t('使用合成样例：')}</span>
        {[
          ['costs.csv', t('成本表')],
          ['orders.csv', t('订单 CSV')],
          ['orders.xlsx', t('订单 Excel')],
          ['orders_errors.csv', t('错误样例')],
        ].map(([filename, label]) => (
          <a key={filename} href={`/api/v1/samples/${filename}`} download>
            <Download size={12} />
            {t(label)}
          </a>
        ))}
      </div>
    </section>
  );
}
