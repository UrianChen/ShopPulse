import { describe, expect, it } from 'vitest';
import { changeText, decimal, formatMetric } from './format';

describe('authoritative decimal formatting', () => {
  it('rounds AOV for display without re-computing comparisons', () => {
    expect(decimal('18333.333333333333', 2, -2)).toBe('183.33');
    expect(decimal('0.418181818182', 2, 2)).toBe('41.82');
    expect(decimal('-0.005')).toBe('-0.01');
    expect(decimal('-0.0001')).toBe('0.00');
  });
  it('preserves huge money and different currency exponents', () => {
    expect(decimal('21474836469999999999785252', 2, -2)).toBe('214,748,364,699,999,999,997,852.52');
    expect(decimal('12500', 3, -3)).toBe('12.500');
    expect(decimal('12500', 0, 0)).toBe('12,500');
    expect(formatMetric({ value: null, unit: 'minor_currency', quality: 'unavailable', unavailable_reason: 'COST_MISSING' }, 'CNY', 2)).toBe('—');
  });
  it('distinguishes percentage points, zero baselines and incomplete data', () => {
    expect(changeText({ delta: '0.018181818182', delta_pp: '1.818181818182', change_rate: null, state: 'comparable', quality: 'confirmed' })).toBe('+1.82 个百分点');
    expect(changeText({ delta: '100', delta_pp: null, change_rate: null, state: 'new', quality: 'confirmed' })).toContain('上期为零');
    expect(changeText({ delta: null, delta_pp: null, change_rate: null, state: 'incomplete_coverage', quality: 'unavailable' })).toContain('不作周期比较');
  });
});
