import { t, useLanguage } from '../../lib/i18n';
import type { Config, Options, Version } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = {
  config: Config;
  onChange: (next: Config) => void;
  option: <K extends keyof Options>(key: K, value: Options[K]) => void;
  costs: Version[] | undefined;
  statusMapping: string;
  onStatusMapping: (value: string) => void;
};

/** Order-only definitions: money scope, payment and refund handling, costs and coverage. */
export function OrderOptions(props: Props) {
  useLanguage();
  const { config, onChange, option, costs, statusMapping, onStatusMapping } = props;
  const o = config.options;
  return (
    <>
      <div className={cx(ui.formGrid, forms.formGrid)}>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('输入金额单位')}
          <select
            aria-label={t('输入金额单位')}
            value={o.input_money_unit}
            onChange={e => option('input_money_unit', e.target.value)}
          >
            <option value="major">{t('元（主货币单位）')}</option>
            <option value="minor">{t('分（最小货币单位）')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('金额层级')}
          <select
            aria-label={t('金额层级')}
            value={o.amount_scope}
            onChange={e => option('amount_scope', e.target.value)}
          >
            <option value="line_goods_excluding_shipping">{t('明细商品实付，不含运费')}</option>
            <option value="order_goods">{t('订单商品总额，按权重分摊')}</option>
            <option value="order_with_shipping">{t('订单总额含运费，扣除后分摊')}</option>
            <option value="derived">{t('单价 × 数量 − 明细优惠')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('支付状态口径')}
          <select
            aria-label={t('支付状态口径')}
            value={o.payment_state_mode}
            onChange={e => option('payment_state_mode', e.target.value)}
          >
            <option value="mapped">{t('按源表字段映射')}</option>
            <option value="confirmed_all_paid">{t('确认文件中全部已支付')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('退款数据')}
          <select
            aria-label={t('退款数据')}
            value={o.refund_mode}
            onChange={e => option('refund_mode', e.target.value)}
          >
            <option value="unknown">{t('未知（净值指标不可用）')}</option>
            <option value="provided">{t('已提供累计商品退款')}</option>
            <option value="confirmed_none">{t('确认覆盖范围内无退款')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('退款层级')}
          <select
            aria-label={t('退款层级')}
            value={o.refund_scope}
            onChange={e => option('refund_scope', e.target.value)}
          >
            <option value="line">{t('明细退款')}</option>
            <option value="order">{t('订单退款，按实付分摊（估算）')}</option>
          </select>
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('关联成本版本')}
          <select
            aria-label={t('关联成本版本')}
            value={config.cost_version_id ?? ''}
            onChange={e => onChange({ ...config, cost_version_id: e.target.value || null })}
          >
            <option value="">{t('暂不关联（成本缺失）')}</option>
            {costs?.map(v => (
              <option key={v.id} value={v.id}>
                {v.name} · {v.row_count} {t('行 ·')}
                {v.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {o.payment_state_mode === 'mapped' && (
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('支付状态映射')}
          <textarea
            aria-label={t('支付状态映射')}
            rows={3}
            value={statusMapping}
            placeholder={t('已付款=paid\n待付款=unpaid\n已取消=cancelled_unpaid')}
            onChange={e => onStatusMapping(e.target.value)}
          />
          <span className={cx(ui.formHint, forms.formHint)}>
            {t('每行：源表状态=paid / unpaid / cancelled_unpaid')}
          </span>
        </label>
      )}
      <div className={cx(ui.formGrid, forms.formGrid, css.threeCols)}>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('覆盖开始')}
          <input
            aria-label={t('覆盖开始')}
            placeholder="2026-09-21T00:00:00+08:00"
            value={o.coverage_start}
            onChange={e => option('coverage_start', e.target.value)}
          />
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('覆盖结束（不含）')}
          <input
            aria-label={t('覆盖结束（不含）')}
            placeholder="2026-10-05T00:00:00+08:00"
            value={o.coverage_end_exclusive}
            onChange={e => option('coverage_end_exclusive', e.target.value)}
          />
        </label>
        <label className={cx(css.field, ui.field, forms.field)}>
          {t('数据截止时间')}
          <input
            aria-label={t('数据截止时间')}
            placeholder="2026-10-07T00:00:00+08:00"
            value={o.source_as_of}
            onChange={e => option('source_as_of', e.target.value)}
          />
        </label>
      </div>
      <label className={cx(ui.checkField, forms.checkField)}>
        <input
          type="checkbox"
          checked={o.coverage_confirmed}
          onChange={e => option('coverage_confirmed', e.target.checked)}
        />
        {t('我确认文件完整覆盖以上区间，退款为截止时间的累计值。')}
      </label>
    </>
  );
}
