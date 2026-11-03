import { t, useLanguage } from '../../lib/i18n';
import { LoaderCircle, ShieldCheck } from 'lucide-react';
import { OrderOptions } from './OrderOptions';
import type { Config, Options, Version } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = {
  config: Config;
  onChange: (next: Config) => void;
  isOrder: boolean;
  costs: Version[] | undefined;
  statusMapping: string;
  onStatusMapping: (value: string) => void;
  busy: boolean;
  locked: boolean;
  onSave: () => void;
};

/** Step 02: the money, time and payment definitions frozen with the version. */
export function OptionsSection(props: Props) {
  useLanguage();
  const { config, onChange, isOrder, busy, locked, onSave } = props;
  function option<K extends keyof Options>(key: K, value: Options[K]) {
    onChange({ ...config, options: { ...config.options, [key]: value } });
  }
  const o = config.options;
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{t('02 · 确认数据口径')}</h2>
          <p>{t('金额与时间含义将随数据版本冻结，不由模型推断。')}</p>
        </div>
        <ShieldCheck size={20} />
      </div>
      <fieldset disabled={busy || locked}>
        <div className={cx(ui.formGrid, forms.formGrid)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('时区')}
            <input
              aria-label={t('时区')}
              value={o.timezone}
              onChange={e => option('timezone', e.target.value)}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('币种')}
            <input
              aria-label={t('币种')}
              value={o.currency}
              maxLength={3}
              onChange={e => option('currency', e.target.value.toUpperCase())}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('币种小数位')}
            <input
              aria-label={t('币种小数位')}
              type="number"
              min={0}
              max={4}
              value={o.currency_exponent}
              onChange={e => option('currency_exponent', Number(e.target.value))}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('十进制符号')}
            <select
              value={o.decimal_separator}
              onChange={e => option('decimal_separator', e.target.value)}
            >
              <option value=".">{t('小数点 .')}</option>
              <option value=",">{t('小数逗号 ,')}</option>
            </select>
          </label>
        </div>
        {isOrder ? (
          <OrderOptions
            config={config}
            onChange={onChange}
            option={option}
            costs={props.costs}
            statusMapping={props.statusMapping}
            onStatusMapping={props.onStatusMapping}
          />
        ) : (
          <>
            <p className={cx(ui.formHint, forms.formHint)}>
              {t(
                '单位成本以主货币单位输入，最多 6 位小数；按照订单支付时间匹配。同 SKU 生效区间不可重叠。',
              )}
            </p>
            <div className={cx(ui.formGrid, forms.formGrid)}>
              <label className={cx(css.field, ui.field, forms.field)}>
                {t('静态成本生效起点')}
                <input
                  aria-label={t('静态成本生效起点')}
                  placeholder={t('源表无生效时间时必须填写')}
                  value={o.cost_effective_from}
                  onChange={e => option('cost_effective_from', e.target.value)}
                />
              </label>
              <label className={cx(css.field, ui.field, forms.field)}>
                {t('静态成本失效终点')}
                <input
                  placeholder={t('空值表示持续有效')}
                  value={o.cost_effective_to}
                  onChange={e => option('cost_effective_to', e.target.value)}
                />
              </label>
            </div>
          </>
        )}
        <label className={cx(ui.checkField, forms.checkField)}>
          <input
            type="checkbox"
            checked={o.semantics_confirmed}
            onChange={e => option('semantics_confirmed', e.target.checked)}
          />
          {t('我已核实字段映射、金额层级、币种以及')}
          {isOrder ? t('支付与退款') : t('成本')}
          {t('含义。')}
        </label>
        <button className={cx(css.primary, ui.primary)} disabled={busy || locked} onClick={onSave}>
          {busy ? <LoaderCircle size={15} className={ui.spin} /> : <ShieldCheck size={15} />}
          {t('保存并校验')}
        </button>
      </fieldset>
    </section>
  );
}
