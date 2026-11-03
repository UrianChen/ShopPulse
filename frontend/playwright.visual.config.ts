import { defineConfig } from '@playwright/test';

// Visual regression: full-page screenshots of every page of the built app (`vite preview`), with
// `/api/v1` answered from the API fixtures in src/test/api.json, so no backend is needed.
// Font rendering differs per OS, so baselines are kept per platform; the Linux ones come from the
// Playwright container that CI uses (`npm run test:visual:linux`).
export default defineConfig({
  testDir: './visual',
  snapshotPathTemplate: '{testDir}/__screenshots__/{platform}/{arg}{ext}',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  timeout: 60000,
  reporter: 'list',
  expect: { toHaveScreenshot: { animations: 'disabled', caret: 'hide', maxDiffPixels: 50 } },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    colorScheme: 'light',
    trace: 'off',
  },
  projects: [{ name: 'visual', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'npx vite preview --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
  },
});
