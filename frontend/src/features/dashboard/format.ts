import { locale, t } from '../../lib/i18n';
export type Metric = { value: string | null; unit: 'minor_currency' | 'count' | 'ratio'; quality: 'confirmed' | 'estimated' | 'unavailable'; unavailable_reason: string | null };
export type Change = { delta: string | null; change_rate: string | null; delta_pp: string | null; state: string; quality: string };

// Exact decimal formatting, including cost totals beyond JavaScript's safe integer range.
export function decimal(text: string, places = 2, power = 0): string {
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = text.replace(/^[+-]/, '').split('.');
  let value = BigInt(whole + fraction);
  const shift = fraction.length - power - places;
  if (shift > 0) {
    const divisor = 10n ** BigInt(shift);
    value = (value + divisor / 2n) / divisor;
  } else value *= 10n ** BigInt(-shift);
  const divisor = 10n ** BigInt(places);
  const integral = new Intl.NumberFormat('en-US').format(value / divisor);
  const suffix = places ? '.' + (value % divisor).toString().padStart(places, '0') : '';
  return (negative && value !== 0n ? '-' : '') + integral + suffix;
}

export function formatMetric(metric: Metric, currency: string, exponent: number) {
  if (metric.value === null) return '—';
  if (metric.unit === 'ratio') return decimal(metric.value, 2, 2) + '%';
  if (metric.unit === 'count') return decimal(metric.value, 0);
  const symbol = new Intl.NumberFormat(locale(), { style: 'currency', currency }).formatToParts(0).find(p => p.type === 'currency')?.value ?? currency;
  return symbol + decimal(metric.value, exponent, -exponent);
}

export const reasons: Record<string, string> = {
  COST_MISSING: '成本未全部匹配', REFUND_UNKNOWN: '累计退款未知', ZERO_DENOMINATOR: '分母为零，无法计算', INCOMPLETE_COVERAGE: '此范围没有完整数据',
};
const states: Record<string, string> = { new: '上期为零 · 新增', both_zero: '两期均为零', turned_positive: '由负转正', turned_negative: '转为负值', negative_baseline: '上期为负 · 不计算增长率', incomplete_coverage: '覆盖不完整 · 不作周期比较', unavailable: '比较数据不可用' };
export function changeText(change?: Change | null): string {
  if (!change) return t("未选择比较周期");
  if (change.delta_pp !== null) return t("{0}{1} 个百分点", Number(change.delta_pp) > 0 ? '+' : '', decimal(change.delta_pp));
  if (change.change_rate !== null) return `${Number(change.change_rate) > 0 ? '+' : ''}${decimal(change.change_rate, 2, 2)}%`;
  return t(states[change.state] ?? '—');
}
