import type { Refine, ReportInput, Schema } from '../../lib/types';
import type { Result } from '../dashboard/Dashboard';
import type { Metric } from '../dashboard/format';

export type Sentence = { text: string; evidence_refs: string[] };
export type Evidence = { evidence_id: string; tool: string; result_hash: string; run_id: string };
export type SupportedHypothesis = {
  id: string;
  text: string | null;
  quality: string;
  evidence_id: string;
  test_evidence_id: string;
};
export type Finding = {
  id: string;
  title: string;
  observation: Sentence;
  supporting?: Sentence[];
  hypotheses: string[];
  limitations: string[];
  evidence_refs: string[];
  supported_hypotheses?: SupportedHypothesis[];
};
export type Hypothesis = {
  id: string;
  statement: string | null;
  state: string;
  reason: string | null;
  quality: string;
  wave: number;
  evidence_id: string;
  test_evidence_id: string;
};
export type Recheck = {
  id: string;
  statement: string | null;
  previous_state: string;
  state: string;
  reason: string | null;
  evidence_id: string;
};
export type RuledOut = {
  hypothesis_id: string;
  statement: string | null;
  text: string;
  evidence_refs: string[];
};
export type HistoryWindow = {
  start: string;
  end_exclusive: string;
  coverage_complete: boolean;
  metrics: Record<string, Metric>;
};
export type History = {
  evidence_id: string;
  window_days: number;
  windows: HistoryWindow[];
  streaks: Record<string, { direction: string; periods: number }>;
};
export type Recommendation = {
  action: string;
  priority: string;
  effort: string;
  verification_metric: string;
  suggested_review_window: string;
  evidence_refs?: string[];
  rationale_finding_ids?: string[];
};
export type Followup = {
  action_id: string;
  action_text: string;
  verification_metric: string;
  state: string;
  reason: string | null;
  baseline: Metric | null;
  current: Metric | null;
  change_rate: string | null;
  source_period: [string, string];
};
export type MerchantNote = {
  id: string;
  start: string;
  end_exclusive: string;
  kind: string;
  text: string;
};
export type Content = {
  generation_mode: string;
  model_error_code?: string;
  summary: Sentence[];
  metrics: Result;
  metric_cards: { key: string; label: string; metric: Metric; evidence_id: string }[];
  snapshot: Record<string, unknown>;
  products: {
    sku: string | null;
    product_name: string;
    current: { metrics: Record<string, Metric> };
  }[];
  anomalies: {
    findings: { code: string; values: unknown; limitation: string }[];
    checks: { code: string; state: string; limitation: string }[];
  };
  findings: Finding[];
  recommendations: Recommendation[];
  limitations: string[];
  warnings: string[];
  evidence_index: Evidence[];
  language?: string;
  action_followups?: Followup[];
  merchant_notes?: MerchantNote[];
  hypotheses?: Hypothesis[];
  hypothesis_recheck?: Recheck[];
  ruled_out?: RuledOut[];
  history?: History | null;
};
/** A report as listed by `/reports`. */
export type ReportSummary = Refine<
  Schema<'Report'>,
  { query: Result['query']; rules: NonNullable<ReportInput['rules']> }
>;
/** A report with its content, as returned by `/reports/{id}`. */
export type Report = ReportSummary & { content: Content | null };
export type SuggestedQuery = {
  start: string;
  end_exclusive: string;
  comparison: string;
  skus: string[];
};
export type Message = Refine<
  Schema<'ReportMessage'>,
  {
    answer: {
      generation_mode: string;
      kind?: string;
      message: string | null;
      summary: Sentence[];
      options?: string[];
      suggested_query?: SuggestedQuery | null;
      analysis: { findings: Finding[]; recommendations: Recommendation[] } | null;
      limitations: string[];
      error_code: string | null;
      new_analysis_required: boolean;
      evidence_index: Evidence[];
    } | null;
  }
>;
export type Step = {
  phase: string;
  tool?: string;
  ok?: boolean;
  code?: string | null;
  error?: string | null;
  reason?: string | null;
  codes?: string[];
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  tool_calls?: string[];
  id?: string;
  state?: string;
  mode?: string | null;
  wave?: number;
  lint?: string[];
  model?: string[] | string | null;
  applied?: boolean;
  supported?: number;
  refuted?: number;
  inconclusive?: number;
};
export type Run = Refine<Schema<'AgentRun'>, { steps: Step[]; usage: Record<string, number> }>;
/** Opens a piece of evidence in the drawer. */
export type OnEvidence = (id: string) => void;
