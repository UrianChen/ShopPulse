import type { MetricQuery, Paged, Refine, Schema } from '../../lib/types';
import type { Change, Metric } from './format';

/** A `/metrics/query` body with every default spelled out, as kept in the filter form and URL. */
export type Query = Required<MetricQuery>;
export type Period = {
  metrics: Record<string, Metric>;
  row_count: number;
  coverage_complete: boolean;
  quality: {
    missing_cost_rows: number;
    missing_cost_skus: number;
    missing_cost_paid_minor: string;
    estimated_restock_rows: number;
    estimated_restock_paid_minor: string;
  };
};
type Point = Period & { start: string; end_exclusive: string };
type Contribution = { sku: string | null; product_name: string; sales_contribution_minor: string };
export type Result = {
  dataset_id: string;
  currency: string;
  currency_exponent: number;
  timezone: string;
  source_as_of: string;
  engine_version: string;
  query: Query;
  periods: { current: string[]; previous: string[] | null };
  current: Period;
  previous: Period | null;
  comparison: Record<string, Change> | null;
  matched_cost_subset: Period;
  trend: Point[];
  warnings: string[];
  excluded_rows: number;
  product_count: number;
  contributions: {
    available: boolean;
    total_minor: string | null;
    gainers: Contribution[];
    decliners: Contribution[];
    effects: { order_effect_minor: string; aov_effect_minor: string } | null;
  };
};
export type Snapshot = Refine<Schema<'MetricSnapshot'>, { result: Result | null }>;
/** A product row of `/metrics/{id}/products` (free-form JSON in the API's response model). */
export type Product = {
  sku: string | null;
  product_name: string;
  current: Period;
  previous: Period | null;
  comparison: Record<string, Change> | null;
  sales_contribution_minor: string | null;
};
export type ProductPage = Paged<Product>;
/** Sorting and filtering of the product table. */
export type ProductOrder = { sort: string; direction: string; focus: string };
