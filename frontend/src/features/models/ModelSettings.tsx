import { t, useLanguage, locale, message } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleX, KeyRound, LoaderCircle, Plus, Server, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../../lib/api';
import '../imports/imports.css';
import './models.css';

type Stage = { ok: boolean; code: string; message: string; http_status?: number };
type Capabilities = { usable: boolean; strategy: string; stages: Record<string, Stage>; requests?: number; protocol?: string };
type Protocol = 'openai_chat' | 'openai_responses' | 'anthropic_messages';
type ModelConfig = {
  id: string; name: string; base_url: string; model_name: string; protocol: Protocol; revision: number;
  is_default: boolean; has_api_key: boolean; timeout_seconds: number;
  product_name_mode: 'sku_only' | 'include_names';
  token_limit_parameter: 'none' | 'max_tokens' | 'max_completion_tokens';
  capabilities: Capabilities | null; tested_at: string | null;
  test_status: string | null; test_error_code: string | null; consent_current: boolean;
};
const strategies: Record<string, string> = {
  native_tools: '原生工具调用', restricted_json: '受限 JSON 模式', narrative: '固定流程叙述', unavailable: '连接不可用',
};
const stages: Record<string, string> = { basic: '基础连接', tools: '工具调用与回传', json: 'JSON 模式', json_schema: '结构化输出（JSON Schema）', text_json: '文本 JSON 校验' };
const protocols: Record<Protocol, { label: string; hint: string; placeholder: string }> = {
  openai_chat: { label: 'OpenAI 兼容 · Chat Completions', hint: '填写 API 前缀（如 /v1），无需添加 /chat/completions。', placeholder: 'https://provider.example/v1' },
  openai_responses: { label: 'OpenAI Responses', hint: '填写 API 前缀（如 /v1），无需添加 /responses。', placeholder: 'https://api.openai.com/v1' },
  anthropic_messages: { label: 'Anthropic Messages', hint: '填写 API 前缀（如 /v1），无需添加 /messages；连接测试会探测工具调用和结构化输出。', placeholder: 'https://api.anthropic.com/v1' },
};
const empty = { name: '', base_url: '', model_name: '', protocol: 'openai_chat' as Protocol, timeout_seconds: 45, is_default: false,
  product_name_mode: 'sku_only' as ModelConfig['product_name_mode'], token_limit_parameter: 'none' as ModelConfig['token_limit_parameter'] };
function originOf(value: string) { try { return new URL(value).origin; } catch { return t("填写 API 根地址后显示"); } }

function ConfigForm({ item, onDone, onCancel }: { item?: ModelConfig; onDone: () => void; onCancel: () => void }) {
  useLanguage();
  const [form, setForm] = useState(item ? { name: item.name, base_url: item.base_url, model_name: item.model_name, protocol: item.protocol ?? 'openai_chat',
    timeout_seconds: item.timeout_seconds, is_default: item.is_default, product_name_mode: item.product_name_mode,
    token_limit_parameter: item.token_limit_parameter } : empty);
  // Never put secrets in query/mutation caches, URLs or browser storage.
  const [key, setKey] = useState('');
  const [clear, setClear] = useState(false);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  function change<K extends keyof typeof form>(field: K, value: typeof form[K]) {
    setForm(previous => ({ ...previous, [field]: value }));
    if (field === 'base_url' || field === 'product_name_mode' || field === 'protocol') setConsent(false);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setPending(true); setError('');
    const body = JSON.stringify({ ...form, consent, ...(item ? { revision: item.revision } : {}),
      ...(key ? { api_key: key } : {}), ...(clear ? { clear_api_key: true } : {}) });
    setKey('');
    try { await api(`/model-configs${item ? `/${item.id}` : ''}`, { method: item ? 'PATCH' : 'POST', body }); onDone(); }
    catch (error) { setError(error instanceof Error ? error.message : t("保存失败，请重试。")); }
    finally { setPending(false); }
  }
  return <section className="panel model-editor"><div className="panel-title"><div><h2>{item ? t("编辑模型配置") : t("添加模型配置")}</h2>
    </div><KeyRound size={21} /></div>
    <form onSubmit={save}><fieldset disabled={pending}>
      <div className="form-grid">
        <label className="field">{t("配置名称")}<input required maxLength={100} value={form.name} onChange={e => change('name', e.target.value)} placeholder={t("例如：经营分析模型")} /></label>
        <label className="field">{t("模型名称")}<input required maxLength={200} value={form.model_name} onChange={e => change('model_name', e.target.value)} placeholder={t("服务提供方给出的模型 ID")} /></label>
      </div>
      <label className="field">{t("接口协议")}<select value={form.protocol} onChange={e => change('protocol', e.target.value as Protocol)}>{(Object.keys(protocols) as Protocol[]).map(key => <option key={key} value={key}>{t(protocols[key].label)}</option>)}</select></label>
      <label className="field">{t("API 根地址")}<input required type="url" maxLength={500} value={form.base_url} onChange={e => change('base_url', e.target.value)} placeholder={protocols[form.protocol].placeholder} /></label>
      <p className="form-hint">{t(protocols[form.protocol].hint)}</p>
      <label className="field">API Key<input type="password" autoComplete="new-password" maxLength={4096} value={key} disabled={clear} onChange={e => setKey(e.target.value)} placeholder={item?.has_api_key ? t("已保存密钥，留空保留；输入新值替换") : t("可选，无认证服务可留空")} /></label>
      <p className="form-hint">{t("密钥在后端加密保存，不会回显。")}</p>
      {item?.has_api_key && <label className="check-field"><input type="checkbox" checked={clear} onChange={e => { setClear(e.target.checked); setKey(''); }} />{t("清除已保存的 API Key")}</label>}
      <details className="advanced-settings"><summary>{t("高级设置")}</summary>      <div className="form-grid">
        <label className="field">{t("请求超时（秒）")}<input type="number" min={5} max={300} required value={form.timeout_seconds} onChange={e => change('timeout_seconds', Number(e.target.value))} /></label>
        <label className="field">{t("输出长度参数")}<select value={form.token_limit_parameter} onChange={e => change('token_limit_parameter', e.target.value as ModelConfig['token_limit_parameter'])}><option value="none">{t("不发送（兼容优先）")}</option><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
      </div>
      <p className="form-hint">{t("仅在服务支持时设置长度参数。")}</p>
</details>
      <div className="model-consent"><ShieldCheck size={21} /><div><strong>{t("确认数据发送范围")}</strong>
        <p>{t("目标服务：")}<b>{originOf(form.base_url)}</b></p><p>{t("发送汇总指标、质量摘要、所选商品信息、追问原文、最近三轮回答和与报告周期重叠的商家备注，不发送原始订单。")}</p>
        <label className="field">{t("商品信息范围")}<select value={form.product_name_mode} onChange={e => change('product_name_mode', e.target.value as ModelConfig['product_name_mode'])}><option value="sku_only">{t("仅 SKU（默认）")}</option><option value="include_names">{t("SKU 与商品名称")}</option></select></label>
        <label className="check-field"><input required type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />{t("我同意向该服务发送上述数据。")}</label>
      </div></div>
      <label className="check-field"><input type="checkbox" checked={form.is_default} onChange={e => change('is_default', e.target.checked)} />{t("设为默认模型")}</label>
      {error && <div className="error-notice" role="alert">{message(error)}</div>}
      <div className="form-actions"><button className="primary" disabled={!consent || pending}>{pending && <LoaderCircle size={16} className="spin" />}{t("保存配置")}</button><button type="button" className="secondary" onClick={onCancel}>{t("取消")}</button></div>
    </fieldset></form>
  </section>;
}

function ConsentUpgrade({ item, onRefresh }: { item: ModelConfig; onRefresh: () => void }) {
  useLanguage();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function confirm() {
    setPending(true); setError('');
    try { await api(`/model-configs/${item.id}/consent`, { method: 'POST' }); onRefresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : t("操作失败。")); }
    finally { setPending(false); }
  }
  return <div className="model-consent consent-upgrade" role="status"><ShieldCheck size={21} /><div>
    <strong>{t("授权范围需要更新")}</strong>
    <p>{t("此配置在 1.x 版本确认授权，模型看不到追问原文和商家备注，追问时只收到问题主题。")}</p>
    <p>{t("确认后将向")}<b>{originOf(item.base_url)}</b>{t("发送汇总指标、质量摘要、所选商品信息、追问原文、最近三轮回答和与报告周期重叠的商家备注，不发送原始订单。服务地址、密钥和连接测试结果保持不变。")}</p>
    {error && <div className="error-notice" role="alert">{message(error)}</div>}
    <button type="button" className="primary" disabled={pending} onClick={() => void confirm()}>{pending && <LoaderCircle size={16} className="spin" />}{t("确认新的授权范围")}</button>
  </div></div>;
}

function ModelCard({ item, onEdit, onRefresh }: { item: ModelConfig; onEdit: () => void; onRefresh: () => void }) {
  useLanguage();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const busy = pending || item.test_status === 'queued' || item.test_status === 'running';
  async function action(kind: 'test' | 'delete') {
    setPending(true); setError('');
    try { await api(`/model-configs/${item.id}${kind === 'test' ? '/test' : ''}`, { method: kind === 'test' ? 'POST' : 'DELETE' }); onRefresh(); }
    catch (error) { setError(error instanceof Error ? error.message : t("操作失败。")); }
    finally { setPending(false); }
  }
  return <article className="panel model-card" aria-label={item.name}>
    <div className="model-card-title"><span className="tile-icon"><Server size={21} /></span><div><h2>{item.name}</h2><p>{item.model_name}</p></div>{item.is_default && <span className="subtle-badge">{t("默认模型")}</span>}</div>
    <p className="model-url">{item.base_url}</p>
    {!item.consent_current && <ConsentUpgrade item={item} onRefresh={onRefresh} />}
    <div className="model-meta"><span><KeyRound size={13} />{item.has_api_key ? t("密钥已保存") : t("未设置密钥")}</span><span>{t(protocols[item.protocol ?? 'openai_chat'].label)}</span><span>{t("版本")} {item.revision}</span><span>{item.product_name_mode === 'sku_only' ? t("仅发送 SKU") : t("包含商品名称")}</span></div>
    <div className={`model-result ${item.capabilities?.usable ? 'usable' : ''}`} aria-live="polite">
      <strong>{busy ? <><LoaderCircle size={15} className="spin" />{t("连接测试中…")}</> : item.capabilities ? <>{item.capabilities.usable ? <CheckCircle2 size={15} /> : <CircleX size={15} />}{t(strategies[item.capabilities.strategy])}</> : item.test_status === 'failed' ? t("测试作业失败，可重新测试") : t("尚未测试连接")}</strong>
      {item.capabilities && <><details className="capability-details" open={!item.capabilities.usable}><summary>{t("测试详情")}</summary><div className="capability-list">{Object.entries(item.capabilities.stages).map(([name, result]) => <div key={name}><span>{t(stages[name])}</span><b className={result.ok ? 'passed' : 'limited'}>{result.ok ? t("通过") : result.code === 'UNSUPPORTED_REQUEST' ? t("不支持") : t("未通过")}</b>{!result.ok && <p>{message(result.message)}{result.http_status && `（HTTP ${result.http_status}）`}</p>}</div>)}</div>
        
        <small>{t("测试于")} {item.tested_at ? new Date(item.tested_at).toLocaleString(locale()) : '—'} · {item.capabilities.requests ?? '—'} {t("次请求")}</small></details></>}
      {item.test_status === 'failed' && !item.capabilities && <p>{item.test_error_code} {t("· 请确认 Worker 正常运行后重试。")}</p>}
      {busy && <p>{t("使用合成内容测试，最长约 90 秒。")}</p>}
    </div>
    <p className="form-hint">{t("点击测试将调用所填服务，可能产生少量模型费用。")}</p>
    {error && <div className="error-notice" role="alert">{message(error)}</div>}
    <div className="form-actions"><button className="primary" disabled={busy} onClick={() => void action('test')}>{t("测试连接")}</button><button className="secondary" disabled={busy} onClick={onEdit}>{t("编辑")}</button><button className="text-button" disabled={busy} onClick={() => setConfirmDelete(!confirmDelete)}>{t("删除")}</button></div>
    {confirmDelete && <div className="delete-confirm"><p>{t("删除「")}{item.name}{t("」及已保存的密钥？此操作无法撤销。")}</p><button className="secondary" disabled={busy} onClick={() => void action('delete')}>{t("确认删除")}</button><button className="text-button" onClick={() => setConfirmDelete(false)}>{t("保留配置")}</button></div>}
  </article>;
}

export function ModelSettings() {
  useLanguage();
  const client = useQueryClient();
  const [editing, setEditing] = useState<ModelConfig | 'new' | null>(null);
  const configs = useQuery({ queryKey: ['model-configs'], queryFn: () => api<ModelConfig[]>('/model-configs'),
    refetchInterval: query => query.state.data?.some(item => ['queued', 'running'].includes(item.test_status ?? '')) ? 1500 : false });
  function refresh() { void client.invalidateQueries({ queryKey: ['model-configs'] }); }
  return <div className="model-settings"><section className="page-heading"><div><h1>{t("模型设置")}</h1><p>{t("连接 OpenAI 兼容、OpenAI Responses 或 Anthropic Messages 模型服务。")}</p></div><button className="primary" disabled={!!editing} onClick={() => setEditing('new')}><Plus size={16} />{t("添加模型")}</button></section>
    
    {!!configs.data?.some(item => !item.consent_current) && <div className="report-warning" role="status">{t("有 {0} 个模型配置仍使用 1.x 的授权范围，确认后追问与商家备注才会发送给模型。", configs.data.filter(item => !item.consent_current).length)}</div>}
    {configs.error && <div role="alert" className="error-notice">{message(configs.error.message)}<button className="text-button" onClick={refresh}>{t("重新加载")}</button></div>}
    {editing && <ConfigForm key={editing === 'new' ? 'new' : editing.id} item={editing === 'new' ? undefined : editing} onDone={() => { setEditing(null); refresh(); }} onCancel={() => setEditing(null)} />}
    {configs.isPending && <p className="empty-copy">{t("正在读取配置…")}</p>}
    {!editing && configs.data?.length === 0 && <section className="panel model-empty"><Sparkles size={34} /><h2>{t("添加分析模型")}</h2><p>{t("支持 OpenAI 兼容、OpenAI Responses 与 Anthropic Messages 接口。")}</p><button className="primary" onClick={() => setEditing('new')}>{t("添加第一个模型")}</button></section>}
    <div className="models-grid">{configs.data?.map(item => <ModelCard key={item.id} item={item} onEdit={() => setEditing(item)} onRefresh={refresh} />)}</div>
  </div>;
}
