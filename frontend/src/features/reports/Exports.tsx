import { t, useLanguage, locale, message } from '../../lib/i18n';
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../../lib/api';

type Export = { id: string; format: string; status: string; error_code: string | null; expires_at: string };
export function Exports({ reportId }: { reportId: string }) {
  useLanguage();
  const [format, setFormat] = useState('pdf');
  const [key, setKey] = useState(crypto.randomUUID());
  const list = useQuery({ queryKey: ['exports', reportId], queryFn: () => api<Export[]>(`/reports/${reportId}/exports`), refetchInterval: q => q.state.data?.some(e => e.status === 'queued') ? 1500 : false });
  const create = useMutation({ mutationFn: () => api(`/reports/${reportId}/exports`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ format }) }), onSuccess: () => { setKey(crypto.randomUUID()); void list.refetch(); } });
  return <section className="panel report-exports"><h2>{t("导出报告")}</h2><p className="form-hint">{t("包含图表与证据，保留报告原文。")}</p>
    <div className="form-grid"><label className="field">{t("导出格式")}<select value={format} onChange={e => { setFormat(e.target.value); setKey(crypto.randomUUID()); }}><option value="pdf">{t("PDF · 分享与打印")}</option><option value="html">{t("HTML · 离线查看")}</option><option value="markdown">{t("Markdown · 图表与证据包")}</option></select></label><button className="primary" disabled={create.isPending} onClick={() => create.mutate()}>{t("生成导出")}</button></div>
    {(create.error || list.error) && <p role="alert" className="error-notice">{message((create.error ?? list.error)?.message)}</p>}
    <div className="export-list">{list.data?.map(row => <div key={row.id}><strong>{row.format.toUpperCase()}</strong><span>{({ queued: t("生成中"), ready: t("可下载"), failed: t("生成失败"), expired: t("已过期"), cancelled: t("已取消") })[row.status]}</span>{row.status === 'ready' && new Date(row.expires_at) > new Date() ? <a className="text-button" href={`/api/v1/exports/${row.id}/download`}>{t("下载")} {row.format.toUpperCase()}</a> : row.error_code ? <span>{row.error_code} {t("· 可重新生成")}</span> : null}<small>{t("有效至")} {new Date(row.expires_at).toLocaleString(locale())}</small></div>)}</div>
  </section>;
}
