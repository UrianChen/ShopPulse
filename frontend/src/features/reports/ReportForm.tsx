import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, FileBarChart2, LoaderCircle } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { day, lastDay } from '../../lib/dates';
import { getLanguage, t, useLanguage } from '../../lib/i18n';
import type { DatasetVersion, ModelConfig, ReportInput } from '../../lib/types';
import type { Report } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

type Comparison = NonNullable<ReportInput['query']['comparison']>;
export type Preset = { start: string; end: string; comparison: string; skus: string };

function comparisonOf(value: string | undefined): Comparison {
  return value === 'custom' || value === 'none' ? value : 'previous';
}

export function ReportForm({
  versions,
  models,
  parent,
  preset,
}: {
  versions: DatasetVersion[];
  models: Pick<ModelConfig, 'id' | 'name' | 'is_default' | 'capabilities' | 'consent_current'>[];
  parent?: Report;
  preset?: Preset;
}) {
  useLanguage();
  const navigate = useNavigate();
  const first = versions.find(v => v.id === parent?.dataset_id) ?? versions[0];
  const end = first.snapshot.config.options.coverage_end_exclusive.slice(0, 10);
  const [title, setTitle] = useState(parent?.title ?? t('店铺经营周报'));
  const [dataset, setDataset] = useState(first.id);
  const [start, setStart] = useState(preset?.start ?? parent?.query.start ?? day(end, -7));
  const [last, setLast] = useState(
    preset?.end ? lastDay(preset.end) : parent ? lastDay(parent.query.end_exclusive) : lastDay(end),
  );
  const [comparison, setComparison] = useState<Comparison>(
    comparisonOf(preset?.comparison ?? parent?.query.comparison),
  );
  const [compareStart, setCompareStart] = useState(parent?.query.compare_start ?? '');
  const [compareLast, setCompareLast] = useState(
    parent?.query.compare_end_exclusive ? lastDay(parent.query.compare_end_exclusive) : '',
  );
  const [skus, setSkus] = useState(
    preset
      ? preset.skus.split(',').filter(Boolean).join(', ')
      : (parent?.query.skus.join(', ') ?? ''),
  );
  const [model, setModel] = useState(
    parent ? (parent.model_config_id ?? '') : (models.find(m => m.is_default)?.id ?? ''),
  );
  const [minOrders, setMinOrders] = useState(parent?.rules.min_orders ?? 20);
  const [reportLanguage, setReportLanguage] = useState(parent?.language ?? getLanguage());
  const [key, setKey] = useState({ body: '', value: crypto.randomUUID() });
  const create = useMutation({
    mutationFn: (body: string) => {
      // Resubmitting the same body reuses its idempotency key, so a retry never duplicates.
      const token = key.body === body ? key.value : crypto.randomUUID();
      setKey({ body, value: token });
      return api<Report>('/reports', {
        method: 'POST',
        headers: { 'Idempotency-Key': token },
        body,
      });
    },
    onSuccess: r => navigate(`/reports/${r.id}`),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const input: ReportInput = {
      title,
      query: {
        dataset_id: dataset,
        start,
        end_exclusive: day(last, 1),
        comparison,
        compare_start: comparison === 'custom' ? compareStart : null,
        compare_end_exclusive: comparison === 'custom' ? day(compareLast, 1) : null,
        skus: skus
          .split(/[,，]/)
          .map(s => s.trim())
          .filter(Boolean),
        granularity: 'day',
      },
      model_config_id: model || null,
      parent_id: parent?.id ?? null,
      rules: { ...(parent?.rules ?? {}), min_orders: minOrders },
      language: reportLanguage === 'en' ? 'en' : 'zh',
    };
    create.mutate(JSON.stringify(input));
  }
  return (
    <div className={css.reports}>
      <Link className={cx(ui.backLink, forms.backLink)} to="/reports">
        <ArrowLeft size={15} />
        {t('返回周报中心')}
      </Link>
      <section className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{parent ? t('创建报告修订') : t('生成经营周报')}</h1>
          <p>{parent ? t('保留原报告，生成新修订。') : t('选择数据与周期，模型可选。')}</p>
        </div>
      </section>
      <section className={cx(css.panel, ui.panel, css.reportForm)}>
        <form onSubmit={submit}>
          <fieldset disabled={create.isPending}>
            <label className={cx(ui.field, forms.field)}>
              {t('报告标题')}
              <input
                required
                maxLength={150}
                value={title}
                onChange={e => setTitle(e.target.value)}
              />
            </label>
            <label className={cx(ui.field, forms.field)}>
              {t('订单数据版本')}
              <select value={dataset} onChange={e => setDataset(e.target.value)}>
                {versions.map(v => (
                  <option key={v.id} value={v.id}>
                    {v.name} · {v.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
              <label className={cx(ui.field, forms.field)}>
                {t('本期开始日期')}
                <input
                  type="date"
                  required
                  value={start}
                  onChange={e => setStart(e.target.value)}
                />
              </label>
              <label className={cx(ui.field, forms.field)}>
                {t('本期结束日期（含当日）')}
                <input
                  type="date"
                  required
                  min={start}
                  value={last}
                  onChange={e => setLast(e.target.value)}
                />
              </label>
            </div>
            <label className={cx(ui.field, forms.field)}>
              {t('比较周期')}
              <select
                value={comparison}
                onChange={e => setComparison(comparisonOf(e.target.value))}
              >
                <option value="previous">{t('上一等长周期')}</option>
                <option value="custom">{t('自定义比较期')}</option>
                <option value="none">{t('不比较')}</option>
              </select>
            </label>
            {comparison === 'custom' && (
              <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
                <label className={cx(ui.field, forms.field)}>
                  {t('比较开始日期')}
                  <input
                    type="date"
                    required
                    value={compareStart}
                    onChange={e => setCompareStart(e.target.value)}
                  />
                </label>
                <label className={cx(ui.field, forms.field)}>
                  {t('比较结束日期（含当日）')}
                  <input
                    type="date"
                    required
                    min={compareStart}
                    value={compareLast}
                    onChange={e => setCompareLast(e.target.value)}
                  />
                </label>
              </div>
            )}
            <label className={cx(ui.field, forms.field)}>
              {t('SKU 范围')}
              <input
                value={skus}
                onChange={e => setSkus(e.target.value)}
                placeholder={t('留空分析全部商品；多个 SKU 用逗号分隔')}
              />
            </label>
            <label className={cx(ui.field, forms.field)}>
              {t('分析模型')}
              <select value={model} onChange={e => setModel(e.target.value)}>
                <option value="">{t('无需模型 · 确定性摘要')}</option>
                {models.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.capabilities?.usable ? '' : t('（未验证或不可用，将降级）')}
                  </option>
                ))}
              </select>
            </label>
            <p className={cx(ui.formHint, forms.formHint)}>
              {t('使用模型可能产生费用，按已授权范围发送数据。')}
              <Link to="/settings/models">{t('管理模型')}</Link>
            </p>
            {models.find(m => m.id === model)?.consent_current === false && (
              <p className={cx(ui.reportWarning, 'report-warning')}>
                {t(
                  '所选模型仍使用 1.x 的授权范围：本报告的追问只发送问题主题，商家备注不会发送给模型。可先在模型设置中确认新的授权范围。',
                )}
              </p>
            )}
            <label className={cx(ui.field, forms.field)}>
              {t('报告语言')}
              <select
                value={reportLanguage}
                onChange={e => setReportLanguage(e.target.value === 'en' ? 'en' : 'zh')}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </label>
            <details className={css.reportRuleOptions}>
              <summary>{t('异常规则与样本量')}</summary>
              <label className={cx(ui.field, forms.field)}>
                {t('两期最低订单量')}
                <input
                  type="number"
                  min={20}
                  max={1000}
                  required
                  value={minOrders}
                  onChange={e => setMinOrders(Number(e.target.value))}
                />
              </label>
              <p>
                {t(
                  '默认检查销售变化 20%、退款占比 10%、毛利率下降 5 个百分点、负毛利、销售集中和日离群。阈值随报告冻结；样本不足会明确标注。',
                )}
              </p>
            </details>
            <ErrorNotice error={create.error} />
            <div className={cx(ui.formActions, forms.formActions)}>
              <button className={cx(css.primary, ui.primary)}>
                {create.isPending ? (
                  <LoaderCircle className={ui.spin} size={16} />
                ) : (
                  <FileBarChart2 size={16} />
                )}
                {t('开始生成')}
              </button>
            </div>
          </fieldset>
        </form>
      </section>
    </div>
  );
}
