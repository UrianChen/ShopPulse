import { t } from '../../lib/i18n';

export const metricNames: Record<string, string> = {
  net_sales: '净销售额',
  gross_profit: '商品毛利',
  refund_amount_rate: '累计退款占比',
  paid_orders: '支付订单量',
};
export const followupStates: Record<string, string> = {
  improved: '已改善',
  not_improved: '未改善',
  insufficient_data: '数据不足',
};
export const statusNames: Record<string, string> = {
  open: '待处理',
  done: '已完成',
  dismissed: '已忽略',
};
export const priorityNames: Record<string, string> = {
  high: '优先核查',
  medium: '建议跟进',
  low: '持续观察',
};
export const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
export const formats: Record<string, string> = {
  generic: '通用 JSON',
  slack: 'Slack',
  feishu: '飞书',
  wecom: '企业微信',
  dingtalk: '钉钉',
};
export const noteKinds: Record<string, string> = {
  promotion: '促销',
  holiday: '节假日',
  stockout: '缺货',
  pricing: '调价',
  other: '其他',
};
const scheduleStates: Record<string, string> = {
  CREATED: '已生成报告',
  NO_NEW_DATA: '没有新数据，已跳过',
  NO_DATASET: '没有可用数据版本',
  ALREADY_CREATED: '本期已生成',
  NOTIFIED: '已推送通知',
  FAILED: '执行失败',
  DATASET_DELETED: '数据版本已删除，已停用',
  BUSY: '正在执行',
  NOT_DUE: '未到执行时间',
};

// Prefix of every `keys.actions(status)` list, so one save refreshes all status filters.
export const allActions = ['actions'] as const;

export function stateText(value: string | null) {
  if (!value) return t('尚未执行');
  if (value.startsWith('NOTIFY_FAILED')) return `${t('推送失败')} · ${value.split(':')[1] ?? ''}`;
  return t(scheduleStates[value] ?? value);
}
