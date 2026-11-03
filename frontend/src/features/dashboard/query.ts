import { day, lastDay } from '../../lib/dates';
import type { DatasetVersion } from '../../lib/types';
import type { Query } from './types';

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const comparisons = ['none', 'previous', 'custom'] as const;

/** Narrows a form or URL value to a comparison mode. */
export function comparisonOf(value: string | null) {
  return comparisons.find(c => c === value);
}

/** The last seven days of the version's coverage, compared with the period before. */
export function defaults(v: DatasetVersion): Query {
  const o = v.snapshot.config.options,
    end = o.coverage_end_exclusive.slice(0, 10);
  return {
    dataset_id: v.id,
    start:
      day(end, -7) < o.coverage_start.slice(0, 10) ? o.coverage_start.slice(0, 10) : day(end, -7),
    end_exclusive: end,
    comparison: 'previous',
    compare_start: null,
    compare_end_exclusive: null,
    granularity: 'day',
    skus: [],
  };
}

/** The query a shared dashboard URL describes, on top of the version defaults. */
export function fromParams(v: DatasetVersion, params: URLSearchParams): Query {
  const q = defaults(v);
  const start = params.get('start') ?? '',
    end = params.get('end') ?? '';
  if (DATE.test(start) && DATE.test(end)) {
    q.start = start;
    q.end_exclusive = end;
  }
  q.comparison = comparisonOf(params.get('comparison')) ?? q.comparison;
  q.compare_start = params.get('compare_start');
  q.compare_end_exclusive = params.get('compare_end');
  q.granularity = params.get('granularity') === 'week' ? 'week' : 'day';
  q.skus = params.getAll('sku');
  return q;
}

export function toParams(q: Query) {
  const next = new URLSearchParams({
    dataset: q.dataset_id,
    start: q.start,
    end: q.end_exclusive,
    comparison: q.comparison,
    granularity: q.granularity,
  });
  q.skus.forEach(s => next.append('sku', s));
  if (q.comparison === 'custom') {
    next.set('compare_start', q.compare_start!);
    next.set('compare_end', q.compare_end_exclusive!);
  }
  return next;
}

export function invalid(q: Query) {
  return (
    !q.start ||
    !q.end_exclusive ||
    q.start >= q.end_exclusive ||
    (q.comparison === 'custom' &&
      (!q.compare_start || !q.compare_end_exclusive || q.compare_start >= q.compare_end_exclusive))
  );
}

/** Inclusive end for a date input; empty when the URL carried something that is not a date. */
export function inputEnd(endExclusive: string | null) {
  if (!endExclusive) return '';
  const date = new Date(endExclusive.slice(0, 10) + 'T12:00:00Z');
  return Number.isNaN(date.getTime()) ? '' : lastDay(endExclusive);
}
