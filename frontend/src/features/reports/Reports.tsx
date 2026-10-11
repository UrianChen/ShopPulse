import { t, useLanguage, locale, message } from '../../lib/i18n';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, BookOpen, FileBarChart2, LoaderCircle, Plus, Send, ShieldCheck, X } from 'lucide-react';
import { api } from '../../lib/api';
import { Contributions, Trend } from '../dashboard/Dashboard';
import type { Result } from '../dashboard/Dashboard';
import { changeText, formatMetric } from '../dashboard/format';
import type { Metric } from '../dashboard/format';
import '../imports/imports.css';
import './reports.css';
import { Exports } from './Exports';
import '../operations.css';

type Sentence = { text: string; evidence_refs: string[] };
type Evidence = { evidence_id: string; tool: string; result_hash: string; run_id: string };
type Finding = { id: string; title: string; observation: Sentence; hypotheses: string[]; limitations: string[]; evidence_refs: string[] };
type Recommendation = { action: string; priority: string; effort: string; verification_metric: string; suggested_review_window: string; evidence_refs?: string[]; rationale_finding_ids?: string[] };
type Content = { generation_mode: string; model_error_code?: string; summary: Sentence[]; metrics: Result;
  metric_cards: { key: string; label: string; metric: Metric; evidence_id: string }[]; snapshot: Record<string, unknown>;
  products: { sku: string | null; product_name: string; current: { metrics: Record<string, Metric> } }[];
  anomalies: { findings: { code: string; values: unknown; limitation: string }[]; checks: { code: string; state: string; limitation: string }[] };
  findings: Finding[]; recommendations: Recommendation[]; limitations: string[]; warnings: string[]; evidence_index: Evidence[] };
type Report = { id: string; title: string; status: string; revision: number; series_id: string; parent_id: string | null;
  dataset_id: string; model_config_id: string | null; generation_mode: string | null; created_at: string; error_code: string | null;
  query: Result['query']; rules: Record<string, number>; content: Content | null };
type Version = { id: string; name: string; snapshot: { config: { options: { coverage_start: string; coverage_end_exclusive: string } } } };
type Model = { id: string; name: string; is_default: boolean; capabilities: { usable: boolean } | null };
type Message = { id: string; sequence: number; question: string; status: string; answer: { generation_mode: string; message: string; summary: Sentence[];
  analysis: { findings: Finding[]; recommendations: Recommendation[] } | null; limitations: string[]; error_code: string | null; new_analysis_required: boolean; evidence_index: Evidence[] } | null };
const done = ['ready', 'ready_with_warnings', 'failed'];
const modes: Record<string, string> = { deterministic: '确定性摘要', native_tools: '模型辅助 · 原生工具', restricted_json: '模型辅助 · 受限 JSON', narrative: '模型辅助 · 固定分析流程' };
const states: Record<string, string> = { queued: '等待执行', computing: '计算指标', analyzing: '分析与校验中', ready: '已完成', ready_with_warnings: '已完成 · 请查看限制', failed: '执行失败', running: '正在回答' };
const ruleNames: Record<string, string> = { SALES_CHANGE: '净销售额波动', HIGH_REFUND: '退款占比偏高', MARGIN_DROP: '毛利率下降', NEGATIVE_PROFIT: '负毛利商品', CONCENTRATION: '销售集中', DAILY_MAD: '日销售离群' };
const toolNames: Record<string, string> = { get_data_quality: '数据质量检查', calculate_metrics: '经营指标计算', get_sales_trend: '销售趋势', rank_products: '商品排行', compare_periods: '周期比较', decompose_sales_change: '销售贡献分解', detect_anomalies: '确定性异常检测' };
const metricNames: Record<string, string> = { net_sales: '净销售额', gross_profit: '商品毛利', refund_amount_rate: '累计退款占比', paid_orders: '支付订单量' };
const qualityNames: Record<string, string> = { SMALL_SAMPLE: '本期少于二十单，变化仅供观察', INCOMPLETE_COVERAGE: '本期数据覆盖不完整', COMPARISON_INCOMPLETE: '比较期数据覆盖不完整', COST_MISSING: '部分商品缺少成本，整体毛利不可用', RESTOCK_ESTIMATED: '退款回库未知，毛利为估算', REFUND_UNKNOWN: '累计退款未知，净值不可用', REFUND_ALLOCATED: '退款经过分摊，相关商品净值为估算' };
function day(value: string, offset: number) { const date = new Date(value.slice(0, 10) + 'T12:00:00Z'); date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0, 10); }
function ErrorBox({ error }: { error: Error | null }) {
  useLanguage(); return error && <div className="error-notice" role="alert">{message(error.message)}</div>; }

export function ReportList() {
  useLanguage();
  const [offset, setOffset] = useState(0);
  const list = useQuery({ queryKey: ['reports', offset], queryFn: () => api<{ total: number; items: Report[] }>(`/reports?offset=${offset}`),
    refetchInterval: q => q.state.data?.items.some(r => !done.includes(r.status)) ? 2000 : false });
  return <div className="reports"><section className="page-heading"><div><h1>{t("智能周报")}</h1><p>{t("查看分析，追溯依据。")}</p></div><Link className="primary" to="/reports/new"><Plus size={16} />{t("生成周报")}</Link></section>
    
    <ErrorBox error={list.error} />
    {!list.data?.total ? <section className="panel report-empty"><BookOpen size={32} /><h2>{list.isPending ? t("正在读取报告…") : t("从第一份经营周报开始")}</h2><p>{t("选择订单数据与分析周期。")}</p><Link className="primary" to="/reports/new">{t("生成第一份周报")}<ArrowRight size={15} /></Link></section> : <section className="report-list">{list.data.items.map(r => <Link to={`/reports/${r.id}`} className="panel report-list-item" key={r.id}><span className="tile-icon"><FileBarChart2 size={23} /></span><div><h2>{r.title}</h2><p>{r.query.start} {t("至")}{day(r.query.end_exclusive, -1)} {t("· 修订")} {r.revision} · {new Date(r.created_at).toLocaleString(locale())}</p><small>{t(modes[r.generation_mode ?? ''] ?? "准备分析")} · {t(states[r.status])}</small></div><ArrowRight size={18} /></Link>)}</section>}
    {list.data && list.data.total > 20 && <div className="pagination"><button className="secondary" disabled={!offset} onClick={() => setOffset(offset - 20)}>{t("上一页")}</button><span>{t("共")}{list.data.total} {t("份报告")}</span><button className="secondary" disabled={offset + 20 >= list.data.total} onClick={() => setOffset(offset + 20)}>{t("下一页")}</button></div>}
  </div>;
}

export function NewReport() {
  useLanguage();
  const [params] = useSearchParams();
  const parentId = params.get('parent');
  const parent = useQuery({ queryKey: ['report-parent', parentId], enabled: !!parentId, queryFn: () => api<Report>(`/reports/${parentId}`) });
  const versions = useQuery({ queryKey: ['datasets'], queryFn: () => api<Version[]>('/datasets') });
  const models = useQuery({ queryKey: ['model-configs'], queryFn: () => api<Model[]>('/model-configs') });
  const parentDataset = useQuery({ queryKey: ['report-parent-dataset', parent.data?.dataset_id], enabled: !!parent.data,
    queryFn: () => api<Version>(`/datasets/${parent.data!.dataset_id}`) });
  if (versions.isPending || models.isPending || (parentId && (parent.isPending || parentDataset.isPending))) return <p>{t("正在读取已发布数据…")}</p>;
  if (versions.error || models.error || parent.error || parentDataset.error) return <ErrorBox error={versions.error ?? models.error ?? parent.error ?? parentDataset.error} />;
  if (!versions.data?.length) return <section className="panel report-empty"><h1>{t("先准备一份订单数据")}</h1><p>{t("周报使用数据中心已发布的版本。")}</p><Link className="primary" to="/data">{t("前往数据中心")}</Link></section>;
  const choices = parentDataset.data && !versions.data.some(v => v.id === parentDataset.data.id)
    ? [parentDataset.data, ...versions.data] : versions.data;
  return <ReportForm versions={choices} models={models.data ?? []} parent={parent.data} />;
}

function ReportForm({ versions, models, parent }: { versions: Version[]; models: Model[]; parent?: Report }) {
  useLanguage();
  const navigate = useNavigate();
  const first = versions.find(v => v.id === parent?.dataset_id) ?? versions[0];
  const end = first.snapshot.config.options.coverage_end_exclusive.slice(0, 10);
  const [title, setTitle] = useState(parent?.title ?? t("店铺经营周报"));
  const [dataset, setDataset] = useState(first.id);
  const [start, setStart] = useState(parent?.query.start ?? day(end, -7));
  const [last, setLast] = useState(parent ? day(parent.query.end_exclusive, -1) : day(end, -1));
  const [comparison, setComparison] = useState(parent?.query.comparison ?? 'previous');
  const [compareStart, setCompareStart] = useState(parent?.query.compare_start ?? '');
  const [compareLast, setCompareLast] = useState(parent?.query.compare_end_exclusive ? day(parent.query.compare_end_exclusive, -1) : '');
  const [skus, setSkus] = useState(parent?.query.skus.join(', ') ?? '');
  const [model, setModel] = useState(parent ? parent.model_config_id ?? '' : models.find(m => m.is_default)?.id ?? '');
  const [minOrders, setMinOrders] = useState(parent?.rules.min_orders ?? 20);
  const [key, setKey] = useState({ body: '', value: crypto.randomUUID() });
  const create = useMutation({ mutationFn: (body: string) => {
    const token = key.body === body ? key.value : crypto.randomUUID(); setKey({ body, value: token });
    return api<Report>('/reports', { method: 'POST', headers: { 'Idempotency-Key': token }, body });
  }, onSuccess: r => navigate(`/reports/${r.id}`) });
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(JSON.stringify({ title, query: { dataset_id: dataset, start, end_exclusive: day(last, 1), comparison,
      compare_start: comparison === 'custom' ? compareStart : null, compare_end_exclusive: comparison === 'custom' ? day(compareLast, 1) : null,
      skus: skus.split(/[,，]/).map(s => s.trim()).filter(Boolean), granularity: 'day' }, model_config_id: model || null, parent_id: parent?.id ?? null,
      rules: { ...(parent?.rules ?? {}), min_orders: minOrders } }));
  }
  return <div className="reports"><Link className="back-link" to="/reports"><ArrowLeft size={15} />{t("返回周报中心")}</Link><section className="page-heading"><div><h1>{parent ? t("创建报告修订") : t("生成经营周报")}</h1><p>{parent ? t("保留原报告，生成新修订。") : t("选择数据与周期，模型可选。")}</p></div></section>
    <section className="panel report-form"><form onSubmit={submit}><fieldset disabled={create.isPending}><label className="field">{t("报告标题")}<input required maxLength={150} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label className="field">{t("订单数据版本")}<select value={dataset} onChange={e => setDataset(e.target.value)}>{versions.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id.slice(0, 8)}</option>)}</select></label>
      <div className="form-grid"><label className="field">{t("本期开始日期")}<input type="date" required value={start} onChange={e => setStart(e.target.value)} /></label><label className="field">{t("本期结束日期（含当日）")}<input type="date" required min={start} value={last} onChange={e => setLast(e.target.value)} /></label></div>
      <label className="field">{t("比较周期")}<select value={comparison} onChange={e => setComparison(e.target.value)}><option value="previous">{t("上一等长周期")}</option><option value="custom">{t("自定义比较期")}</option><option value="none">{t("不比较")}</option></select></label>
      {comparison === 'custom' && <div className="form-grid"><label className="field">{t("比较开始日期")}<input type="date" required value={compareStart} onChange={e => setCompareStart(e.target.value)} /></label><label className="field">{t("比较结束日期（含当日）")}<input type="date" required min={compareStart} value={compareLast} onChange={e => setCompareLast(e.target.value)} /></label></div>}
      <label className="field">{t("SKU 范围")}<input value={skus} onChange={e => setSkus(e.target.value)} placeholder={t("留空分析全部商品；多个 SKU 用逗号分隔")} /></label>
      <label className="field">{t("分析模型")}<select value={model} onChange={e => setModel(e.target.value)}><option value="">{t("无需模型 · 确定性摘要")}</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}{m.capabilities?.usable ? '' : t("（未验证或不可用，将降级）")}</option>)}</select></label>
      <p className="form-hint">{t("使用模型可能产生费用，按已授权范围发送数据。")}<Link to="/settings/models">{t("管理模型")}</Link></p>
      <details className="report-rule-options"><summary>{t("异常规则与样本量")}</summary><label className="field">{t("两期最低订单量")}<input type="number" min={20} max={1000} required value={minOrders} onChange={e => setMinOrders(Number(e.target.value))} /></label><p>{t("默认检查销售变化 20%、退款占比 10%、毛利率下降 5 个百分点、负毛利、销售集中和日离群。阈值随报告冻结；样本不足会明确标注。")}</p></details>
      <ErrorBox error={create.error} /><div className="form-actions"><button className="primary">{create.isPending ? <LoaderCircle className="spin" size={16} /> : <FileBarChart2 size={16} />}{t("开始生成")}</button></div>
    </fieldset></form></section></div>;
}

function Sentences({ values, onEvidence }: { values: Sentence[]; onEvidence: (id: string) => void }) {
  useLanguage(); return <div className="report-sentences">{values.map((s, i) => <p key={i}>{s.text} {s.evidence_refs.map(id => <button className="evidence-link" key={id} onClick={() => onEvidence(id)}>{t("查看证据")}</button>)}</p>)}</div>; }
function Advice({ findings, recommendations, onEvidence }: { findings: Finding[]; recommendations: Recommendation[]; onEvidence: (id: string) => void }) {
  useLanguage(); return <>
  {findings.map(f => <div className="report-finding" key={f.id}><h3>{f.title}</h3><Sentences values={[f.observation]} onEvidence={onEvidence} />{f.hypotheses.map((h, i) => <p className="hypothesis" key={i}><b>{t("待验证假设")}</b>{h}</p>)}</div>)}
  <div className="report-advice">{recommendations.map((r, i) => <div key={i}><span className="subtle-badge">{({ high: t("优先核查"), medium: t("建议跟进"), low: t("持续观察") })[r.priority]}</span><p>{r.action}</p><small>{t("预计工作量：")}{({ small: t("小"), medium: t("中"), large: t("大") })[r.effort]} {t("· 验证指标：")}{t(metricNames[r.verification_metric] ?? r.verification_metric)} {t("· 建议复查：")}{r.suggested_review_window === 'next_month' ? t("下月") : t("下周")}</small>{[...new Set(r.evidence_refs ?? findings.filter(f => r.rationale_finding_ids?.includes(f.id)).flatMap(f => f.evidence_refs))].map(id => <button className="evidence-link" key={id} onClick={() => onEvidence(id)}>{t("查看依据")}</button>)}</div>)}</div>
  </>; }

export function ReportDetail() {
  const language = useLanguage();
  const { reportId } = useParams();
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (evidenceId) drawer.current?.showModal(); }, [evidenceId]);
  const report = useQuery({ queryKey: ['report', reportId], queryFn: () => api<Report>(`/reports/${reportId}`), refetchInterval: q => !done.includes(q.state.data?.status ?? '') ? 1500 : false });
  const evidence = useQuery({ queryKey: ['report-evidence', reportId, evidenceId], enabled: !!evidenceId, queryFn: () => api<Record<string, unknown>>(`/reports/${reportId}/evidence/${evidenceId}`) });
  const runs = useQuery({ queryKey: ['report-runs', reportId, report.data?.status], queryFn: () => api<{ id: string; status: string; steps: { phase: string; tool?: string }[]; usage: Record<string, number>; error_code: string | null }[]>(`/reports/${reportId}/runs`), refetchInterval: !done.includes(report.data?.status ?? '') ? 2000 : false });
  const r = report.data, c = r?.content;
  return <div className="reports"><Link className="back-link" to="/reports"><ArrowLeft size={15} />{t("返回周报中心")}</Link><ErrorBox error={report.error} />
    {r && <><section className="page-heading"><div><h1>{r.title}</h1><p>{r.query.start} {t("至")}{day(r.query.end_exclusive, -1)} {t("· 修订")} {r.revision} {t("· 数据版本")} {r.dataset_id.slice(0, 8)}</p></div><Link className="secondary" to={`/reports/new?parent=${r.id}`}>{t("创建新修订")}</Link></section>
      <div className="report-status" aria-live="polite"><ShieldCheck size={18} /><strong>{t(modes[c?.generation_mode ?? ''] ?? "正在准备报告")}</strong><span>{t(states[r.status])}</span>{!done.includes(r.status) && <LoaderCircle size={16} className="spin" />}</div>
      {c?.model_error_code && c.model_error_code !== 'NO_MODEL' && <div className="report-warning">{t("模型分析未通过或暂不可用（")}{c.model_error_code}{t("），当前保留确定性摘要。可检查模型配置后创建新修订。")}</div>}
      {r.status === 'failed' && <div role="alert" className="error-notice">{t("报告未完成：")}{r.error_code}{t("。可创建新修订重试。")}</div>}
      {c && language === 'en' && <p className="original-language-note">Report content is preserved in its original language.</p>}
      {c && <><section className="panel report-overview"><div className="panel-title"><div><h2>{t("经营概览")}</h2></div></div><Sentences values={c.summary} onEvidence={setEvidenceId} /></section>
        <section className="report-metrics">{c.metric_cards.slice(0, 6).map(card => <div className="panel" key={card.key} data-testid={`report-metric-${card.key}`}><span>{t(card.label)}</span><strong>{formatMetric(card.metric, c.metrics.currency, c.metrics.currency_exponent)}</strong><small>{card.metric.quality === 'estimated' ? t("估算 · ") : ''}{card.metric.value === null ? t("数据不足或分母为零") : changeText(c.metrics.comparison?.[card.key])}</small><button className="evidence-link" onClick={() => setEvidenceId(card.evidence_id)}>{t("计算依据")}</button></div>)}</section>
        <div className="report-charts"><Trend result={c.metrics} /><Contributions result={c.metrics} /></div>
        <section className="panel"><h2>{t("商品表现")}</h2><p className="form-hint">{t("净销售额前 10 名")}</p><div className="table-scroll"><table><thead><tr><th>{t("SKU / 商品")}</th><th>{t("净销售额")}</th><th>{t("商品毛利")}</th><th>{t("支付件数")}</th></tr></thead><tbody>{c.products.map((p, i) => <tr key={i}><td>{p.sku ?? t("未映射 SKU")}<small className="report-product-name">{p.product_name}</small></td>{['net_sales', 'gross_profit', 'paid_units'].map(k => <td key={k}>{formatMetric(p.current.metrics[k], c.metrics.currency, c.metrics.currency_exponent)}</td>)}</tr>)}</tbody></table></div></section>
        <section className="panel"><h2>{t("异常与数据限制")}</h2>{c.anomalies.findings.length ? c.anomalies.findings.map((f, i) => <div className="report-finding" key={i}><h3>{t(ruleNames[f.code])}</h3><p>{f.limitation}</p><details><summary>{t("查看阈值、实际值与样本")}</summary><pre>{JSON.stringify(f.values, null, 2)}</pre></details></div>) : <p className="form-hint">{t("未触发异常规则；请同时关注数据限制。")}</p>}
          <div className="rule-checks">{c.anomalies.checks.map(check => <p key={check.code}><strong>{t(ruleNames[check.code])}</strong><span>{({ clear: t("未触发"), triggered: t("已触发"), insufficient_data: t("样本或数据不足"), insufficient_baseline: t("历史基线不足") })[check.state]}</span></p>)}</div>
          {c.warnings.length > 0 && <p className="report-warning">{t("数据质量标记：")}{c.warnings.map(code => t(qualityNames[code] ?? code)).join('；')}{t("。请结合证据中的质量结果解释指标。")}</p>}
          <ul className="report-limitations">{c.limitations.map(l => <li key={l}>{l}</li>)}</ul></section>
        <section className="panel"><h2>{t("经营观察与行动建议")}</h2><p className="form-hint">{t("原因是待验证假设，建议需人工判断。")}</p><Advice findings={c.findings} recommendations={c.recommendations} onEvidence={setEvidenceId} /></section>
        <section className="panel"><h2>{t("证据附录")}</h2><div className="evidence-list">{c.evidence_index.map(ev => <button key={ev.evidence_id} onClick={() => setEvidenceId(ev.evidence_id)}><BookOpen size={15} /><strong>{t(toolNames[ev.tool])}</strong><span>{ev.evidence_id.slice(0, 8)}</span><ArrowRight size={14} /></button>)}</div><details className="report-snapshot"><summary>{t("冻结版本与指标口径")}</summary><pre>{JSON.stringify(c.snapshot, null, 2)}</pre></details></section>
        {done.includes(r.status) && <><Exports reportId={r.id} /><Questions reportId={r.id} onEvidence={setEvidenceId} /></>}
      </>}
      <section className="panel report-run"><h2>{t("运行记录")}</h2><ErrorBox error={runs.error} />{runs.data?.map(run => <details key={run.id}><summary>{run.id.slice(0, 8)} · {run.status} {run.error_code && `· ${run.error_code}`}</summary><p>{run.steps.map(s => s.tool ? `${s.phase}: ${s.tool}` : s.phase).join(' → ')}</p><pre>{JSON.stringify(run.usage, null, 2)}</pre></details>)}</section>
    </>}
    {evidenceId && <dialog ref={drawer} className="evidence-overlay" aria-label={t("计算证据")} onCancel={() => setEvidenceId(null)} onClick={e => { if (e.target === e.currentTarget) setEvidenceId(null); }}><section className="evidence-drawer" onClick={e => e.stopPropagation()}><div className="panel-title"><div><h2>{t("计算证据")}</h2><p>{evidenceId}</p></div><button className="icon-button" aria-label={t("关闭证据")} onClick={() => setEvidenceId(null)}><X size={20} /></button></div><ErrorBox error={evidence.error} />{evidence.isPending ? <p>{t("读取中…")}</p> : <pre>{JSON.stringify(evidence.data, null, 2)}</pre>}</section></dialog>}
  </div>;
}

function Questions({ reportId, onEvidence }: { reportId: string; onEvidence: (id: string) => void }) {
  useLanguage();
  const client = useQueryClient();
  const [question, setQuestion] = useState('');
  const [offset, setOffset] = useState(0);
  const [key, setKey] = useState(crypto.randomUUID());
  const messages = useQuery({ queryKey: ['report-messages', reportId, offset], queryFn: () => api<{ total: number; items: Message[] }>(`/reports/${reportId}/messages?offset=${offset}`),
    refetchInterval: q => q.state.data?.items.some(m => ['queued', 'running'].includes(m.status)) ? 1500 : false });
  const send = useMutation({ mutationFn: () => api(`/reports/${reportId}/messages`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ question }) }),
    onSuccess: () => { setQuestion(''); setKey(crypto.randomUUID()); setOffset(0); void client.invalidateQueries({ queryKey: ['report-messages', reportId] }); void client.invalidateQueries({ queryKey: ['report-runs', reportId] }); } });
  const busy = send.isPending || messages.data?.items.some(m => ['queued', 'running'].includes(m.status));
  return <section className="panel report-questions"><h2>{t("追问报告")}</h2><p className="form-hint">{t("可追问销售、退款、成本与商品；更换周期请新建报告。")}</p>
    <form onSubmit={e => { e.preventDefault(); send.mutate(); }}><label className="field">{t("你的问题")}<textarea required maxLength={2000} rows={3} value={question} onChange={e => { setQuestion(e.target.value); setKey(crypto.randomUUID()); }} placeholder={t("例如：这期退款需要关注什么？")} /></label><button className="primary" disabled={busy || !question.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Send size={15} />}{t("提交追问")}</button></form><ErrorBox error={send.error ?? messages.error} />
    <div className="question-list">{messages.data?.items.map(m => <article key={m.id}><h3>{m.question}</h3><span className="import-state">{t(states[m.status])}</span>{m.answer && <><p className="form-hint">{t(modes[m.answer.generation_mode])}{m.answer.error_code && ` · ${m.answer.error_code}`}</p><p>{message(m.answer.message)}</p><Sentences values={m.answer.summary} onEvidence={onEvidence} />{m.answer.analysis && <Advice findings={m.answer.analysis.findings} recommendations={m.answer.analysis.recommendations} onEvidence={onEvidence} />}{m.answer.new_analysis_required && <Link className="text-button" to={`/reports/new?parent=${reportId}`}>{t("选择范围并创建新分析")}</Link>}</>}{m.status === 'failed' && <p className="report-warning">{t("本次追问未完成，原报告保持不变。可以重新提交。")}</p>}</article>)}</div>
    {messages.data && messages.data.total > 20 && <div className="pagination"><button className="secondary" disabled={!offset} onClick={() => setOffset(offset - 20)}>{t("较新追问")}</button><button className="secondary" disabled={offset + 20 >= messages.data.total} onClick={() => setOffset(offset + 20)}>{t("较早追问")}</button></div>}
  </section>;
}
