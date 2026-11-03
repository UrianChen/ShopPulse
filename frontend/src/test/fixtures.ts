import type { Content, Report } from '../features/reports/types';

const money = (value: string) =>
  ({ value, unit: 'minor_currency', quality: 'confirmed', unavailable_reason: null }) as const;

export const metricsEvidence = 'ev-metrics';

export function content(overrides: Partial<Content> = {}): Content {
  return {
    generation_mode: 'native_tools',
    summary: [{ text: '本期净销售额为 CNY 550.00。', evidence_refs: [metricsEvidence] }],
    // Charts are stubbed in component tests; the cards only need currency and comparison.
    metrics: {
      currency: 'CNY',
      currency_exponent: 2,
      comparison: null,
    } as unknown as Content['metrics'],
    metric_cards: [
      { key: 'net_sales', label: '净销售额', metric: money('55000'), evidence_id: metricsEvidence },
    ],
    snapshot: { model: null },
    products: [],
    anomalies: { findings: [], checks: [] },
    findings: [
      {
        id: 'f_refund',
        title: '退款',
        observation: { text: '退款最多的商品是 A。', evidence_refs: ['ev-refunds'] },
        supporting: [],
        hypotheses: ['可能与质量问题有关'],
        limitations: [],
        evidence_refs: ['ev-refunds'],
        supported_hypotheses: [
          {
            id: 'h_refund',
            text: '退款集中在单个商品上。',
            quality: 'confirmed',
            evidence_id: 'ev-verdict',
            test_evidence_id: 'ev-refunds',
          },
        ],
      },
    ],
    recommendations: [
      {
        action: '核对 A 的退款原因',
        priority: 'high',
        effort: 'small',
        verification_metric: 'refund_amount_rate',
        suggested_review_window: 'next_week',
        rationale_finding_ids: ['f_refund'],
      },
    ],
    limitations: ['观察到的变化不能证明原因。'],
    warnings: [],
    evidence_index: [
      { evidence_id: metricsEvidence, tool: 'calculate_metrics', result_hash: 'h', run_id: 'r' },
    ],
    hypotheses: [
      {
        id: 'h_refund',
        statement: '退款集中在单个商品上。',
        state: 'supported',
        reason: null,
        quality: 'confirmed',
        wave: 0,
        evidence_id: 'ev-verdict',
        test_evidence_id: 'ev-refunds',
      },
      {
        id: 'h_mix',
        statement: '毛利率的变化主要来自商品结构变化。',
        state: 'refuted',
        reason: null,
        quality: 'estimated',
        wave: 1,
        evidence_id: 'ev-mix',
        test_evidence_id: 'ev-split',
      },
      {
        id: 'h_sku',
        statement: '该商品的净销售额较比较期下降。',
        state: 'inconclusive',
        reason: 'LOW_SAMPLE',
        quality: 'confirmed',
        wave: 2,
        evidence_id: 'ev-sku',
        test_evidence_id: 'ev-drill',
      },
    ],
    ruled_out: [
      {
        hypothesis_id: 'h_mix',
        statement: '毛利率的变化主要来自商品结构变化。',
        text: '数据不支持该解释。',
        evidence_refs: ['ev-mix', 'ev-split'],
      },
    ],
    ...overrides,
  };
}

export function report(overrides: Partial<Report> = {}): Report {
  return {
    id: 'r1',
    title: '黄金周报',
    status: 'ready',
    revision: 1,
    series_id: 's1',
    parent_id: null,
    language: 'zh',
    dataset_id: 'd1234567-0000',
    model_config_id: null,
    generation_mode: 'native_tools',
    job_id: 'j1',
    job_status: 'succeeded',
    schedule_id: null,
    created_at: '2026-10-05T00:00:00Z',
    error_code: null,
    query: {
      dataset_id: 'd1234567-0000',
      start: '2026-09-28',
      end_exclusive: '2026-10-05',
      comparison: 'previous',
      compare_start: '2026-09-21',
      compare_end_exclusive: '2026-09-28',
      skus: [],
      granularity: 'day',
    } as Report['query'],
    rules: { min_orders: 20 },
    content: content(),
    ...overrides,
  };
}
