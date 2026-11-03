// Query keys and polling in one place, so invalidations always match the queries they target.
import type { Query } from '@tanstack/react-query';

export const keys = {
  workspace: ['workspace'] as const,
  datasets: ['datasets'] as const,
  dataset: (id: string) => ['datasets', id] as const,
  datasetSkus: (id: string) => ['datasets', id, 'skus'] as const,
  costVersions: ['cost-versions'] as const,
  costVersion: (id: string) => ['cost-versions', id] as const,
  upload: (id: string) => ['upload', id] as const,
  imports: ['imports'] as const,
  importDraft: (id: string) => ['imports', id] as const,
  importIssues: (id: string) => ['imports', id, 'issues'] as const,
  metrics: (snapshotId: string) => ['metrics', snapshotId] as const,
  metricProducts: (snapshotId: string, page: number) =>
    ['metrics', snapshotId, 'products', page] as const,
  modelConfigs: ['model-configs'] as const,
  reports: ['reports'] as const,
  reportList: (offset: number) => ['reports', 'list', offset] as const,
  homeReports: ['reports', 'home'] as const,
  report: (id: string) => ['reports', id] as const,
  reportRuns: (id: string) => ['reports', id, 'runs'] as const,
  reportEvidence: (id: string, evidenceId: string) =>
    ['reports', id, 'evidence', evidenceId] as const,
  reportMessages: (id: string) => ['reports', id, 'messages'] as const,
  reportActions: (id: string) => ['reports', id, 'actions'] as const,
  reportExports: (id: string) => ['reports', id, 'exports'] as const,
  actions: (status: string) => ['actions', status] as const,
  notes: ['notes'] as const,
  schedules: ['schedules'] as const,
  operationsStatus: ['operations', 'status'] as const,
  operationsJobs: ['operations', 'jobs'] as const,
  operationsSettings: ['operations', 'settings'] as const,
  operationsAudit: ['operations', 'audit'] as const,
};

export const ACTIVE = ['queued', 'running', 'computing', 'analyzing', 'validating', 'publishing'];
export const FINAL = ['ready', 'ready_with_warnings', 'failed', 'succeeded', 'cancelled'];

export const POLL = { fast: 1500, normal: 2000, slow: 3000 } as const;

/**
 * `refetchInterval` that polls while ``busy(data)`` holds and stops once work is done. Without
 * data (first load still pending, or it failed) it does not poll, so an error is not retried forever.
 * Pages pass it directly: `refetchInterval: pollWhile(r => !FINAL.includes(r.status))`.
 */
export function pollWhile<T>(busy: (data: T) => boolean, interval: number = POLL.normal) {
  return (query: Query<T, Error, T, readonly unknown[]>) => {
    const data = query.state.data;
    return data !== undefined && busy(data) ? interval : false;
  };
}

/** True while any listed item is still queued or running. */
export function anyActive<T>(items: T[] | undefined, status: (item: T) => string | null) {
  return (items ?? []).some(item => ACTIVE.includes(status(item) ?? ''));
}
