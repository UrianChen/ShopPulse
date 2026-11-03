/** Joins class names (CSS Module classes and hooks), skipping falsy ones. */
export function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(' ');
}
