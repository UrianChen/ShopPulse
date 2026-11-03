import type { Schema } from '../../lib/types';

export type Config = Schema<'WorkspaceSettings'>;
export type Status = Schema<'ServiceStatus'>;
export type Task = Schema<'Job'>;
/** Impact preview of a deletion or of the retention cleanup. */
export type Plan = Pick<Schema<'DeletionPlan'> | Schema<'CleanupPlan'>, 'token' | 'counts'>;
export type AuditEntry = Schema<'AuditEntry'>;
