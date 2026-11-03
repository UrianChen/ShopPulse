import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // `camelCase` keeps the dashed names too, for classes picked by value (`ui[`state-${value}`]`).
  css: { modules: { localsConvention: 'camelCase' } },
  server: {
    port: 5173,
    strictPort: true,
    // API_PROXY_TARGET points the dev server at another API, e.g. a Compose instance on :8080.
    proxy: { '/api': { target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000' } },
  },
});
