import { expect, test, type Page } from '@playwright/test';
import { expectAccessible } from '../e2e/axe';
import { ids, serveApi } from './api';

const LANGUAGE_KEY = 'shoppulse.language';
// Shortly after the fixtures were recorded, so expiry dates and "today" stay stable.
const NOW = new Date('2026-11-03T08:00:00Z');

/** `open` brings up an overlay; those screens are captured at viewport size. */
type Screen = { name: string; path: string; open?: (page: Page) => Promise<void> };

const screens: Screen[] = [
  { name: 'home', path: '/' },
  { name: 'data', path: '/data' },
  { name: 'import', path: `/data?import=${ids.ordersImport}` },
  { name: 'dashboard', path: '/dashboard' },
  { name: 'reports', path: '/reports' },
  { name: 'new-report', path: `/reports/new?parent=${ids.report}` },
  { name: 'report', path: `/reports/${ids.report}` },
  {
    name: 'report-evidence',
    path: `/reports/${ids.report}`,
    open: async page => {
      await page
        .getByRole('button', { name: /^(查看检验|View test)$/ })
        .first()
        .click();
      await expect(page.getByRole('dialog')).toBeVisible();
    },
  },
  { name: 'automation', path: '/automation' },
  { name: 'models', path: '/settings/models' },
  { name: 'operations', path: '/operations' },
  { name: 'not-found', path: '/missing-page' },
];

/** Wait until queries have settled and fonts are in. */
async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.getByText(/^(读取中…|Loading…)$|^正在读取|^Loading /)).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

for (const language of ['zh', 'en'] as const) {
  test.describe(language, () => {
    test.beforeEach(async ({ page }) => {
      await page.clock.setFixedTime(NOW);
      await page.addInitScript(
        ([key, value]) => localStorage.setItem(key, value),
        [LANGUAGE_KEY, language],
      );
    });

    for (const screen of screens) {
      test(screen.name, async ({ page }) => {
        const missing = await serveApi(page);
        await page.goto(screen.path);
        await settle(page);
        if (screen.open) {
          await screen.open(page);
          await settle(page);
        }
        expect(missing).toEqual([]);
        await expectAccessible(page);
        await expect(page).toHaveScreenshot(`${screen.name}-${language}.png`, {
          fullPage: !screen.open,
        });
      });
    }
  });
}
