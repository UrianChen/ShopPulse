import type { Dispatch, FormEvent, SetStateAction } from 'react';
import { RefreshCw, SlidersHorizontal, X } from 'lucide-react';
import { day } from '../../lib/dates';
import { t, useLanguage } from '../../lib/i18n';
import type { DatasetVersion } from '../../lib/types';
import { comparisonOf, defaults, inputEnd } from './query';
import type { Query } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './dashboard.module.css';

type Props = {
  draft: Query;
  setDraft: Dispatch<SetStateAction<Query | null>>;
  versions: DatasetVersion[];
  skuInput: string;
  setSkuInput: (value: string) => void;
  skuOptions: string[] | undefined;
  dirty: boolean;
  pending: boolean;
  onApply: (q: Query) => void;
};

export function FilterForm({
  draft,
  setDraft,
  versions,
  skuInput,
  setSkuInput,
  skuOptions,
  dirty,
  pending,
  onApply,
}: Props) {
  useLanguage();
  function update<K extends keyof Query>(key: K, v: Query[K]) {
    setDraft(d => d && { ...d, [key]: v });
  }
  function addSku() {
    const s = skuInput.trim();
    if (s && !draft.skus.includes(s) && draft.skus.length < 100) {
      update('skus', [...draft.skus, s]);
      setSkuInput('');
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    onApply(draft);
  }
  return (
    <form
      className={cx(css.panel, ui.panel, css.dashboardFilters, 'dashboard-filters')}
      onSubmit={submit}
    >
      <div className={cx(css.panelTitle, ui.panelTitle)}>
        <h2>
          <SlidersHorizontal size={17} /> {t('分析范围')}
        </h2>
        <span></span>
      </div>
      <div className={css.filterGrid}>
        <label className={cx(css.field, ui.field, css.versionSelect)}>
          {t('数据版本')}
          <select
            aria-label={t('数据版本')}
            value={draft.dataset_id}
            onChange={e => {
              const v = versions.find(v => v.id === e.target.value)!;
              setDraft(defaults(v));
              setSkuInput('');
            }}
          >
            <option value="" disabled>
              {t('选择已发布版本')}
            </option>
            {versions.map(v => (
              <option key={v.id} value={v.id}>
                {v.name} · {v.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label className={cx(css.field, ui.field)}>
          {t('开始日期')}
          <input
            aria-label={t('开始日期')}
            type="date"
            min="1900-01-01"
            max="2100-12-31"
            required
            value={draft.start}
            onChange={e => update('start', e.target.value)}
          />
        </label>
        <label className={cx(css.field, ui.field)}>
          {t('结束日期（含当日）')}
          <input
            aria-label={t('结束日期（含当日）')}
            type="date"
            min="1900-01-01"
            max="2100-12-31"
            required
            value={inputEnd(draft.end_exclusive)}
            onChange={e => update('end_exclusive', e.target.value ? day(e.target.value, 1) : '')}
          />
        </label>
        <label className={cx(css.field, ui.field)}>
          {t('比较周期')}
          <select
            aria-label={t('比较周期')}
            value={draft.comparison}
            onChange={e => update('comparison', comparisonOf(e.target.value) ?? 'previous')}
          >
            <option value="previous">{t('上一等长周期')}</option>
            <option value="custom">{t('自定义比较')}</option>
            <option value="none">{t('不比较')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field)}>
          {t('趋势粒度')}
          <select
            aria-label={t('趋势粒度')}
            value={draft.granularity}
            onChange={e => update('granularity', e.target.value === 'week' ? 'week' : 'day')}
          >
            <option value="day">{t('按日')}</option>
            <option value="week">{t('按周')}</option>
          </select>
        </label>
        {draft.comparison === 'custom' && (
          <>
            <label className={cx(css.field, ui.field)}>
              {t('比较开始')}
              <input
                aria-label={t('比较开始')}
                type="date"
                required
                value={draft.compare_start ?? ''}
                onChange={e => update('compare_start', e.target.value)}
              />
            </label>
            <label className={cx(css.field, ui.field)}>
              {t('比较结束（含当日）')}
              <input
                aria-label={t('比较结束（含当日）')}
                type="date"
                required
                value={inputEnd(draft.compare_end_exclusive)}
                onChange={e =>
                  update('compare_end_exclusive', e.target.value ? day(e.target.value, 1) : null)
                }
              />
            </label>
          </>
        )}
      </div>
      <div className={css.skuControls}>
        <label className={cx(css.field, ui.field)}>
          {t('SKU 筛选')}
          <div className={css.skuInput}>
            <input
              aria-label={t('SKU 筛选')}
              list="dashboard-skus"
              value={skuInput}
              maxLength={128}
              placeholder={t('输入 SKU，留空查看全部')}
              onChange={e => setSkuInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addSku();
                }
              }}
            />
            <button type="button" className={cx(css.secondary, ui.secondary)} onClick={addSku}>
              {t('添加')}
            </button>
          </div>
        </label>
        <datalist id="dashboard-skus">
          {skuOptions?.map(s => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <div className={cx(css.skuChips, 'sku-chips')}>
          {draft.skus.map(s => (
            <button
              type="button"
              key={s}
              onClick={() =>
                update(
                  'skus',
                  draft.skus.filter(v => v !== s),
                )
              }
            >
              {s}
              <X size={12} />
            </button>
          ))}
        </div>
        <div className={css.filterActions}>
          <span>{dirty ? t('筛选已修改，点击更新') : t('按店铺时区 · 最多 366 天')}</span>
          <button className={cx(css.primary, ui.primary)} disabled={pending} type="submit">
            <RefreshCw size={15} />
            {t('更新看板')}
          </button>
        </div>
      </div>
    </form>
  );
}
