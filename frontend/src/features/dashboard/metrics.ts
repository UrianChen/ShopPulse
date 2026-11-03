import { formatMetric } from './format';
import type { Metric } from './format';
import type { Result } from './types';

export const labels: Record<string, string> = {
  net_sales: '净销售额',
  paid_orders: '支付订单量',
  aov: '净客单价',
  gross_profit: '商品毛利',
  gross_sales: '退款前商品实付',
  refund_amount: '支付订单累计退款',
  gross_margin: '商品毛利率',
  paid_units: '支付件数',
  gross_aov: '实付客单价',
  net_cogs: '净商品成本',
  refund_amount_rate: '累计退款金额占比',
  refunded_order_rate: '发生退款订单占比',
  cost_line_coverage: '成本明细覆盖率',
  cost_amount_coverage: '成本实付金额覆盖率',
};

export function money(value: string | null, result: Result) {
  return formatMetric(
    {
      value,
      unit: 'minor_currency',
      quality: value === null ? 'unavailable' : 'confirmed',
      unavailable_reason: null,
    },
    result.currency,
    result.currency_exponent,
  );
}

export function metricText(metric: Metric, result: Result) {
  return formatMetric(metric, result.currency, result.currency_exponent);
}
