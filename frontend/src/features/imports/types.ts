import type { Refine, Schema } from '../../lib/types';

export type Kind = Schema<'Upload'>['kind'];

export type Preview = {
  columns: string[];
  sheets: string[];
  sheet_name: string | null;
  row_count: number;
  suggestions: Record<string, { column: string; confidence: number }>;
  preview: { row_number: number; values: Record<string, string> }[];
};

// Hand-written rather than the generated `ImportConfig`: the form edits these as plain strings
// from inputs and selects, while the generated type narrows them to enums.
export type Options = {
  timezone: string;
  currency: string;
  currency_exponent: number;
  input_money_unit: string;
  decimal_separator: string;
  amount_scope: string;
  payment_state_mode: string;
  status_mapping: Record<string, string>;
  refund_mode: string;
  refund_scope: string;
  coverage_start: string;
  coverage_end_exclusive: string;
  source_as_of: string;
  cost_effective_from: string;
  cost_effective_to: string;
  semantics_confirmed: boolean;
  coverage_confirmed: boolean;
};

export type Config = {
  sheet_name: string | null;
  header_row: number;
  encoding: string;
  delimiter: string;
  columns: Record<string, string>;
  cost_version_id: string | null;
  options: Options;
};

export type Summary = {
  source_rows: number;
  included_rows: number;
  excluded_rows: number;
  unpaid_rows: number;
  errors: number;
  unacknowledged: number;
  issue_counts: Record<string, number>;
  warning_codes: string[];
  cost_matched_rows: number;
  preview?: Preview;
};

export type Resolutions = {
  excluded_rows?: number[];
  acknowledged_codes?: string[];
  reason?: string;
};

export type Draft = Refine<
  Schema<'ImportDraft'>,
  { config: Config; summary: Summary | null; resolutions: Resolutions }
>;

export type UploadRecord = Refine<Schema<'Upload'>, { metadata: Preview | null }>;

export type Issue = Schema<'ValidationIssue'>;

/** The frozen configuration of a published version; this page reads all of it. */
type Frozen = { snapshot: { config: Config; file_sha256?: string; engine_version?: string } };

/** A published version as listed by `/datasets` and `/cost-versions`. */
export type Version = Refine<Schema<'DatasetVersion'>, Frozen>;

export type OrderVersionDetail = Refine<Schema<'DatasetDetail'>, Frozen>;

export type CostVersionDetail = Refine<Schema<'CostVersionDetail'>, Frozen>;
