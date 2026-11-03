import { keys as shared } from '../../lib/queries';

/** Shared query keys plus the paged issue list, which refetches per validation run and page. */
export const keys = {
  ...shared,
  importIssuePage: (
    id: string,
    validatedRevision: number | null | undefined,
    status: string | undefined,
    offset: number,
  ) => [...shared.importIssues(id), validatedRevision, status, offset] as const,
};
