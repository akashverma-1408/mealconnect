/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev proxy: the browser calls /api/... on :5173 and Vite forwards to FastAPI on :8000.
    // Same origin for the browser => no CORS issues in development; Nginx does this in prod.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    globals: true,
    css: false,
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,jsx}'],
      exclude: ['src/main.jsx', 'src/test/**', '**/*.test.{js,jsx}'],
      reporter: ['text-summary', 'html'],
      // Regression floor, raised as coverage grows. Flows not unit-tested here are
      // covered end-to-end by Playwright (e2e/).
      thresholds: { lines: 38, statements: 36, branches: 43, functions: 25 },
    },
  },
})
