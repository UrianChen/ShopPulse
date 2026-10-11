import { afterEach, describe, expect, it, vi } from 'vitest';
import { getLanguage, LANGUAGE_KEY, locale, message, setLanguage, t } from './i18n';
import { formatMetric } from '../features/dashboard/format';

afterEach(() => { vi.unstubAllGlobals(); setLanguage('zh'); });

describe('interface language', () => {
  it('persists only language and updates the document language', () => {
    const setItem = vi.fn();
    vi.stubGlobal('localStorage', { setItem });
    vi.stubGlobal('document', { documentElement: { lang: 'zh-CN' } });
    setLanguage('en');
    expect(getLanguage()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(setItem).toHaveBeenCalledWith(LANGUAGE_KEY, 'en');
    expect(t('净销售额')).toBe('Net sales');
    setLanguage('zh');
    expect(t('净销售额')).toBe('净销售额');
  });
  it('works when storage is blocked and preserves interpolated values', () => {
    vi.stubGlobal('localStorage', { setItem: () => { throw new Error('blocked'); } });
    setLanguage('en');
    expect(locale()).toBe('en-US');
    expect(t('比较期 {0}', '2026-10-01')).toBe('Previous: 2026-10-01');
    expect(t('商家自己的数据名称')).toBe('商家自己的数据名称');
    expect(message('unrecognized provider-safe error')).toBe('unrecognized provider-safe error');
    expect(message('无法完成未知请求')).toContain('Unable to complete');
  });
  it('localizes currency without losing decimal precision or changing values', () => {
    const metric = { value: '900719925474099312345', unit: 'minor_currency' as const, quality: 'confirmed' as const, unavailable_reason: null };
    setLanguage('en');
    expect(formatMetric(metric, 'CNY', 2)).toBe('CN¥9,007,199,254,740,993,123.45');
    setLanguage('zh');
    expect(formatMetric(metric, 'CNY', 2)).toBe('¥9,007,199,254,740,993,123.45');
  });
});
