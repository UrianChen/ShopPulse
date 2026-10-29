import { t, useLanguage, locale, message, getLanguage } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { BellRing, CalendarClock, ClipboardCheck, LoaderCircle, NotebookPen, Play, Plus, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import '../imports/imports.css';
import './automation.css';

export type Evaluation = { state: string; reason: string | null; change_rate: string | null; report_id: string };
export type ActionItem = { id: string; report_id: string; text: string; verification_metric: string; review_window: string; priority: string; effort: string;
  status: string; note: string | null; evaluation: Evaluation | null; revision: number; report_title?: string | null };
type Schedule = { id: string; name: string; title: string; dataset_id: string | null; model_config_id: string | null; period_days: number; weekday: number; hour: number;
  timezone: string; enabled: boolean; language: string; has_webhook: boolean; webhook_format: string; last_report_id: string | null; last_run_at: string | null;
  next_run_at: string | null; last_status: string | null; next_period: { start: string; end_exclusive: string } | null; revision: number };
type Note = { id: string; start_date: string; end_exclusive: string; kind: string; text: string };
type Version = { id: string; name: string };
type Model = { id: string; name: string };

export const metricNames: Record<string, string> = { net_sales: '净销售额', gross_profit: '商品毛利', refund_amount_rate: '累计退款占比', paid_orders: '支付订单量' };
export const followupStates: Record<string, string> = { improved: '已改善', not_improved: '未改善', insufficient_data: '数据不足' };
const statusNames: Record<string, string> = { open: '待处理', done: '已完成', dismissed: '已忽略' };
const priorityNames: Record<string, string> = { high: '优先核查', medium: '建议跟进', low: '持续观察' };
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const formats: Record<string, string> = { generic: '通用 JSON', slack: 'Slack', feishu: '飞书', wecom: '企业微信', dingtalk: '钉钉' };
export const noteKinds: Record<string, string> = { promotion: '促销', holiday: '节假日', stockout: '缺货', pricing: '调价', other: '其他' };
const scheduleStates: Record<string, string> = { CREATED: '已生成报告', NO_NEW_DATA: '没有新数据，已跳过', NO_DATASET: '没有可用数据版本', ALREADY_CREATED: '本期已生成',
  NOTIFIED: '已推送通知', FAILED: '执行失败', DATASET_DELETED: '数据版本已删除，已停用', BUSY: '正在执行', NOT_DUE: '未到执行时间' };
function day(value: string, offset: number) { const date = new Date(value.slice(0, 10) + 'T12:00:00Z'); date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0, 10); }
function stateText(value: string | null) {
  if (!value) return t('尚未执行');
  if (value.startsWith('NOTIFY_FAILED')) return `${t('推送失败')} · ${value.split(':')[1] ?? ''}`;
  return t(scheduleStates[value] ?? value);
}
function ErrorBox({ error }: { error: unknown }) {
  useLanguage(); return error ? <div className="error-notice" role="alert">{message(error instanceof Error ? error.message : String(error))}</div> : null; }

export function ActionRow({ item, onChanged, showReport = false }: { item: ActionItem; onChanged: () => void; showReport?: boolean }) {
  useLanguage();
  const [note, setNote] = useState(item.note ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function save(patch: { status?: string; note?: string }) {
    setPending(true); setError(null);
    try { await api(`/actions/${item.id}`, { method: 'PATCH', body: JSON.stringify({ revision: item.revision, ...patch }) }); onChanged(); }
    catch (failure) { setError(failure); } finally { setPending(false); }
  }
  return <div className={`action-row status-${item.status}`}>
    <div className="action-main"><span className="subtle-badge">{t(priorityNames[item.priority] ?? item.priority)}</span><p>{item.text}</p>
      <small>{t('验证指标：')}{t(metricNames[item.verification_metric] ?? item.verification_metric)}{item.evaluation && <> · {t('最近评估：')}<b className={`followup-${item.evaluation.state}`}>{t(followupStates[item.evaluation.state])}</b></>}
        {showReport && item.report_title && <> · <Link to={`/reports/${item.report_id}`}>{item.report_title}</Link></>}</small></div>
    <div className="action-controls">
      <label className="field">{t('状态')}<select value={item.status} disabled={pending} onChange={e => void save({ status: e.target.value })}>{Object.entries(statusNames).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label>
      <label className="field">{t('备注')}<input maxLength={500} value={note} disabled={pending} onChange={e => setNote(e.target.value)} placeholder={t('记录处理情况')} /></label>
      <button type="button" className="secondary" disabled={pending || note === (item.note ?? '')} onClick={() => void save({ note })}>{t('保存备注')}</button>
    </div>
    <ErrorBox error={error} />
  </div>;
}

function ScheduleForm({ item, versions, models, onDone, onCancel }: { item?: Schedule; versions: Version[]; models: Model[]; onDone: () => void; onCancel: () => void }) {
  useLanguage();
  const [form, setForm] = useState({ name: item?.name ?? '', title: item?.title ?? t('经营周报'), dataset_id: item?.dataset_id ?? '', model_config_id: item?.model_config_id ?? '',
    period_days: item?.period_days ?? 7, weekday: item?.weekday ?? 0, hour: item?.hour ?? 8, language: item?.language ?? getLanguage(),
    webhook_format: item?.webhook_format ?? 'generic', enabled: item?.enabled ?? true });
  const [webhook, setWebhook] = useState('');
  const [clearWebhook, setClearWebhook] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  function change<K extends keyof typeof form>(field: K, value: typeof form[K]) { setForm(previous => ({ ...previous, [field]: value })); }
  async function save(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    const body = { ...form, dataset_id: form.dataset_id || null, model_config_id: form.model_config_id || null,
      ...(webhook ? { webhook_url: webhook } : {}), ...(clearWebhook ? { clear_webhook: true } : {}), ...(item ? { revision: item.revision } : {}) };
    try { await api(`/schedules${item ? `/${item.id}` : ''}`, { method: item ? 'PATCH' : 'POST', body: JSON.stringify(body) }); setWebhook(''); onDone(); }
    catch (failure) { setError(failure); } finally { setPending(false); }
  }
  return <form className="panel automation-form" onSubmit={save}><h2>{item ? t('编辑定时周报') : t('新建定时周报')}</h2><fieldset disabled={pending}>
    <div className="form-grid"><label className="field">{t('任务名称')}<input required maxLength={100} value={form.name} onChange={e => change('name', e.target.value)} /></label>
      <label className="field">{t('报告标题')}<input required maxLength={100} value={form.title} onChange={e => change('title', e.target.value)} /></label></div>
    <div className="form-grid"><label className="field">{t('订单数据版本')}<select value={form.dataset_id} onChange={e => change('dataset_id', e.target.value)}><option value="">{t('始终使用最新版本')}</option>{versions.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id.slice(0, 8)}</option>)}</select></label>
      <label className="field">{t('分析模型')}<select value={form.model_config_id} onChange={e => change('model_config_id', e.target.value)}><option value="">{t('无需模型 · 确定性摘要')}</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label></div>
    <div className="form-grid four"><label className="field">{t('分析天数')}<input type="number" min={1} max={31} required value={form.period_days} onChange={e => change('period_days', Number(e.target.value))} /></label>
      <label className="field">{t('执行日')}<select value={form.weekday} onChange={e => change('weekday', Number(e.target.value))}>{weekdays.map((name, index) => <option key={name} value={index}>{t(name)}</option>)}</select></label>
      <label className="field">{t('执行时刻')}<select value={form.hour} onChange={e => change('hour', Number(e.target.value))}>{Array.from({ length: 24 }, (_, hour) => <option key={hour} value={hour}>{String(hour).padStart(2, '0')}:00</option>)}</select></label>
      <label className="field">{t('报告语言')}<select value={form.language} onChange={e => change('language', e.target.value)}><option value="zh">中文</option><option value="en">English</option></select></label></div>
    <p className="form-hint">{t('每次以数据覆盖截止日为终点，分析最近若干天并与上一等长周期比较；没有新数据时跳过。')}</p>
    <div className="form-grid"><label className="field">{t('通知地址（Webhook）')}<input type="url" autoComplete="off" maxLength={1000} value={webhook} disabled={clearWebhook} onChange={e => setWebhook(e.target.value)} placeholder={item?.has_webhook ? t('已保存地址，留空保留；输入新值替换') : 'https://'} /></label>
      <label className="field">{t('消息格式')}<select value={form.webhook_format} onChange={e => change('webhook_format', e.target.value)}>{Object.entries(formats).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label></div>
    <p className="form-hint">{t('地址加密保存且不回显；仅允许公网 HTTPS，内网地址需部署者加入白名单。')}</p>
    {item?.has_webhook && <label className="check-field"><input type="checkbox" checked={clearWebhook} onChange={e => { setClearWebhook(e.target.checked); setWebhook(''); }} />{t('清除已保存的通知地址')}</label>}
    <label className="check-field"><input type="checkbox" checked={form.enabled} onChange={e => change('enabled', e.target.checked)} />{t('启用')}</label>
    <ErrorBox error={error} />
    <div className="form-actions"><button className="primary">{pending && <LoaderCircle size={16} className="spin" />}{t('保存')}</button><button type="button" className="secondary" onClick={onCancel}>{t('取消')}</button></div>
  </fieldset></form>;
}

function Schedules() {
  useLanguage();
  const client = useQueryClient();
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<unknown>(null);
  const schedules = useQuery({ queryKey: ['schedules'], queryFn: () => api<Schedule[]>('/schedules') });
  const versions = useQuery({ queryKey: ['datasets'], queryFn: () => api<Version[]>('/datasets') });
  const models = useQuery({ queryKey: ['model-configs'], queryFn: () => api<Model[]>('/model-configs') });
  function refresh() { void client.invalidateQueries({ queryKey: ['schedules'] }); }
  async function run(item: Schedule) {
    setError(null); setNotice('');
    try { const result = await api<{ status: string; report_id: string | null }>(`/schedules/${item.id}/run`, { method: 'POST' }); setNotice(stateText(result.status)); refresh(); }
    catch (failure) { setError(failure); }
  }
  async function remove(item: Schedule) {
    setError(null);
    try { await api(`/schedules/${item.id}`, { method: 'DELETE' }); refresh(); } catch (failure) { setError(failure); }
  }
  return <section className="automation-section"><div className="panel-title"><div><h2><CalendarClock size={19} />{t('定时周报')}</h2><p className="form-hint">{t('按计划自动生成新一期报告，并可推送到群机器人。')}</p></div>
    <button className="primary" disabled={!!editing} onClick={() => setEditing('new')}><Plus size={16} />{t('新建定时周报')}</button></div>
    <ErrorBox error={schedules.error ?? error} />{notice && <p className="report-warning" role="status">{notice}</p>}
    {editing && <ScheduleForm key={editing === 'new' ? 'new' : editing.id} item={editing === 'new' ? undefined : editing} versions={versions.data ?? []} models={models.data ?? []} onDone={() => { setEditing(null); refresh(); }} onCancel={() => setEditing(null)} />}
    {schedules.data?.length === 0 && !editing && <p className="empty-copy">{t('还没有定时周报。')}</p>}
    <div className="schedule-list">{schedules.data?.map(item => <article className="panel schedule-card" key={item.id}>
      <div><h3>{item.name}{!item.enabled && <span className="subtle-badge">{t('已停用')}</span>}{item.has_webhook && <span className="subtle-badge"><BellRing size={12} />{t(formats[item.webhook_format])}</span>}</h3>
        <p>{t('每{0} {1}:00（{2}）', t(weekdays[item.weekday]), String(item.hour).padStart(2, '0'), item.timezone)} · {t('分析最近 {0} 天', item.period_days)}</p>
        <small>{t('下次执行：')}{item.next_run_at ? new Date(item.next_run_at).toLocaleString(locale()) : '—'} · {t('上次结果：')}{stateText(item.last_status)}
          {item.last_report_id && <> · <Link to={`/reports/${item.last_report_id}`}>{t('查看最近报告')}</Link></>}</small>
        {item.next_period && <small>{t('下一期范围：')}{item.next_period.start} {t('至')} {day(item.next_period.end_exclusive, -1)}</small>}</div>
      <div className="form-actions"><button className="secondary" onClick={() => void run(item)}><Play size={15} />{t('立即运行')}</button><button className="secondary" disabled={!!editing} onClick={() => setEditing(item)}>{t('编辑')}</button><button className="text-button" onClick={() => void remove(item)}><Trash2 size={15} />{t('删除')}</button></div>
    </article>)}</div>
  </section>;
}

function Notes() {
  useLanguage();
  const client = useQueryClient();
  const notes = useQuery({ queryKey: ['notes'], queryFn: () => api<Note[]>('/notes') });
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ start: today, last: today, kind: 'promotion', text: '' });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  function refresh() { void client.invalidateQueries({ queryKey: ['notes'] }); }
  async function save(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    try { await api('/notes', { method: 'POST', body: JSON.stringify({ start_date: form.start, end_exclusive: day(form.last, 1), kind: form.kind, text: form.text }) }); setForm({ ...form, text: '' }); refresh(); }
    catch (failure) { setError(failure); } finally { setPending(false); }
  }
  async function remove(note: Note) {
    try { await api(`/notes/${note.id}`, { method: 'DELETE' }); refresh(); } catch (failure) { setError(failure); }
  }
  return <section className="automation-section"><div className="panel-title"><div><h2><NotebookPen size={19} />{t('商家备注')}</h2><p className="form-hint">{t('记录促销、节假日、缺货或调价。覆盖报告周期的备注会作为分析背景，模型可在假设中引用。')}</p></div></div>
    <form className="panel automation-form" onSubmit={save}><fieldset disabled={pending}><div className="form-grid four">
      <label className="field">{t('开始日期')}<input type="date" required value={form.start} onChange={e => setForm({ ...form, start: e.target.value })} /></label>
      <label className="field">{t('结束日期（含当日）')}<input type="date" required min={form.start} value={form.last} onChange={e => setForm({ ...form, last: e.target.value })} /></label>
      <label className="field">{t('类型')}<select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>{Object.entries(noteKinds).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label>
      <label className="field">{t('内容')}<input required maxLength={300} value={form.text} onChange={e => setForm({ ...form, text: e.target.value })} placeholder={t('例如：国庆满减活动')} /></label></div>
      <ErrorBox error={error ?? notes.error} /><div className="form-actions"><button className="primary">{t('添加备注')}</button></div></fieldset></form>
    <ul className="note-list">{notes.data?.map(note => <li key={note.id}><span className="subtle-badge">{t(noteKinds[note.kind] ?? note.kind)}</span><span>{note.start_date} {t('至')} {day(note.end_exclusive, -1)}</span><span>{note.text}</span><button className="text-button" onClick={() => void remove(note)} aria-label={t('删除备注')}><Trash2 size={15} /></button></li>)}</ul>
    {notes.data?.length === 0 && <p className="empty-copy">{t('还没有备注。')}</p>}
  </section>;
}

function Actions() {
  useLanguage();
  const client = useQueryClient();
  const [status, setStatus] = useState('open');
  const actions = useQuery({ queryKey: ['actions', status], queryFn: () => api<{ total: number; items: ActionItem[] }>(`/actions?status=${status}&limit=50`) });
  return <section className="automation-section"><div className="panel-title"><div><h2><ClipboardCheck size={19} />{t('建议跟进')}</h2><p className="form-hint">{t('报告中的建议会成为行动项；之后的报告会用验证指标检查是否改善。')}</p></div>
    <label className="field compact">{t('状态')}<select value={status} onChange={e => setStatus(e.target.value)}><option value="open">{t('待处理')}</option><option value="done">{t('已完成')}</option><option value="dismissed">{t('已忽略')}</option><option value="all">{t('全部')}</option></select></label></div>
    <ErrorBox error={actions.error} />
    {actions.data?.items.length === 0 && <p className="empty-copy">{t('没有符合条件的行动项。')}</p>}
    {!!actions.data?.items.length && <div className="panel action-list">{actions.data.items.map(item => <ActionRow key={`${item.id}-${item.revision}`} item={item} showReport onChanged={() => void client.invalidateQueries({ queryKey: ['actions'] })} />)}</div>}
  </section>;
}

export function Automation() {
  useLanguage();
  return <div className="automation"><section className="page-heading"><div><h1>{t('自动化')}</h1><p>{t('定时生成周报，记录经营背景，跟进建议效果。')}</p></div></section>
    <Schedules /><Notes /><Actions /></div>;
}
