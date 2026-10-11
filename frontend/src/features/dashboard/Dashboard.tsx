import { locale, t, useLanguage, message } from '../../lib/i18n';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Activity, ArrowRight, CalendarDays, CheckCircle2, Database, Info, LoaderCircle, RefreshCw, SlidersHorizontal, TrendingUp, X } from 'lucide-react';
import { api } from '../../lib/api';
import { changeText, formatMetric, reasons } from './format';
import type { Change, Metric } from './format';
import './dashboard.css';

type Query = { dataset_id: string; start: string; end_exclusive: string; comparison: string; compare_start: string | null; compare_end_exclusive: string | null; skus: string[]; granularity: string };
type Version = { id: string; name: string; snapshot: { config: { options: { coverage_start: string; coverage_end_exclusive: string } } } };
type Period = { metrics: Record<string, Metric>; row_count: number; coverage_complete: boolean; quality: { missing_cost_rows: number; missing_cost_skus: number; missing_cost_paid_minor: string; estimated_restock_rows: number; estimated_restock_paid_minor: string } };
type Point = Period & { start: string; end_exclusive: string };
type Contribution = { sku: string | null; product_name: string; sales_contribution_minor: string };
export type Result = { dataset_id: string; currency: string; currency_exponent: number; timezone: string; source_as_of: string; engine_version: string; query: Query; periods: { current: string[]; previous: string[] | null }; current: Period; previous: Period | null; comparison: Record<string, Change> | null; matched_cost_subset: Period; trend: Point[]; warnings: string[]; excluded_rows: number; product_count: number; contributions: { available: boolean; total_minor: string | null; gainers: Contribution[]; decliners: Contribution[]; effects: { order_effect_minor: string; aov_effect_minor: string } | null } };
type Snapshot = { id: string; status: string; error_code: string | null; result: Result | null };
type Product = { sku: string | null; product_name: string; current: Period; previous: Period | null; comparison: Record<string, Change> | null; sales_contribution_minor: string | null };

const labels: Record<string, string> = { net_sales: '净销售额', paid_orders: '支付订单量', aov: '净客单价', gross_profit: '商品毛利', gross_sales: '退款前商品实付', refund_amount: '支付订单累计退款', gross_margin: '商品毛利率', paid_units: '支付件数', gross_aov: '实付客单价', net_cogs: '净商品成本', refund_amount_rate: '累计退款金额占比', refunded_order_rate: '发生退款订单占比', cost_line_coverage: '成本明细覆盖率', cost_amount_coverage: '成本实付金额覆盖率' };
const warnings: Record<string, string> = { INCOMPLETE_COVERAGE: '本期超出源文件确认的完整覆盖范围。当前仅显示已提供记录，不能视为完整周期经营数据。', COMPARISON_INCOMPLETE: '比较期覆盖不完整，已禁用增长率与贡献分解。', COST_MISSING: '存在成本缺失，整体商品毛利不可用；下方单独显示匹配子集。', RESTOCK_ESTIMATED: '部分回库数量未知，按不回转成本计算，毛利标记为估算。', REFUND_UNKNOWN: '累计退款未知，净销售额、净客单价和毛利不可用。', REFUND_ALLOCATED: '订单退款按明细实付分摊，商品相关净值标记为估算。', SMALL_SAMPLE: '本期订单少于 20 笔。可查看实际比例，不据此给出显著变化结论。' };
function day(value: string, offset: number) { const date = new Date(value.slice(0, 10) + 'T12:00:00Z'); if (Number.isNaN(date.getTime())) return ''; date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0, 10); }
function money(value: string | null, result: Result) { return formatMetric({ value, unit: 'minor_currency', quality: value === null ? 'unavailable' : 'confirmed', unavailable_reason: null }, result.currency, result.currency_exponent); }
function value(metric: Metric, result: Result) { return formatMetric(metric, result.currency, result.currency_exponent); }
function MetricValue({ metric, result }: { metric: Metric; result: Result }) {
  useLanguage(); return <><span>{value(metric, result)}</span>{metric.quality === 'estimated' && <small className="estimate">{t("估算")}</small>}{metric.value === null && <small className="unavailable-reason">{t(reasons[metric.unavailable_reason ?? ''] ?? "不可用")}</small>}</>; }

export function Trend({ result }: { result: Result }) {
  useLanguage();
  const [hover, setHover] = useState<number | null>(null);
  const [series, setSeries] = useState('net_sales');
  const points = result.trend;
  const nums = points.map(p => p.metrics[series].value === null ? null : Number(p.metrics[series].value));
  const values = nums.filter((n): n is number => n !== null);
  const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min;
  const x = (i: number) => 65 + i * 640 / Math.max(1, points.length - 1);
  const y = (n: number) => 215 - (n - min) / range * 165;
  let path = '', connected = false;
  nums.forEach((n, i) => { if (n === null) connected = false; else { path += `${connected ? 'L' : 'M'} ${x(i)} ${y(n)} `; connected = true; } });
  const selected = points[hover ?? points.length - 1];
  return <section className="panel trend-panel"><div className="panel-title"><div><h2>{t("经营趋势")}</h2><p>{result.query.granularity === 'day' ? t("按店铺自然日") : t("按周一至周日，边缘周按筛选范围")} {t("· 空缺数据不补零")}</p></div><select aria-label={t("趋势指标")} value={series} onChange={e => setSeries(e.target.value)}>{['net_sales', 'gross_sales', 'gross_profit', 'paid_orders'].map(k => <option value={k} key={k}>{t(labels[k])}</option>)}</select></div>
    <figure className="trend-figure"><svg viewBox="0 0 740 265" role="img" aria-label={t("{0}趋势图", t(labels[series]))}>
      {[0, 0.5, 1].map(f => { const n = min + range * f; return <g key={f}><line x1="65" x2="705" y1={y(n)} y2={y(n)} stroke="#e8eee8" strokeDasharray="4 4" /><text x="55" y={y(n) + 4} textAnchor="end" className="axis-label">{new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }).format(n / (series === 'paid_orders' ? 1 : 10 ** result.currency_exponent))}</text></g>; })}
      <path d={path} stroke="#426c4e" strokeWidth="2.5" fill="none" />
      {nums.map((n, i) => n === null ? null : <circle key={points[i].start} cx={x(i)} cy={y(n)} r={hover === i ? 5 : 3} fill="#648d54" tabIndex={0} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} aria-label={`${points[i].start} ${t(labels[series])} ${value(points[i].metrics[series], result)}`}><title>{points[i].start}：{value(points[i].metrics[series], result)}</title></circle>)}
      <text x="65" y="247" className="axis-label">{points[0]?.start}</text><text x="705" y="247" textAnchor="end" className="axis-label">{points.at(-1)?.start}</text>
    </svg><figcaption>{selected && <><span>{selected.start}{result.query.granularity === 'week' ? t(" 至 {0}", day(selected.end_exclusive, -1)) : ''}</span><strong>{t(labels[series])} <MetricValue metric={selected.metrics[series]} result={result} /></strong><span>{selected.coverage_complete ? t("完整覆盖") : t("覆盖不完整")}</span></>}</figcaption></figure>
  </section>;
}

export function Contributions({ result }: { result: Result }) {
  useLanguage();
  const c = result.contributions;
  const rows = [...c.gainers, ...c.decliners];
  const max = Math.max(1, ...rows.map(r => Math.abs(Number(r.sales_contribution_minor))));
  return <section className="panel contributions-panel"><div className="panel-title"><div><h2>{t("销售变化贡献")}</h2><p>{t("增减贡献前 5 名 · 合计")}{money(c.total_minor, result)}</p></div><TrendingUp size={20} /></div>
    {!c.available ? <p className="chart-empty">{t("需要两期完整且净销售可用的数据，才能比较商品贡献。")}</p> : rows.length ? <div className="contribution-list">{rows.map(r => <div className="contribution-row" key={r.sku ?? 'unmapped'}><div><span>{r.sku ?? t("未映射 SKU")}</span><strong>{money(r.sales_contribution_minor, result)}</strong></div><div className="contribution-track"><span className={Number(r.sales_contribution_minor) < 0 ? 'negative' : ''} style={{ width: `${Math.abs(Number(r.sales_contribution_minor)) / max * 100}%` }} /></div></div>)}</div> : <p className="chart-empty">{t("两期商品净销售额没有变化。")}</p>}
    {c.effects && <div className="effects"><span>{t("订单量效应")}<strong>{money(c.effects.order_effect_minor, result)}</strong></span><span>{t("客单价效应")}<strong>{money(c.effects.aov_effect_minor, result)}</strong></span><p>{t("描述性金额分解，不代表促销、价格或需求变化的因果结论。")}</p></div>}
  </section>;
}

export function Dashboard() {
  useLanguage();
  const [params, setParams] = useSearchParams();
  const versions = useQuery({ queryKey: ['datasets'], queryFn: () => api<Version[]>('/datasets') });
  const requestedVersion = params.get('dataset');
  const selectedVersion = useQuery({ queryKey: ['dashboard-version', requestedVersion], enabled: !!requestedVersion && !versions.data?.some(v => v.id === requestedVersion), queryFn: () => api<Version>(`/datasets/${requestedVersion}`) });
  const availableVersions = selectedVersion.data && !versions.data?.some(v => v.id === selectedVersion.data!.id) ? [...(versions.data ?? []), selectedVersion.data] : (versions.data ?? []);
  const [draft, setDraft] = useState<Query | null>(null);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [skuInput, setSkuInput] = useState('');
  const [sort, setSort] = useState('net_sales');
  const [direction, setDirection] = useState('desc');
  const [focus, setFocus] = useState('all');
  const [offset, setOffset] = useState(0);
  const active = useRef('');
  const [validationError, setValidationError] = useState('');
  const request = useMutation({ mutationFn: (q: Query) => api<Snapshot>('/metrics/query', { method: 'POST', body: JSON.stringify(q) }), onSuccess: (item, q) => { if (JSON.stringify(q) === active.current) setSnapshotId(item.id); } });
  const snapshot = useQuery({ queryKey: ['metrics', snapshotId], enabled: !!snapshotId, queryFn: () => api<Snapshot>(`/metrics/${snapshotId}`), refetchInterval: q => ['queued', 'running'].includes(q.state.data?.status ?? '') ? 1000 : false });
  const result = snapshot.data?.result;
  const products = useQuery({ queryKey: ['metric-products', snapshotId, sort, direction, focus, offset], enabled: !!result, queryFn: () => api<{ total: number; items: Product[] }>(`/metrics/${snapshotId}/products?sort=${sort}&direction=${direction}&focus=${focus}&offset=${offset}&limit=20`) });
  const choices = useQuery({ queryKey: ['sku-options', draft?.dataset_id, skuInput], enabled: !!draft?.dataset_id, queryFn: () => api<string[]>(`/datasets/${draft!.dataset_id}/skus?search=${encodeURIComponent(skuInput)}`) });
  function defaults(v: Version): Query {
    const o = v.snapshot.config.options, end = o.coverage_end_exclusive.slice(0, 10);
    return { dataset_id: v.id, start: day(end, -7) < o.coverage_start.slice(0, 10) ? o.coverage_start.slice(0, 10) : day(end, -7), end_exclusive: end, comparison: 'previous', compare_start: null, compare_end_exclusive: null, granularity: 'day', skus: [] };
  }
  function apply(q: Query) {
    if (!q.start || !q.end_exclusive || q.start >= q.end_exclusive || (q.comparison === 'custom' && (!q.compare_start || !q.compare_end_exclusive || q.compare_start >= q.compare_end_exclusive))) { setValidationError(t("请选择有效的开始与结束日期。")); return; }
    setValidationError(''); setDraft(q); active.current = JSON.stringify(q); setSnapshotId(null); setOffset(0);
    const next = new URLSearchParams({ dataset: q.dataset_id, start: q.start, end: q.end_exclusive, comparison: q.comparison, granularity: q.granularity });
    q.skus.forEach(s => next.append('sku', s));
    if (q.comparison === 'custom') { next.set('compare_start', q.compare_start!); next.set('compare_end', q.compare_end_exclusive!); }
    setParams(next, { replace: true }); request.mutate(q);
  }
  useEffect(() => {
    if (draft) return;
    const v = requestedVersion ? availableVersions.find(v => v.id === requestedVersion) : versions.data?.[0];
    if (!v) return;
    const q = defaults(v);
    if (/^\d{4}-\d{2}-\d{2}$/.test(params.get('start') ?? '') && /^\d{4}-\d{2}-\d{2}$/.test(params.get('end') ?? '')) { q.start = params.get('start')!; q.end_exclusive = params.get('end')!; }
    if (['none', 'previous', 'custom'].includes(params.get('comparison') ?? '')) q.comparison = params.get('comparison')!;
    q.compare_start = params.get('compare_start'); q.compare_end_exclusive = params.get('compare_end');
    q.granularity = params.get('granularity') === 'week' ? 'week' : 'day'; q.skus = params.getAll('sku');
    setDraft(q); apply(q);
  }, [versions.data, selectedVersion.data]);
  const busy = request.isPending || (!!snapshotId && (snapshot.isPending || ['queued', 'running'].includes(snapshot.data?.status ?? '')));
  const dirty = !!draft && JSON.stringify(draft) !== active.current;
  const error = versions.error ?? selectedVersion.error ?? request.error ?? snapshot.error ?? products.error ?? choices.error;
  function update<K extends keyof Query>(key: K, v: Query[K]) { setDraft(d => d && ({ ...d, [key]: v })); }
  function addSku() { const s = skuInput.trim(); if (draft && s && !draft.skus.includes(s) && draft.skus.length < 100) { update('skus', [...draft.skus, s]); setSkuInput(''); } }
  function submit(e: FormEvent) { e.preventDefault(); if (draft) apply(draft); }
  return <div className="dashboard"><div className="page-heading"><div><h1>{t("经营看板")}</h1><p>{t("销售、毛利与商品表现。")}</p></div><Link to="/data" className="secondary"><Database size={15} />{t("管理数据")}</Link></div>
    {error && <div className="error-notice" role="alert">{message(error.message)}</div>}
    {versions.isPending && <p className="empty-copy">{t("读取已发布数据版本…")}</p>}
    {versions.data?.length === 0 && <section className="panel dashboard-empty"><Database size={38} /><h2>{t("暂无经营数据")}</h2><p>{t("发布订单数据后即可查看看板。")}</p><Link to="/data" className="primary">{t("前往导入数据")}<ArrowRight size={15} /></Link></section>}
    {draft && <form className="panel dashboard-filters" onSubmit={submit}><div className="panel-title"><h2><SlidersHorizontal size={17} /> {t("分析范围")}</h2><span></span></div><div className="filter-grid">
      <label className="field version-select">{t("数据版本")}<select aria-label={t("数据版本")} value={draft.dataset_id} onChange={e => { const v = availableVersions.find(v => v.id === e.target.value)!; setDraft(defaults(v)); setSkuInput(''); }}><option value="" disabled>{t("选择已发布版本")}</option>{availableVersions.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id.slice(0, 8)}</option>)}</select></label>
      <label className="field">{t("开始日期")}<input aria-label={t("开始日期")} type="date" min="1900-01-01" max="2100-12-31" required value={draft.start} onChange={e => update('start', e.target.value)} /></label><label className="field">{t("结束日期（含当日）")}<input aria-label={t("结束日期（含当日）")} type="date" min="1900-01-01" max="2100-12-31" required value={draft.end_exclusive ? day(draft.end_exclusive, -1) : ''} onChange={e => update('end_exclusive', e.target.value ? day(e.target.value, 1) : '')} /></label>
      <label className="field">{t("比较周期")}<select aria-label={t("比较周期")} value={draft.comparison} onChange={e => update('comparison', e.target.value)}><option value="previous">{t("上一等长周期")}</option><option value="custom">{t("自定义比较")}</option><option value="none">{t("不比较")}</option></select></label><label className="field">{t("趋势粒度")}<select aria-label={t("趋势粒度")} value={draft.granularity} onChange={e => update('granularity', e.target.value)}><option value="day">{t("按日")}</option><option value="week">{t("按周")}</option></select></label>
      {draft.comparison === 'custom' && <><label className="field">{t("比较开始")}<input aria-label={t("比较开始")} type="date" required value={draft.compare_start ?? ''} onChange={e => update('compare_start', e.target.value)} /></label><label className="field">{t("比较结束（含当日）")}<input aria-label={t("比较结束（含当日）")} type="date" required value={draft.compare_end_exclusive ? day(draft.compare_end_exclusive, -1) : ''} onChange={e => update('compare_end_exclusive', e.target.value ? day(e.target.value, 1) : null)} /></label></>}
    </div><div className="sku-controls"><label className="field">{t("SKU 筛选")}<div className="sku-input"><input aria-label={t("SKU 筛选")} list="dashboard-skus" value={skuInput} maxLength={128} placeholder={t("输入 SKU，留空查看全部")} onChange={e => setSkuInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSku(); } }} /><button type="button" className="secondary" onClick={addSku}>{t("添加")}</button></div></label><datalist id="dashboard-skus">{choices.data?.map(s => <option key={s} value={s} />)}</datalist><div className="sku-chips">{draft.skus.map(s => <button type="button" key={s} onClick={() => update('skus', draft.skus.filter(v => v !== s))}>{s}<X size={12} /></button>)}</div><div className="filter-actions"><span>{dirty ? t("筛选已修改，点击更新") : t("按店铺时区 · 最多 366 天")}</span><button className="primary" disabled={request.isPending} type="submit"><RefreshCw size={15} />{t("更新看板")}</button></div></div></form>}
    {validationError && <div className="error-notice" role="alert">{message(validationError)}</div>}
    {busy && <section className="panel computing" role="status"><LoaderCircle className="spin" size={23} /><div><strong>{snapshot.data?.status === 'running' ? t("正在计算经营指标") : t("指标任务已提交")}</strong><p>{t("计算完成后自动显示。")}</p></div></section>}
    {snapshot.data?.status === 'failed' && <section className="panel"><h2>{t("指标计算未完成")}</h2><p className="form-hint">{t("请确认 worker 与数据库正常，或缩小时间/商品范围后重试。错误代码：")}{snapshot.data.error_code}</p><button className="secondary" onClick={() => draft && apply(draft)}>{t("重新计算")}</button></section>}
    {result && <>
      <div className="analysis-context"><CalendarDays size={16} /><strong>{result.periods.current[0]} — {day(result.periods.current[1], -1)}</strong><span>{result.timezone} · {result.currency} · {result.query.skus.length ? `SKU：${result.query.skus.join('、')}` : t("全部商品")}</span><span className="snapshot-ready"><CheckCircle2 size={13} />{t("计算已完成")}</span></div>
      {!!result.warnings.length && <aside className="quality-notes" aria-label={t("数据质量提示")}><Info size={18} /><div>{result.warnings.map(code => <p key={code}>{t(warnings[code] ?? code)}</p>)}</div></aside>}
      <section className="metric-grid">{['net_sales', 'paid_orders', 'aov', 'gross_profit', 'gross_sales', 'refund_amount', 'gross_margin', 'paid_units'].map(k => <article className={`metric-card ${k === 'net_sales' ? 'featured' : ''}`} key={k} data-testid={`metric-${k}`}><div className="metric-label">{t(labels[k])}<Activity size={14} /></div><strong className="metric-value"><MetricValue metric={result.current.metrics[k]} result={result} /></strong><div className="metric-change">{changeText(result.comparison?.[k])}{result.comparison?.[k]?.quality === 'estimated' ? t(" · 估算") : ''}</div><small className="metric-baseline">{result.previous ? t("比较期 {0}", value(result.previous.metrics[k], result)) : t("本期筛选范围")}</small></article>)}</section>
      {result.current.quality.missing_cost_rows > 0 && <section className="panel matched-subset"><div><h2>{t("已匹配成本商品 · 单独核算")}</h2><p>{t("缺失")}{result.current.quality.missing_cost_rows} {t("行 /")}{result.current.quality.missing_cost_skus} {t("个 SKU，涉及实付")}{money(result.current.quality.missing_cost_paid_minor, result)}{t("。已匹配")}{result.matched_cost_subset.row_count} {t("条明细，以下三项严格使用该子集。")}</p></div><div>{['net_sales', 'net_cogs', 'gross_profit'].map(k => <span key={k}>{t(labels[k])}<strong data-testid={`subset-${k}`}><MetricValue metric={result.matched_cost_subset.metrics[k]} result={result} /></strong></span>)}</div></section>}
      <div className="dashboard-charts"><Trend key={snapshotId} result={result} /><Contributions result={result} /></div>
      <section className="panel product-panel"><div className="panel-title"><div><h2>{t("商品表现")}</h2><p>{t("点击 SKU 筛选；各商品订单量不可相加。")}</p></div><span>{products.data?.total ?? '—'} {t("个商品分组")}</span></div><div className="product-controls"><label>{t("排序")}<select aria-label={t("商品排序")} value={sort} onChange={e => { setSort(e.target.value); setOffset(0); }}>{['net_sales', 'gross_profit', 'refund_amount', 'paid_units'].map(k => <option value={k} key={k}>{t(labels[k])}</option>)}</select></label><label>{t("方向")}<select aria-label={t("排序方向")} value={direction} onChange={e => { setDirection(e.target.value); setOffset(0); }}><option value="desc">{t("从高到低")}</option><option value="asc">{t("从低到高")}</option></select></label><label>{t("查看")}<select aria-label={t("商品条件")} value={focus} onChange={e => { setFocus(e.target.value); setOffset(0); }}><option value="all">{t("全部")}</option><option value="negative_profit">{t("负毛利")}</option><option value="refunded">{t("发生退款")}</option></select></label></div><div className="table-scroll"><table><thead><tr><th>{t("商品 / SKU")}</th><th>{t("净销售额")}</th><th>{t("支付件数 / 订单")}</th><th>{t("累计退款")}</th><th>{t("商品毛利")}</th><th>{t("销售变动贡献")}</th></tr></thead><tbody>{products.data?.items.map((p, i) => <tr key={p.sku ?? `unmapped-${i}`}><td><strong>{p.product_name}</strong>{p.sku ? <button className="text-button sku-filter-link" onClick={() => draft && apply({ ...draft, skus: [p.sku!] })}>{p.sku}</button> : <small>{t("未映射 SKU")}</small>}</td><td><MetricValue metric={p.current.metrics.net_sales} result={result} /></td><td>{value(p.current.metrics.paid_units, result)} / {value(p.current.metrics.paid_orders, result)}</td><td><MetricValue metric={p.current.metrics.refund_amount} result={result} /></td><td><MetricValue metric={p.current.metrics.gross_profit} result={result} /></td><td>{money(p.sales_contribution_minor, result)}</td></tr>)}</tbody></table></div>{products.isPending ? <p className="empty-copy">{t("正在读取商品结果…")}</p> : products.data?.total === 0 ? <p className="empty-copy">{t("当前范围或商品条件下没有记录。")}</p> : null}{(products.data?.total ?? 0) > 20 && <div className="pagination"><button className="secondary" disabled={offset === 0} onClick={() => setOffset(offset - 20)}>{t("上一页")}</button><span>{offset + 1}–{Math.min(offset + 20, products.data!.total)} / {products.data?.total}</span><button className="secondary" disabled={offset + 20 >= products.data!.total} onClick={() => setOffset(offset + 20)}>{t("下一页")}</button></div>}</section>
      <details className="panel metric-definitions"><summary>{t("更多指标与计算口径")}</summary><div className="extra-metrics">{['net_cogs', 'gross_aov', 'refund_amount_rate', 'refunded_order_rate', 'cost_line_coverage', 'cost_amount_coverage'].map(k => <div key={k}><span>{t(labels[k])}</span><strong><MetricValue metric={result.current.metrics[k]} result={result} /></strong><small>{changeText(result.comparison?.[k])}</small></div>)}</div><p>{t("退款为截至")}{result.source_as_of} {t("的累计值，归属原支付周期，并非期间现金退款；近期订单的退款观察时间可能更短。")}</p><p>{t("商品毛利按上传金额口径计算，未扣平台佣金、运费、广告、人工和税费。成本逐行 ROUND_HALF_UP 后汇总；未知回库按不回转成本估算。")}</p><p>{t("源版本排除")}{result.excluded_rows} {t("行（全文件范围）。本期")}{result.current.row_count} {t("条明细，")}{result.current.coverage_complete ? t("完整覆盖") : t("覆盖不完整")}{t("。数据版本")}{result.dataset_id} {t("· 指标引擎")}{result.engine_version}。</p>{result.periods.previous && <p>{t("比较范围：")}{result.periods.previous[0]} {t("至")}{day(result.periods.previous[1], -1)}，{result.previous?.coverage_complete ? t("完整覆盖") : t("覆盖不完整")}{t("。自定义比较可不等长，请结合天数解释差异。")}</p>}</details>
    </>}
  </div>;
}
