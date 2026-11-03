import { t } from '../../lib/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import type { Body } from '../../lib/types';
import { keys } from './keys';
import type { DraftForm } from './useDraftForm';
import type { Draft } from './types';

const PAYMENT_STATES = ['paid', 'unpaid', 'cancelled_unpaid'];

function parseStatusMapping(text: string) {
  const mapping: Record<string, string> = {};
  for (const line of text.split('\n').filter(v => v.trim())) {
    const [key, state, extra] = line.split('=');
    if (!key || !state || extra || !PAYMENT_STATES.includes(state.trim()))
      throw new Error(t('状态映射格式应为：原始状态=paid / unpaid / cancelled_unpaid，每行一条。'));
    mapping[key.trim()] = state.trim();
  }
  return mapping;
}

function parseExcludedRows(text: string) {
  const rows = text.trim()
    ? text
        .split(/[,，\s]+/)
        .filter(Boolean)
        .map(Number)
    : [];
  if (rows.some(v => !Number.isInteger(v) || v < 1))
    throw new Error(t('排除行号须为正整数，以逗号分隔。'));
  return [...new Set(rows)];
}

/** Save-and-validate, resolve-and-validate and publish for one import draft. */
export function useImportActions(id: string, current: Draft | undefined, form: DraftForm) {
  const client = useQueryClient();
  function refresh() {
    // `keys.imports` is a prefix of this draft's key and its issue pages, so they refetch too.
    void client.invalidateQueries({ queryKey: keys.imports });
    void client.invalidateQueries({ queryKey: keys.datasets });
    void client.invalidateQueries({ queryKey: keys.costVersions });
  }
  function validate(revision: number) {
    const body: Body<'RevisionRequest'> = { expected_revision: revision };
    return api(`/imports/${id}/validate`, { method: 'POST', body: JSON.stringify(body) });
  }
  const save = useMutation({
    mutationFn: async () => {
      const { config } = form;
      if (!config || !current) throw new Error(t('导入配置尚未加载。'));
      const mapping = parseStatusMapping(form.statusMapping);
      const updated = await api<Draft>(`/imports/${id}/mapping`, {
        method: 'PUT',
        body: JSON.stringify({
          expected_revision: current.revision,
          config: { ...config, options: { ...config.options, status_mapping: mapping } },
        }),
      });
      return validate(updated.revision);
    },
    onSuccess: refresh,
  });
  const resolve = useMutation({
    mutationFn: async (revision: number) => {
      const body: Body<'ResolutionRequest'> = {
        expected_revision: revision,
        excluded_rows: parseExcludedRows(form.excluded),
        acknowledged_codes: form.ack,
        reason: form.reason,
      };
      const updated = await api<Draft>(`/imports/${id}/resolutions`, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      return validate(updated.revision);
    },
    onSuccess: refresh,
  });
  const publish = useMutation({
    mutationFn: (revision: number) => {
      const body: Body<'RevisionRequest'> = { expected_revision: revision };
      return api(`/imports/${id}/publish`, { method: 'POST', body: JSON.stringify(body) });
    },
    onSuccess: refresh,
  });
  return { save, resolve, publish };
}
