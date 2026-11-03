// Interface labels for server codes. Values are translation keys (see src/lib/messages.ts).
import { t } from '../../lib/i18n';
import type { Content, Step, SuggestedQuery } from './types';

export const DONE = ['ready', 'ready_with_warnings', 'failed'];
export const modes: Record<string, string> = {
  deterministic: '确定性摘要',
  native_tools: '模型辅助 · 原生工具',
  restricted_json: '模型辅助 · 受限 JSON',
  narrative: '模型辅助 · 固定分析流程',
};
export const states: Record<string, string> = {
  queued: '等待执行',
  computing: '计算指标',
  analyzing: '分析与校验中',
  ready: '已完成',
  ready_with_warnings: '已完成 · 请查看限制',
  failed: '执行失败',
  running: '正在回答',
};
export const ruleNames: Record<string, string> = {
  SALES_CHANGE: '净销售额波动',
  HIGH_REFUND: '退款占比偏高',
  MARGIN_DROP: '毛利率下降',
  NEGATIVE_PROFIT: '负毛利商品',
  CONCENTRATION: '销售集中',
  DAILY_MAD: '日销售离群',
};
export const toolNames: Record<string, string> = {
  get_data_quality: '数据质量检查',
  calculate_metrics: '经营指标计算',
  get_sales_trend: '销售趋势',
  rank_products: '商品排行',
  compare_periods: '周期比较',
  decompose_sales_change: '销售贡献分解',
  detect_anomalies: '确定性异常检测',
  inspect_sku: 'SKU 下钻',
  refund_breakdown: '退款拆解',
  cost_coverage: '成本覆盖检查',
  explain_metric: '指标口径说明',
  check_recommendation: '上期建议复查',
  get_merchant_notes: '商家备注',
  decompose_metric_change: '结构与费率分解',
  get_history: '历史窗口',
  derive: '派生计算',
  test_hypothesis: '假设检验',
  recheck_hypotheses: '上期结论复核',
};
export const hypothesisStates: Record<string, string> = {
  supported: '数据支持',
  refuted: '已被排除',
  inconclusive: '无法判断',
};
export const hypothesisReasons: Record<string, string> = {
  LOW_SAMPLE: '订单样本偏少',
  UNAVAILABLE_VALUE: '所需数值不可用',
  NOT_FOUND: '未找到对应商品或日期',
  NOT_PRESENT: '该商品在本期没有对应数值',
  ZERO_VALUE: '变化为零',
  ZERO_BASE: '分母为零',
  NEGATIVE_BASE: '分母为负',
  SIGN_MISMATCH: '方向不一致',
};
export const directions: Record<string, string> = { up: '上升', down: '下降', flat: '持平' };
export const metricNames: Record<string, string> = {
  net_sales: '净销售额',
  gross_profit: '商品毛利',
  refund_amount_rate: '累计退款占比',
  paid_orders: '支付订单量',
  aov: '净客单价',
};
export const qualityNames: Record<string, string> = {
  SMALL_SAMPLE: '本期少于二十单，变化仅供观察',
  INCOMPLETE_COVERAGE: '本期数据覆盖不完整',
  COMPARISON_INCOMPLETE: '比较期数据覆盖不完整',
  COST_MISSING: '部分商品缺少成本，整体毛利不可用',
  RESTOCK_ESTIMATED: '退款回库未知，毛利为估算',
  REFUND_UNKNOWN: '累计退款未知，净值不可用',
  REFUND_ALLOCATED: '退款经过分摊，相关商品净值为估算',
};
export const followupReasons: Record<string, string> = {
  SCOPE_CHANGED: '分析范围不同，无法比较',
  CURRENCY_CHANGED: '币种不同，无法比较',
  VALUE_UNAVAILABLE: '指标值不可用',
};
const phaseNames: Record<string, string> = {
  computing: '计算核心指标',
  analyzing: '模型分析',
  plan: '开始规划',
  model: '模型请求',
  tool: '工具调用',
  repair: '校验未通过，要求修复',
  finalize: '结束工具调用',
  compact: '压缩上下文',
  validated: '证据校验通过',
  validating: '最终校验',
  completed: '完成',
  test: '假设检验',
  hypotheses: '本轮假设检验完成',
  review: '审稿检查',
  review_repair: '审稿后局部修复',
  fallback: '回退到工具调用流程',
};
const repairModes: Record<string, string> = { patch: '局部修复', full: '整体重写' };
const finalizeReasons: Record<string, string> = {
  no_new_evidence: '没有新证据',
  round_limit: '达到轮次上限',
  budget: '接近预算上限',
};

export function stepText(s: Step) {
  const parts = [t(phaseNames[s.phase] ?? s.phase)];
  if (s.tool) parts.push(toolNames[s.tool] ? `${t(toolNames[s.tool])} (${s.tool})` : s.tool);
  if (s.code) parts.push(s.code);
  if (s.error) parts.push(s.error);
  if (s.id) parts.push(s.id);
  if (s.state) parts.push(t(hypothesisStates[s.state] ?? s.state));
  if (s.reason) parts.push(t(finalizeReasons[s.reason] ?? hypothesisReasons[s.reason] ?? s.reason));
  if (s.phase === 'hypotheses')
    parts.push(
      (['supported', 'refuted', 'inconclusive'] as const)
        .filter(k => s[k])
        .map(k => `${t(hypothesisStates[k])} ${s[k]}`)
        .join(' / '),
    );
  if (s.phase === 'repair' && s.mode) parts.push(t(repairModes[s.mode] ?? s.mode));
  if (s.lint?.length) parts.push(s.lint.join(', '));
  if (s.phase === 'review_repair') parts.push(s.applied ? t('已采纳') : t('保留原稿'));
  if (s.codes?.length) parts.push(s.codes.join(', '));
  if (s.tool_calls?.length) parts.push('→ ' + s.tool_calls.join(', '));
  if (s.latency_ms !== undefined) parts.push(`${s.latency_ms} ms`);
  return parts.join(' · ');
}

export function suggestedLink(reportId: string, query?: SuggestedQuery | null) {
  if (!query) return `/reports/new?parent=${reportId}`;
  const params = new URLSearchParams({
    parent: reportId,
    start: query.start,
    end: query.end_exclusive,
    comparison: query.comparison,
    skus: query.skus.join(','),
  });
  return `/reports/new?${params}`;
}

export function signedPercent(value: string) {
  const number = Number(value) * 100;
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
}

export function limitedConsent(content: Content) {
  // Each report keeps the consent frozen when it was created; v1 scopes never send question text.
  const model = content.snapshot.model as { consent?: { fields?: string[] } } | null | undefined;
  return !!model && !(model.consent?.fields ?? []).includes('question_text');
}
