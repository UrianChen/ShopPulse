import { t, useLanguage } from '../../lib/i18n';
import { FileSpreadsheet } from 'lucide-react';
import { SourcePreview } from './SourcePreview';
import type { Config, Preview } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

const orderFields: Record<string, string> = {
  order_id: '订单编号 *',
  order_line_id: '明细编号',
  sku: '商品 SKU',
  product_name: '商品名称',
  paid_at: '支付时间 *',
  quantity: '购买数量 *',
  line_paid_minor: '商品 / 订单实付',
  line_refund_minor: '累计商品退款',
  restocked_quantity: '已回库数量',
  currency: '币种',
  payment_state: '支付状态',
  allocation_weight: '优惠前金额（分摊权重）',
  shipping_minor: '订单运费',
  unit_price: '单价（推导实付）',
  discount_minor: '明细优惠（推导实付）',
};
const costFields: Record<string, string> = {
  sku: '商品 SKU *',
  unit_cost: '单位成本 *',
  currency: '币种',
  effective_from: '生效时间',
  effective_to: '失效时间（不含）',
};

type Props = {
  config: Config;
  onChange: (next: Config) => void;
  metadata: Preview | null | undefined;
  isOrder: boolean;
  disabled: boolean;
};

/** Step 01: file parsing settings and the source-column mapping. */
export function MappingSection({ config, onChange, metadata, isOrder, disabled }: Props) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{t('01 · 解析与字段映射')}</h2>
          <p>{t('字段建议仅作参考，请根据源表确认。可输入自定义列名。')}</p>
        </div>
        <FileSpreadsheet size={20} />
      </div>
      <fieldset disabled={disabled}>
        <details className={ui.advancedSettings}>
          <summary>{t('文件解析设置')}</summary>
          <div className={cx(ui.formGrid, forms.formGrid, css.parseOptions)}>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('工作表')}
              <input
                aria-label={t('工作表')}
                list="sheet-names"
                value={config.sheet_name ?? ''}
                placeholder={t('CSV 无需填写')}
                onChange={e => onChange({ ...config, sheet_name: e.target.value || null })}
              />
              <datalist id="sheet-names">
                {metadata?.sheets.map(s => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('标题行')}
              <input
                aria-label={t('标题行')}
                type="number"
                min={1}
                max={100}
                value={config.header_row}
                onChange={e => onChange({ ...config, header_row: Number(e.target.value) })}
              />
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('CSV 编码')}
              <select
                aria-label={t('CSV 编码')}
                value={config.encoding}
                onChange={e => onChange({ ...config, encoding: e.target.value })}
              >
                <option value="utf-8-sig">UTF-8 / BOM</option>
                <option value="gb18030">GB18030</option>
              </select>
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('CSV 分隔符')}
              <select
                aria-label={t('CSV 分隔符')}
                value={config.delimiter}
                onChange={e => onChange({ ...config, delimiter: e.target.value })}
              >
                <option value=",">{t('逗号')}</option>
                <option value=";">{t('分号')}</option>
                <option value={'\t'}>{t('制表符')}</option>
              </select>
            </label>
          </div>
        </details>
        <SourcePreview data={metadata} />
        {metadata && (
          <button
            className={cx(css.textButton, ui.textButton, forms.textButton)}
            type="button"
            onClick={() =>
              onChange({
                ...config,
                columns: Object.fromEntries(
                  Object.entries(metadata.suggestions).map(([k, v]) => [k, v.column]),
                ),
              })
            }
          >
            {t('套用当前预览的字段建议')}
          </button>
        )}
        <datalist id="source-columns">
          {metadata?.columns.map(c => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <div className={css.mappingGrid}>
          {Object.entries(isOrder ? orderFields : costFields).map(([key, label]) => (
            <label className={cx(css.field, ui.field, forms.field)} key={key}>
              {t(label)}
              <input
                aria-label={t(label)}
                list="source-columns"
                placeholder={t('不映射')}
                value={config.columns[key] ?? ''}
                onChange={e => {
                  const next = { ...config.columns };
                  if (e.target.value) next[key] = e.target.value;
                  else delete next[key];
                  onChange({ ...config, columns: next });
                }}
              />
            </label>
          ))}
        </div>
      </fieldset>
    </section>
  );
}
