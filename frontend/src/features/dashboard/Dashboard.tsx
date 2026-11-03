import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, Database, LoaderCircle } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { AnalysisContext } from './AnalysisContext';
import { Contributions } from './Contributions';
import { FilterForm } from './FilterForm';
import { dashboardKeys } from './keys';
import { MatchedSubset } from './MatchedSubset';
import { MetricCards } from './MetricCards';
import { MetricDefinitions } from './MetricDefinitions';
import { PAGE_SIZE, ProductTable } from './ProductTable';
import { QualityNotes } from './QualityNotes';
import { Trend } from './Trend';
import type { ProductOrder, ProductPage } from './types';
import { useDashboardQuery } from './useDashboardQuery';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

export { Contributions } from './Contributions';
export { Trend } from './Trend';
export type { Result } from './types';

export function Dashboard() {
  useLanguage();
  const {
    versions,
    selectedVersion,
    availableVersions,
    draft,
    setDraft,
    request,
    snapshotId,
    snapshot,
    offset,
    setOffset,
    validationError,
    apply,
    busy,
    dirty,
  } = useDashboardQuery();
  const [skuInput, setSkuInput] = useState('');
  const [order, setOrder] = useState<ProductOrder>({
    sort: 'net_sales',
    direction: 'desc',
    focus: 'all',
  });
  const result = snapshot.data?.result;
  const products = useQuery({
    queryKey: dashboardKeys.products(snapshotId ?? '', offset, order),
    enabled: !!result,
    queryFn: () =>
      api<ProductPage>(
        `/metrics/${snapshotId}/products?sort=${order.sort}&direction=${order.direction}&focus=${order.focus}&offset=${offset}&limit=${PAGE_SIZE}`,
      ),
  });
  const choices = useQuery({
    queryKey: dashboardKeys.skuOptions(draft?.dataset_id ?? '', skuInput),
    enabled: !!draft?.dataset_id,
    queryFn: () =>
      api<string[]>(`/datasets/${draft!.dataset_id}/skus?search=${encodeURIComponent(skuInput)}`),
  });
  const error =
    versions.error ??
    selectedVersion.error ??
    request.error ??
    snapshot.error ??
    products.error ??
    choices.error;
  return (
    <div className={css.dashboard}>
      <div className={cx(css.pageHeading, ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('经营看板')}</h1>
          <p>{t('销售、毛利与商品表现。')}</p>
        </div>
        <Link to="/data" className={cx(css.secondary, ui.secondary)}>
          <Database size={15} />
          {t('管理数据')}
        </Link>
      </div>
      <ErrorNotice error={error} />
      {versions.isPending && <p className={ui.emptyCopy}>{t('读取已发布数据版本…')}</p>}
      {versions.data?.length === 0 && (
        <section className={cx(css.panel, ui.panel, css.dashboardEmpty)}>
          <Database size={38} />
          <h2>{t('暂无经营数据')}</h2>
          <p>{t('发布订单数据后即可查看看板。')}</p>
          <Link to="/data" className={cx(css.primary, ui.primary)}>
            {t('前往导入数据')}
            <ArrowRight size={15} />
          </Link>
        </section>
      )}
      {draft && (
        <FilterForm
          draft={draft}
          setDraft={setDraft}
          versions={availableVersions}
          skuInput={skuInput}
          setSkuInput={setSkuInput}
          skuOptions={choices.data}
          dirty={dirty}
          pending={request.isPending}
          onApply={apply}
        />
      )}
      <ErrorNotice error={validationError} />
      {busy && (
        <section className={cx(css.panel, ui.panel, css.computing)} role="status">
          <LoaderCircle className={ui.spin} size={23} />
          <div>
            <strong>
              {snapshot.data?.status === 'running' ? t('正在计算经营指标') : t('指标任务已提交')}
            </strong>
            <p>{t('计算完成后自动显示。')}</p>
          </div>
        </section>
      )}
      {snapshot.data?.status === 'failed' && (
        <section className={cx(css.panel, ui.panel)}>
          <h2>{t('指标计算未完成')}</h2>
          <p className={ui.formHint}>
            {t('请确认 worker 与数据库正常，或缩小时间/商品范围后重试。错误代码：')}
            {snapshot.data.error_code}
          </p>
          <button className={cx(css.secondary, ui.secondary)} onClick={() => draft && apply(draft)}>
            {t('重新计算')}
          </button>
        </section>
      )}
      {result && (
        <>
          <AnalysisContext result={result} />
          {!!result.warnings.length && <QualityNotes codes={result.warnings} />}
          <MetricCards result={result} />
          {result.current.quality.missing_cost_rows > 0 && <MatchedSubset result={result} />}
          <div className={css.dashboardCharts}>
            <Trend key={snapshotId} result={result} />
            <Contributions result={result} />
          </div>
          <ProductTable
            result={result}
            page={products.data}
            loading={products.isPending}
            order={order}
            offset={offset}
            onOrder={setOrder}
            onOffset={setOffset}
            onSku={sku => draft && apply({ ...draft, skus: [sku] })}
          />
          <MetricDefinitions result={result} />
        </>
      )}
    </div>
  );
}
