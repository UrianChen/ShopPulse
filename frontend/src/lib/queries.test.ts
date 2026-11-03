import type { Query } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { day, lastDay } from './dates';
import { anyActive, keys, POLL, pollWhile } from './queries';

function query<T>(data: T | undefined) {
  return { state: { data } } as Query<T, Error, T, readonly unknown[]>;
}

describe('polling', () => {
  it('polls only while loaded data says work is running', () => {
    const interval = pollWhile<{ status: string }>(d => d.status === 'running', POLL.fast);
    expect(interval(query({ status: 'running' }))).toBe(POLL.fast);
    expect(interval(query({ status: 'ready' }))).toBe(false);
    // No data means the first load is pending or failed: do not retry an error forever.
    expect(interval(query<{ status: string }>(undefined))).toBe(false);
  });

  it('treats queued and running work as active', () => {
    const items = [{ status: 'succeeded' }, { status: 'queued' }];
    expect(anyActive(items, i => i.status)).toBe(true);
    expect(anyActive(items.slice(0, 1), i => i.status)).toBe(false);
    expect(anyActive(undefined, (i: { status: string }) => i.status)).toBe(false);
  });

  it('nests detail keys under their list so one invalidation refreshes both', () => {
    expect(keys.report('r1').slice(0, 1)).toEqual(keys.reports);
    expect(keys.reportRuns('r1').slice(0, 2)).toEqual(keys.report('r1'));
    expect(keys.dataset('d1').slice(0, 1)).toEqual(keys.datasets);
  });
});

describe('dates', () => {
  it('shifts calendar days and tolerates bad input', () => {
    expect(day('2026-10-05', -1)).toBe('2026-10-04');
    expect(lastDay('2026-03-01T00:00:00+08:00')).toBe('2026-02-28');
    expect(day('not a date', 1)).toBe('');
  });
});
