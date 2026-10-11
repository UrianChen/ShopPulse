import { useSyncExternalStore } from 'react';
import { english } from './messages';
import { serverEnglish } from './serverMessages';

export type Language = 'zh' | 'en';
export const LANGUAGE_KEY = 'shoppulse.language';
const listeners = new Set<() => void>();
function storedLanguage(): Language {
  try { return localStorage.getItem(LANGUAGE_KEY) === 'en' ? 'en' : 'zh'; }
  catch { return 'zh'; }
}
let language: Language = storedLanguage();
function applyDocumentLanguage() {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    document.title = language === 'en' ? 'ShopPulse · Business workspace' : 'ShopPulse · 经营工作台';
  }
}
applyDocumentLanguage();
export function getLanguage() { return language; }
export function locale() { return language === 'en' ? 'en-US' : 'zh-CN'; }
export function setLanguage(next: Language) {
  if (next !== 'en' && next !== 'zh') return;
  language = next;
  try { localStorage.setItem(LANGUAGE_KEY, next); } catch { /* Private browsing can disable storage. */ }
  applyDocumentLanguage();
  listeners.forEach(listener => listener());
}
if (typeof window !== 'undefined') window.addEventListener('storage', event => {
  if (event.key === LANGUAGE_KEY || event.key === null) {
    language = storedLanguage(); applyDocumentLanguage(); listeners.forEach(listener => listener());
  }
});
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function useLanguage() { return useSyncExternalStore(subscribe, getLanguage, () => 'zh' as Language); }
export function t(source: string | null | undefined, ...values: unknown[]): string {
  if (source == null) return '';
  const text = language === 'en' ? english[source] ?? serverEnglish[source] ?? source : source;
  return text.replace(/\{(\d+)\}/g, (match, index: string) => Number(index) < values.length ? String(values[Number(index)] ?? '') : match);
}
// Server errors are displayed without exposing raw response bodies. User data is never translated.
export function message(source: string | null | undefined) {
  const text = t(source);
  if (language === 'en' && source) {
    const patterns: [RegExp, string][] = [
      [/^与第 (\d+) 行内容相同，请确认保留或排除。$/, 'Duplicates row $1. Review whether to keep or exclude it.'],
      [/^所选列 (.+) 不存在。$/, 'Selected column $1 does not exist.'],
      [/^(.+) 缺失，请修正映射、补齐数据或排除此行。$/, '$1 is missing. Fix the mapping, add the value or exclude the row.'],
      [/^请映射 (.+)$/, 'Map the required field: $1'],
      [/^(.+) 超过 128 字符。$/, '$1 exceeds 128 characters.'],
      [/^计算内存超过 (.+) MiB 限制，请缩小范围后重试。$/, 'Calculation exceeded $1 MiB. Narrow the range and retry.'],
    ];
    for (const [pattern, replacement] of patterns) if (pattern.test(source)) return source.replace(pattern, replacement);
  }
  return language === 'en' && /[\u3400-\u9fff]/.test(text)
    ? 'Unable to complete this request. Review your data or settings and try again.' : text;
}
