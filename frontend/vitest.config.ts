import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test/setup.ts'],
    // Component tests opt into a DOM with a `@vitest-environment jsdom` docblock.
    environment: 'node',
  },
});
