/**
 * Calendar date ``offset`` days from an ISO date (``YYYY-MM-DD…``), as ``YYYY-MM-DD``.
 * Returns '' for an unparsable value (dates often come from URL parameters).
 */
export function day(value: string, offset: number) {
  const date = new Date(value.slice(0, 10) + 'T12:00:00Z');
  if (Number.isNaN(date.getTime())) return '';
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

/** Inclusive last day of an exclusive end date. */
export function lastDay(endExclusive: string) {
  return day(endExclusive, -1);
}
