import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../lib/api';
import { t } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { DatasetVersion } from '../../lib/types';
import { fromParams, invalid, toParams } from './query';
import type { Query, Snapshot } from './types';

const computing = (status: string | undefined) => ['queued', 'running'].includes(status ?? '');

/**
 * The filter draft, its mirror in the URL and the metric snapshot computed for the applied query.
 * The URL's version (or the first published one) seeds the draft once; after that only `apply` runs.
 */
export function useDashboardQuery() {
  const [params, setParams] = useSearchParams();
  const versions = useQuery({
    queryKey: keys.datasets,
    queryFn: () => api<DatasetVersion[]>('/datasets'),
  });
  const requestedVersion = params.get('dataset');
  const selectedVersion = useQuery({
    queryKey: keys.dataset(requestedVersion ?? ''),
    enabled: !!requestedVersion && !versions.data?.some(v => v.id === requestedVersion),
    queryFn: () => api<DatasetVersion>(`/datasets/${requestedVersion}`),
  });
  const listed = versions.data ?? [];
  const extra = selectedVersion.data;
  const availableVersions =
    extra && !listed.some(v => v.id === extra.id) ? [...listed, extra] : listed;
  const [draft, setDraft] = useState<Query | null>(null);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const active = useRef('');
  const [validationError, setValidationError] = useState('');
  const request = useMutation({
    mutationFn: (q: Query) =>
      api<Snapshot>('/metrics/query', { method: 'POST', body: JSON.stringify(q) }),
    onSuccess: (item, q) => {
      if (JSON.stringify(q) === active.current) setSnapshotId(item.id);
    },
  });
  const snapshot = useQuery({
    queryKey: keys.metrics(snapshotId ?? ''),
    enabled: !!snapshotId,
    queryFn: () => api<Snapshot>(`/metrics/${snapshotId}`),
    refetchInterval: q => (computing(q.state.data?.status) ? 1000 : false),
  });
  const { mutate } = request;
  const apply = useCallback(
    (q: Query) => {
      if (invalid(q)) {
        setValidationError(t('请选择有效的开始与结束日期。'));
        return;
      }
      setValidationError('');
      setDraft(q);
      active.current = JSON.stringify(q);
      setSnapshotId(null);
      setOffset(0);
      setParams(toParams(q), { replace: true });
      mutate(q);
    },
    [mutate, setParams],
  );
  // Undefined once a draft exists, so the effect below seeds the form exactly once.
  const initialVersion = draft
    ? undefined
    : requestedVersion
      ? availableVersions.find(v => v.id === requestedVersion)
      : versions.data?.[0];
  useEffect(() => {
    if (!initialVersion) return;
    const q = fromParams(initialVersion, params);
    // Set separately so the form still appears when the URL's dates fail validation.
    setDraft(q);
    apply(q);
  }, [initialVersion, params, apply]);
  const busy =
    request.isPending || (!!snapshotId && (snapshot.isPending || computing(snapshot.data?.status)));
  const dirty = !!draft && JSON.stringify(draft) !== active.current;
  return {
    versions,
    selectedVersion,
    availableVersions,
    draft,
    setDraft,
    request,
    snapshotId,
    snapshot,
    offset,
    setOffset,
    validationError,
    apply,
    busy,
    dirty,
  };
}
