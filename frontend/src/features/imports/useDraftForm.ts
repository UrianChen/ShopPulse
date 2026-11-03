import { useState } from 'react';
import type { Config, Draft } from './types';

/** Payment-state mapping as the editable `源表状态=paid` lines. */
export function mappingText(mapping: Record<string, string>) {
  return Object.entries(mapping)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
}

/**
 * Editable copy of a draft's config and resolutions. It resets whenever the draft id or revision
 * changes, but not on polls that return the same revision, so unsaved edits survive.
 */
export function useDraftForm(current: Draft | undefined) {
  const [config, setConfig] = useState<Config | null>(null);
  const [ack, setAck] = useState<string[]>([]);
  const [excluded, setExcluded] = useState('');
  const [reason, setReason] = useState('');
  const [offset, setOffset] = useState(0);
  const [statusMapping, setStatusMapping] = useState('');
  const stamp = current ? `${current.id}:${current.revision}` : null;
  const [loaded, setLoaded] = useState<string | null>(null);
  // Adjusting state during render (not in an effect) so the stale copy is never shown.
  if (current && stamp !== loaded) {
    setLoaded(stamp);
    setConfig(structuredClone(current.config));
    setOffset(0);
    setAck(current.resolutions.acknowledged_codes ?? []);
    setExcluded((current.resolutions.excluded_rows ?? []).join(','));
    setReason(current.resolutions.reason ?? '');
    setStatusMapping(mappingText(current.config.options.status_mapping));
  }
  return {
    config,
    setConfig,
    ack,
    setAck,
    excluded,
    setExcluded,
    reason,
    setReason,
    offset,
    setOffset,
    statusMapping,
    setStatusMapping,
  };
}

export type DraftForm = ReturnType<typeof useDraftForm>;
