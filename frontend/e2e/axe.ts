import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

/** Fails on serious or critical accessibility violations of the current page (axe-core rules). */
export async function expectAccessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const blocking = violations
    .filter(v => v.impact === 'serious' || v.impact === 'critical')
    .map(v => `${v.id} (${v.impact}): ${v.nodes.map(n => n.target.join(' ')).join(' | ')}`);
  expect(blocking, 'serious or critical accessibility violations').toEqual([]);
}
