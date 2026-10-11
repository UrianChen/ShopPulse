import { t, useLanguage, message } from '../../lib/i18n';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Database, Download, FileSpreadsheet, LoaderCircle, Plus, ShieldCheck, UploadCloud } from 'lucide-react';
import { api } from '../../lib/api';
import './imports.css';

type Kind = 'orders' | 'costs';
type Preview = { columns: string[]; sheets: string[]; sheet_name: string | null; row_count: number; suggestions: Record<string, { column: string; confidence: number }>; preview: { row_number: number; values: Record<string, string> }[] };
type Options = {
  timezone: string; currency: string; currency_exponent: number; input_money_unit: string;
  decimal_separator: string; amount_scope: string; payment_state_mode: string;
  status_mapping: Record<string, string>; refund_mode: string; refund_scope: string;
  coverage_start: string; coverage_end_exclusive: string; source_as_of: string;
  cost_effective_from: string; cost_effective_to: string; semantics_confirmed: boolean; coverage_confirmed: boolean;
};
type Config = { sheet_name: string | null; header_row: number; encoding: string; delimiter: string; columns: Record<string, string>; cost_version_id: string | null; options: Options };
type Summary = { source_rows: number; included_rows: number; excluded_rows: number; unpaid_rows: number; errors: number; unacknowledged: number; issue_counts: Record<string, number>; warning_codes: string[]; cost_matched_rows: number; preview?: Preview };
type Draft = { id: string; upload_id: string; name: string; kind: Kind; revision: number; validated_revision: number | null; config: Config; status: string; summary: Summary | null; error_message: string | null; published_id: string | null; resolutions: { excluded_rows?: number[]; acknowledged_codes?: string[]; reason?: string } };
type UploadRecord = { id: string; name: string; status: string; kind: Kind; metadata: Preview | null; error_message: string | null; source_available: boolean; source_deleted_at: string | null };
type Issue = { code: string; severity: string; row_number: number; field: string; message: string; acknowledged: boolean };
type Version = { id: string; name: string; row_count: number; created_at: string; source_available?: boolean; summary?: Summary; snapshot: { config: Config; file_sha256: string; engine_version: string } };
type Detail = Version & { preview: { source_row_number: number; order_id: string; sku: string | null; quantity: number; line_paid_minor: number; line_refund_minor: number | null; unit_cost: string | null }[] };
type CostDetail = Version & { preview: { sku: string; unit_cost: string; currency: string; effective_from: string; effective_to: string | null }[] };

const stateName: Record<string, string> = { mapping_required: '待确认映射', validating: '校验中', review_required: '待处理问题', ready: '可发布', publishing: '发布中', published: '已发布', failed: '处理失败', parsing: '解析中' };
const orderFields: Record<string, string> = { order_id: '订单编号 *', order_line_id: '明细编号', sku: '商品 SKU', product_name: '商品名称', paid_at: '支付时间 *', quantity: '购买数量 *', line_paid_minor: '商品 / 订单实付', line_refund_minor: '累计商品退款', restocked_quantity: '已回库数量', currency: '币种', payment_state: '支付状态', allocation_weight: '优惠前金额（分摊权重）', shipping_minor: '订单运费', unit_price: '单价（推导实付）', discount_minor: '明细优惠（推导实付）' };
const costFields: Record<string, string> = { sku: '商品 SKU *', unit_cost: '单位成本 *', currency: '币种', effective_from: '生效时间', effective_to: '失效时间（不含）' };
function Notice({ error }: { error: Error | null }) {
  useLanguage(); return error ? <div className="error-notice" role="alert">{message(error.message)}</div> : null; }
function State({ value }: { value: string }) {
  useLanguage(); return <span className={`import-state state-${value}`}>{t(stateName[value] ?? value)}</span>; }

function SourcePreview({ data }: { data?: Preview | null }) {
  useLanguage();
  if (!data) return null;
  return <details className="source-preview"><summary>{t("查看源表预览 ·")}{data.row_count} {t("行 · 最多显示前 10 行")}</summary><div className="table-scroll"><table><thead><tr><th>{t("行号")}</th>{data.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{data.preview.map(row => <tr key={row.row_number}><td>{row.row_number}</td>{data.columns.map(c => <td key={c}>{row.values[c]}</td>)}</tr>)}</tbody></table></div><p className="form-hint">{t("未识别的列在预览中隐藏。原文件仅保存在你的后端，不会发送给模型。")}</p></details>;
}

function UploadPanel({ onCreated }: { onCreated: (id: string) => void }) {
  useLanguage();
  const [kind, setKind] = useState<Kind>('orders');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [uploadId, setUploadId] = useState<string | null>(null);
  const upload = useMutation({ mutationFn: async () => {
    if (!file) throw new Error(t("请选择 CSV 或 XLSX 文件。"));
    if (file.size > 20 * 1024 * 1024) throw new Error(t("文件超过 20 MiB，请拆分后上传。"));
    const body = new FormData(); body.append('file', file); body.append('kind', kind);
    return api<{ upload_id: string }>('/uploads', { method: 'POST', body, signal: AbortSignal.timeout(120000) });
  }, onSuccess: result => setUploadId(result.upload_id) });
  const record = useQuery({ queryKey: ['upload', uploadId], enabled: !!uploadId, queryFn: () => api<UploadRecord>(`/uploads/${uploadId}`), refetchInterval: q => q.state.data?.status === 'parsing' ? 1500 : false });
  const create = useMutation({ mutationFn: () => api<Draft>('/imports', { method: 'POST', body: JSON.stringify({ upload_id: uploadId, name: name.trim() || file?.name }) }), onSuccess: result => onCreated(result.id) });
  const busy = upload.isPending || record.data?.status === 'parsing' || create.isPending;
  function submit(e: FormEvent) { e.preventDefault(); upload.mutate(); }
  return <section className="panel import-upload"><div className="panel-title"><div><h2>{t("导入数据")}</h2><p>{t("建议先导入成本，再导入订单。")}</p></div><UploadCloud size={23} /></div>
    <form onSubmit={submit}>
      <div className="kind-switch"><button type="button" className={kind === 'orders' ? 'selected' : ''} disabled={busy} onClick={() => { setKind('orders'); setUploadId(null); }}>{t("订单明细")}</button><button type="button" className={kind === 'costs' ? 'selected' : ''} disabled={busy} onClick={() => { setKind('costs'); setUploadId(null); }}>{t("商品成本")}</button></div>
      <label className="file-drop"><FileSpreadsheet size={32} /><strong>{file?.name ?? t("选择 CSV 或 Excel 文件")}</strong><span>{t("最大 20 MiB · 最多 100,000 行 · .csv / .xlsx")}</span><input aria-label={t("选择数据文件")} type="file" accept=".csv,.xlsx" disabled={busy} onChange={e => { const f = e.target.files?.[0] ?? null; setFile(f); setName(f?.name ?? ''); setUploadId(null); }} /></label>
      <label className="field">{t("导入名称")}<input aria-label={t("导入名称")} value={name} onChange={e => setName(e.target.value)} maxLength={120} required /></label>
      <div className="form-actions"><button className="primary" disabled={!file || busy} type="submit">{busy ? <LoaderCircle size={15} className="spin" /> : <UploadCloud size={15} />}{busy ? t("正在解析…") : t("上传并预览")}</button>
      {record.data && ['ready', 'failed'].includes(record.data.status) && <button type="button" className="secondary" disabled={create.isPending} onClick={() => create.mutate()}>{t("配置字段与口径")}</button>}</div>
    </form>
    <Notice error={upload.error ?? record.error ?? create.error} />
    {record.data?.error_message && <div className="error-notice">{message(record.data.error_message)}<br />{t("可继续配置编码、标题行或工作表后重新校验。")}</div>}
    <SourcePreview data={record.data?.metadata} />
    <div className="sample-links"><span>{t("使用合成样例：")}</span>{[['costs.csv', t("成本表")], ['orders.csv', t("订单 CSV")], ['orders.xlsx', t("订单 Excel")], ['orders_errors.csv', t("错误样例")]].map(([filename, label]) => <a key={filename} href={`/api/v1/samples/${filename}`} download><Download size={12} />{t(label)}</a>)}</div>
  </section>;
}

function Wizard({ id, onBack }: { id: string; onBack: () => void }) {
  useLanguage();
  const client = useQueryClient();
  const draft = useQuery({ queryKey: ['import', id], queryFn: () => api<Draft>(`/imports/${id}`), refetchInterval: q => ['validating', 'publishing'].includes(q.state.data?.status ?? '') ? 1500 : false });
  const upload = useQuery({ queryKey: ['upload', draft.data?.upload_id], enabled: !!draft.data, queryFn: () => api<UploadRecord>(`/uploads/${draft.data!.upload_id}`) });
  const costs = useQuery({ queryKey: ['cost-versions'], queryFn: () => api<Version[]>('/cost-versions') });
  const [config, setConfig] = useState<Config | null>(null);
  const [ack, setAck] = useState<string[]>([]);
  const [excluded, setExcluded] = useState('');
  const [reason, setReason] = useState('');
  const [offset, setOffset] = useState(0);
  const [statusMapping, setStatusMapping] = useState('');
  const current = draft.data;
  useEffect(() => { if (current) {
    setConfig(structuredClone(current.config)); setOffset(0);
    setAck(current.resolutions.acknowledged_codes ?? []);
    setExcluded((current.resolutions.excluded_rows ?? []).join(',')); setReason(current.resolutions.reason ?? '');
    setStatusMapping(Object.entries(current.config.options.status_mapping).map(([k, v]) => `${k}=${v}`).join('\n'));
  } }, [current?.id, current?.revision]);
  const problems = useQuery({ queryKey: ['issues', id, current?.validated_revision, current?.status, offset], enabled: !!current?.validated_revision, queryFn: () => api<{ total: number; items: Issue[] }>(`/imports/${id}/issues?offset=${offset}&limit=100`) });
  function refresh() { void client.invalidateQueries({ queryKey: ['import', id] }); void client.invalidateQueries({ queryKey: ['imports'] }); void client.invalidateQueries({ queryKey: ['datasets'] }); void client.invalidateQueries({ queryKey: ['cost-versions'] }); }
  const save = useMutation({ mutationFn: async () => {
    if (!config || !current) throw new Error(t("导入配置尚未加载。"));
    const mapping: Record<string, string> = {};
    for (const line of statusMapping.split('\n').filter(v => v.trim())) {
      const [key, state, extra] = line.split('=');
      if (!key || !state || extra || !['paid', 'unpaid', 'cancelled_unpaid'].includes(state.trim())) throw new Error(t("状态映射格式应为：原始状态=paid / unpaid / cancelled_unpaid，每行一条。"));
      mapping[key.trim()] = state.trim();
    }
    const updated = await api<Draft>(`/imports/${id}/mapping`, { method: 'PUT', body: JSON.stringify({ expected_revision: current.revision, config: { ...config, options: { ...config.options, status_mapping: mapping } } }) });
    return api(`/imports/${id}/validate`, { method: 'POST', body: JSON.stringify({ expected_revision: updated.revision }) });
  }, onSuccess: refresh });
  const resolve = useMutation({ mutationFn: async () => {
    const rows = excluded.trim() ? excluded.split(/[,，\s]+/).filter(Boolean).map(Number) : [];
    if (rows.some(v => !Number.isInteger(v) || v < 1)) throw new Error(t("排除行号须为正整数，以逗号分隔。"));
    const updated = await api<Draft>(`/imports/${id}/resolutions`, { method: 'PUT', body: JSON.stringify({ expected_revision: current?.revision, excluded_rows: [...new Set(rows)], acknowledged_codes: ack, reason }) });
    return api(`/imports/${id}/validate`, { method: 'POST', body: JSON.stringify({ expected_revision: updated.revision }) });
  }, onSuccess: refresh });
  const publish = useMutation({ mutationFn: () => api(`/imports/${id}/publish`, { method: 'POST', body: JSON.stringify({ expected_revision: current?.revision }) }), onSuccess: refresh });
  const error = draft.error ?? upload.error ?? costs.error ?? save.error ?? resolve.error ?? publish.error ?? problems.error;
  if (!current || !config) return <><Notice error={error} /><p className="muted">{t("读取导入配置…")}</p></>;
  const metadata = current.summary?.preview ?? upload.data?.metadata;
  const isOrder = current.kind === 'orders';
  const busy = ['validating', 'publishing'].includes(current.status) || save.isPending || resolve.isPending || publish.isPending;
  const locked = ['published', 'publishing', 'deleted'].includes(current.status) || upload.data?.source_available === false;
  function option<K extends keyof Options>(key: K, value: Options[K]) { setConfig(previous => previous && ({ ...previous, options: { ...previous.options, [key]: value } })); }
  const o = config.options;
  const savedStatusMapping = Object.entries(current.config.options.status_mapping).map(([k, v]) => `${k}=${v}`).join('\n');
  const dirty = JSON.stringify(config) !== JSON.stringify(current.config) || statusMapping !== savedStatusMapping;
  return <div className="import-wizard"><button className="back-link" onClick={onBack}><ArrowLeft size={15} />{t("返回数据中心")}</button>
    <div className="page-heading"><div><h1>{current.name}</h1><p>{isOrder ? t("订单明细") : t("商品成本")} {t("· 修订")} {current.revision} {t("· 发布后数据不可原地修改")}</p></div><State value={current.status} /></div>
    <Notice error={error} />{current.error_message && <div className="error-notice">{message(current.error_message)}</div>}
    {upload.data?.source_available === false && <p className="error-notice">{t("原文件已按保留策略清理，无法重新导入或核对原表。已发布的标准化数据和报告仍可使用。")}</p>}
    {current.status === 'published' ? <section className="panel published-card"><CheckCircle2 size={36} /><h2>{t("数据版本已发布")}</h2><p>{current.summary?.included_rows} {t("行已安全保存。原始文件哈希、字段映射、排除决策和口径均已冻结。")}</p><code>{current.published_id}</code><button className="primary" onClick={onBack}>{t("查看数据版本")}</button>{isOrder && <Link className="secondary" to={`/dashboard?dataset=${current.published_id}`}>{t("打开经营看板")}</Link>}</section> : <>
    <section className="panel"><div className="panel-title"><div><h2>{t("01 · 解析与字段映射")}</h2><p>{t("字段建议仅作参考，请根据源表确认。可输入自定义列名。")}</p></div><FileSpreadsheet size={20} /></div>
      <fieldset disabled={busy || locked}><details className="advanced-settings"><summary>{t("文件解析设置")}</summary><div className="form-grid parse-options">
        <label className="field">{t("工作表")}<input aria-label={t("工作表")} list="sheet-names" value={config.sheet_name ?? ''} placeholder={t("CSV 无需填写")} onChange={e => setConfig({ ...config, sheet_name: e.target.value || null })} /><datalist id="sheet-names">{metadata?.sheets.map(s => <option key={s} value={s} />)}</datalist></label>
        <label className="field">{t("标题行")}<input aria-label={t("标题行")} type="number" min={1} max={100} value={config.header_row} onChange={e => setConfig({ ...config, header_row: Number(e.target.value) })} /></label>
        <label className="field">{t("CSV 编码")}<select aria-label={t("CSV 编码")} value={config.encoding} onChange={e => setConfig({ ...config, encoding: e.target.value })}><option value="utf-8-sig">UTF-8 / BOM</option><option value="gb18030">GB18030</option></select></label>
        <label className="field">{t("CSV 分隔符")}<select aria-label={t("CSV 分隔符")} value={config.delimiter} onChange={e => setConfig({ ...config, delimiter: e.target.value })}><option value=",">{t("逗号")}</option><option value=";">{t("分号")}</option><option value={'\t'}>{t("制表符")}</option></select></label>
      </div>
      </details><SourcePreview data={metadata} />
      {metadata && <button className="text-button" type="button" onClick={() => setConfig({ ...config, columns: Object.fromEntries(Object.entries(metadata.suggestions).map(([k, v]) => [k, v.column])) })}>{t("套用当前预览的字段建议")}</button>}
      <datalist id="source-columns">{metadata?.columns.map(c => <option key={c} value={c} />)}</datalist>
      <div className="mapping-grid">{Object.entries(isOrder ? orderFields : costFields).map(([key, label]) => <label className="field" key={key}>{t(label)}<input aria-label={t(label)} list="source-columns" placeholder={t("不映射")} value={config.columns[key] ?? ''} onChange={e => { const next = { ...config.columns }; if (e.target.value) next[key] = e.target.value; else delete next[key]; setConfig({ ...config, columns: next }); }} /></label>)}</div></fieldset>
    </section>
    <section className="panel"><div className="panel-title"><div><h2>{t("02 · 确认数据口径")}</h2><p>{t("金额与时间含义将随数据版本冻结，不由模型推断。")}</p></div><ShieldCheck size={20} /></div>
      <fieldset disabled={busy || locked}><div className="form-grid">
        <label className="field">{t("时区")}<input aria-label={t("时区")} value={o.timezone} onChange={e => option('timezone', e.target.value)} /></label>
        <label className="field">{t("币种")}<input aria-label={t("币种")} value={o.currency} maxLength={3} onChange={e => option('currency', e.target.value.toUpperCase())} /></label>
        <label className="field">{t("币种小数位")}<input aria-label={t("币种小数位")} type="number" min={0} max={4} value={o.currency_exponent} onChange={e => option('currency_exponent', Number(e.target.value))} /></label>
        <label className="field">{t("十进制符号")}<select value={o.decimal_separator} onChange={e => option('decimal_separator', e.target.value)}><option value=".">{t("小数点 .")}</option><option value=",">{t("小数逗号 ,")}</option></select></label>
      </div>
      {isOrder ? <>
        <div className="form-grid"><label className="field">{t("输入金额单位")}<select aria-label={t("输入金额单位")} value={o.input_money_unit} onChange={e => option('input_money_unit', e.target.value)}><option value="major">{t("元（主货币单位）")}</option><option value="minor">{t("分（最小货币单位）")}</option></select></label>
        <label className="field">{t("金额层级")}<select aria-label={t("金额层级")} value={o.amount_scope} onChange={e => option('amount_scope', e.target.value)}><option value="line_goods_excluding_shipping">{t("明细商品实付，不含运费")}</option><option value="order_goods">{t("订单商品总额，按权重分摊")}</option><option value="order_with_shipping">{t("订单总额含运费，扣除后分摊")}</option><option value="derived">{t("单价 × 数量 − 明细优惠")}</option></select></label>
        <label className="field">{t("支付状态口径")}<select aria-label={t("支付状态口径")} value={o.payment_state_mode} onChange={e => option('payment_state_mode', e.target.value)}><option value="mapped">{t("按源表字段映射")}</option><option value="confirmed_all_paid">{t("确认文件中全部已支付")}</option></select></label>
        <label className="field">{t("退款数据")}<select aria-label={t("退款数据")} value={o.refund_mode} onChange={e => option('refund_mode', e.target.value)}><option value="unknown">{t("未知（净值指标不可用）")}</option><option value="provided">{t("已提供累计商品退款")}</option><option value="confirmed_none">{t("确认覆盖范围内无退款")}</option></select></label>
        <label className="field">{t("退款层级")}<select aria-label={t("退款层级")} value={o.refund_scope} onChange={e => option('refund_scope', e.target.value)}><option value="line">{t("明细退款")}</option><option value="order">{t("订单退款，按实付分摊（估算）")}</option></select></label>
        <label className="field">{t("关联成本版本")}<select aria-label={t("关联成本版本")} value={config.cost_version_id ?? ''} onChange={e => setConfig({ ...config, cost_version_id: e.target.value || null })}><option value="">{t("暂不关联（成本缺失）")}</option>{costs.data?.map(v => <option key={v.id} value={v.id}>{v.name} · {v.row_count} {t("行 ·")}{v.id.slice(0, 8)}</option>)}</select></label></div>
        {o.payment_state_mode === 'mapped' && <label className="field">{t("支付状态映射")}<textarea aria-label={t("支付状态映射")} rows={3} value={statusMapping} placeholder={t("已付款=paid\n待付款=unpaid\n已取消=cancelled_unpaid")} onChange={e => setStatusMapping(e.target.value)} /><span className="form-hint">{t("每行：源表状态=paid / unpaid / cancelled_unpaid")}</span></label>}
        <div className="form-grid three-cols"><label className="field">{t("覆盖开始")}<input aria-label={t("覆盖开始")} placeholder="2026-09-21T00:00:00+08:00" value={o.coverage_start} onChange={e => option('coverage_start', e.target.value)} /></label><label className="field">{t("覆盖结束（不含）")}<input aria-label={t("覆盖结束（不含）")} placeholder="2026-10-05T00:00:00+08:00" value={o.coverage_end_exclusive} onChange={e => option('coverage_end_exclusive', e.target.value)} /></label><label className="field">{t("数据截止时间")}<input aria-label={t("数据截止时间")} placeholder="2026-10-07T00:00:00+08:00" value={o.source_as_of} onChange={e => option('source_as_of', e.target.value)} /></label></div>
        <label className="check-field"><input type="checkbox" checked={o.coverage_confirmed} onChange={e => option('coverage_confirmed', e.target.checked)} />{t("我确认文件完整覆盖以上区间，退款为截止时间的累计值。")}</label>
      </> : <><p className="form-hint">{t("单位成本以主货币单位输入，最多 6 位小数；按照订单支付时间匹配。同 SKU 生效区间不可重叠。")}</p><div className="form-grid"><label className="field">{t("静态成本生效起点")}<input aria-label={t("静态成本生效起点")} placeholder={t("源表无生效时间时必须填写")} value={o.cost_effective_from} onChange={e => option('cost_effective_from', e.target.value)} /></label><label className="field">{t("静态成本失效终点")}<input placeholder={t("空值表示持续有效")} value={o.cost_effective_to} onChange={e => option('cost_effective_to', e.target.value)} /></label></div></>}
      <label className="check-field"><input type="checkbox" checked={o.semantics_confirmed} onChange={e => option('semantics_confirmed', e.target.checked)} />{t("我已核实字段映射、金额层级、币种以及")}{isOrder ? t("支付与退款") : t("成本")}{t("含义。")}</label>
      <button className="primary" disabled={busy || locked} onClick={() => save.mutate()}>{busy ? <LoaderCircle size={15} className="spin" /> : <ShieldCheck size={15} />}{t("保存并校验")}</button></fieldset>
    </section>
    {current.summary && <section className="panel quality-panel"><div className="panel-title"><div><h2>{t("03 · 处理数据质量问题")}</h2><p>{t("排除或确认后会产生新的配置修订，并重新校验。")}</p></div><State value={current.status} /></div>
      <div className="quality-stats"><div><strong>{current.summary.source_rows}</strong><span>{t("原始数据行")}</span></div><div><strong>{current.summary.included_rows}</strong><span>{t("拟纳入行")}</span></div><div><strong>{current.summary.errors}</strong><span>{t("阻断问题")}</span></div><div><strong>{current.summary.unacknowledged}</strong><span>{t("待确认警告")}</span></div></div>
      <p className="form-hint">{t("已排除")}{current.summary.excluded_rows} {t("行 · 未支付")}{current.summary.unpaid_rows} {t("行 · 成本匹配")}{current.summary.cost_matched_rows} {t("行")}</p>
      {!!problems.data?.items.length && <div className="table-scroll"><table><thead><tr><th>{t("行号")}</th><th>{t("等级")}</th><th>{t("规则")}</th><th>{t("处理建议")}</th></tr></thead><tbody>{problems.data.items.map((i, n) => <tr key={`${i.code}-${i.row_number}-${n}`}><td>{i.row_number || t("配置")}</td><td><span className={i.severity === 'error' ? 'issue-error' : 'issue-warning'}>{i.severity === 'error' ? t("阻断") : i.acknowledged ? t("已确认") : t("警告")}</span></td><td><code>{i.code}</code></td><td>{message(i.message)}</td></tr>)}</tbody></table></div>}
      {(problems.data?.total ?? 0) > 100 && <div className="pagination"><button className="secondary" disabled={offset === 0} onClick={() => setOffset(offset - 100)}>{t("上一页")}</button><span>{offset + 1}–{Math.min(offset + 100, problems.data!.total)} / {problems.data?.total}</span><button className="secondary" disabled={offset + 100 >= problems.data!.total} onClick={() => setOffset(offset + 100)}>{t("下一页")}</button></div>}
      {current.status === 'review_required' && <fieldset disabled={busy}><div className="resolution-box"><h3>{t("确认与排除决策")}</h3>{current.summary.warning_codes.map(code => <label className="check-field" key={code}><input type="checkbox" checked={ack.includes(code)} onChange={e => setAck(e.target.checked ? [...ack, code] : ack.filter(v => v !== code))} />{t("已核实并接受")}{code}（{current.summary!.issue_counts[code]} {t("处）")}</label>)}<div className="form-grid"><label className="field">{t("排除的源表行号")}<input aria-label={t("排除的源表行号")} value={excluded} placeholder={t("例如 8,12；不排除则留空")} onChange={e => setExcluded(e.target.value)} /></label><label className="field">{t("决策原因")}<input aria-label={t("决策原因")} value={reason} maxLength={500} placeholder={t("说明排除或接受警告的依据")} onChange={e => setReason(e.target.value)} /></label></div><button className="secondary" disabled={!reason.trim()} onClick={() => resolve.mutate()}>{t("保存决策并重新校验")}</button></div></fieldset>}
      <div className="publish-actions"><div><strong>{t("发布不可变数据版本")}</strong><p>{dirty ? t("你有未保存的修改，请先保存并重新校验。") : t("后续修改需要创建新版本；有未解决阻断或警告时禁止发布。")}</p></div><button className="primary" disabled={current.status !== 'ready' || busy || dirty} onClick={() => publish.mutate()}><CheckCircle2 size={16} />{t("发布数据版本")}</button></div>
    </section>}
    </>}
  </div>;
}

export function DataCenter() {
  useLanguage();
  const [params, setParams] = useSearchParams();
  const id = params.get('import');
  const imports = useQuery({ queryKey: ['imports'], queryFn: () => api<Draft[]>('/imports'), refetchInterval: 5000 });
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: () => api<Version[]>('/datasets'), refetchInterval: 5000 });
  const costs = useQuery({ queryKey: ['cost-versions'], queryFn: () => api<Version[]>('/cost-versions'), refetchInterval: 5000 });
  const [newUpload, setNewUpload] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [costDetailId, setCostDetailId] = useState<string | null>(null);
  const costDetail = useQuery({ queryKey: ['cost-version', costDetailId], enabled: !!costDetailId, queryFn: () => api<CostDetail>(`/cost-versions/${costDetailId}`) });
  const detail = useQuery({ queryKey: ['dataset', detailId], enabled: !!detailId, queryFn: () => api<Detail>(`/datasets/${detailId}`) });
  const client = useQueryClient();
  function back() { setParams({}); setNewUpload(false); void client.invalidateQueries({ queryKey: ['datasets'] }); void client.invalidateQueries({ queryKey: ['cost-versions'] }); void client.invalidateQueries({ queryKey: ['imports'] }); }
  if (id) return <Wizard key={id} id={id} onBack={back} />;
  return <div className="data-center"><div className="page-heading"><div><h1>{t("数据中心")}</h1><p>{t("管理订单与成本数据。")}</p></div><button className="primary" onClick={() => setNewUpload(!newUpload)}><Plus size={16} />{newUpload ? t("收起上传") : t("导入数据")}</button></div>
    
    {(newUpload || imports.data?.length === 0) && <UploadPanel onCreated={next => { setParams({ import: next }); void client.invalidateQueries({ queryKey: ['imports'] }); }} />}
    {(imports.isPending || datasets.isPending || costs.isPending) && <p className="empty-copy" role="status">{t("读取中…")}</p>}
    <Notice error={imports.error ?? datasets.error ?? costs.error ?? detail.error ?? costDetail.error} />
    <section className="panel"><div className="panel-title"><div><h2>{t("导入记录")}</h2><p>{t("最近 100 次导入")}</p></div><FileSpreadsheet size={20} /></div><div className="table-scroll"><table><thead><tr><th>{t("名称")}</th><th>{t("数据类型")}</th><th>{t("状态")}</th><th>{t("行数")}</th><th>{t("操作")}</th></tr></thead><tbody>{imports.data?.map(item => <tr key={item.id}><td>{item.name}</td><td>{item.kind === 'orders' ? t("订单明细") : t("商品成本")}</td><td><State value={item.status} /></td><td>{item.summary?.included_rows ?? '—'}</td><td><button className="text-button" onClick={() => setParams({ import: item.id })}>{item.status === 'published' ? t("查看记录") : t("继续处理")}</button></td></tr>)}</tbody></table></div>{!imports.isPending && !imports.data?.length && <p className="empty-copy">{t("暂无导入记录")}</p>}</section>
    <div className="version-grid">{[[t("已发布订单版本"), datasets.data ?? [], 'orders'], [t("已发布成本版本"), costs.data ?? [], 'costs']].map(([title, values, kind]) => <section className="panel" key={t(title as string)}><div className="panel-title"><h2>{t(title as string)}</h2><span className="outline-badge">{(values as Version[]).length} {t("个版本")}</span></div>{(values as Version[]).map(v => <div className="version-row" key={v.id}><span className="tile-icon"><Database size={17} /></span><div><strong>{v.name}</strong><p>{v.row_count} {t("行 ·")}{v.snapshot.config.options.currency} · {v.id.slice(0, 8)}</p></div>{<button className="text-button" onClick={() => kind === 'orders' ? (setDetailId(v.id), setCostDetailId(null)) : (setCostDetailId(v.id), setDetailId(null))}>{t("查看")}</button>}</div>)}{!datasets.isPending && !costs.isPending && !(values as Version[]).length && <p className="empty-copy">{t("暂无版本，通过校验后即可发布。")}</p>}</section>)}</div>
    {(detail.data?.source_available === false || costDetail.data?.source_available === false) && <p className="error-notice">{t("原文件已清理，无法核对原表。以下标准化数据与文件哈希仍保留。")}</p>}
    {detail.data && <section className="panel dataset-detail"><div className="panel-title"><div><h2>{detail.data.name}</h2><p>{t("标准化明细预览 · 金额以最小货币单位显示（CNY 为分）")}</p></div><button className="text-button" onClick={() => setDetailId(null)}>{t("收起")}</button></div><div className="snapshot-info"><span>{t("覆盖：")}{detail.data.snapshot.config.options.coverage_start} {t("至")}{detail.data.snapshot.config.options.coverage_end_exclusive}{t("（不含）")}</span><span>{t("数据截止：")}{detail.data.snapshot.config.options.source_as_of}</span><span>{t("引擎：")}{detail.data.snapshot.engine_version} {t("· 文件 SHA-256：")}{detail.data.snapshot.file_sha256}</span></div><div className="table-scroll"><table><thead><tr><th>{t("源行号")}</th><th>{t("订单")}</th><th>SKU</th><th>{t("数量")}</th><th>{t("实付（最小单位）")}</th><th>{t("退款（最小单位）")}</th><th>{t("单位成本（主单位）")}</th></tr></thead><tbody>{detail.data.preview.map(r => <tr key={r.source_row_number}><td>{r.source_row_number}</td><td>{r.order_id}</td><td>{r.sku ?? t("未匹配")}</td><td>{r.quantity}</td><td>{r.line_paid_minor}</td><td>{r.line_refund_minor ?? t("未知")}</td><td>{r.unit_cost ?? t("缺失")}</td></tr>)}</tbody></table></div></section>}
    {costDetail.data && <section className="panel cost-detail"><div className="panel-title"><div><h2>{costDetail.data.name}</h2><p>{t("不可变成本版本 · 前 20 行 · 金额为主货币单位")}</p></div><button className="text-button" onClick={() => setCostDetailId(null)}>{t("收起")}</button></div><div className="table-scroll"><table><thead><tr><th>SKU</th><th>{t("单位成本")}</th><th>{t("币种")}</th><th>{t("生效时间")}</th><th>{t("失效时间（不含）")}</th></tr></thead><tbody>{costDetail.data.preview.map((r, i) => <tr key={i}><td>{r.sku}</td><td>{r.unit_cost}</td><td>{r.currency}</td><td>{r.effective_from}</td><td>{r.effective_to ?? t("持续有效")}</td></tr>)}</tbody></table></div></section>}
  </div>;
}
