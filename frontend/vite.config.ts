import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// The backend sets a session cookie, so the dev server proxies /api to keep one origin.
// VITE_API_TARGET points it elsewhere (the browser tests use their own backend on :8010).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.VITE_API_TARGET ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: [...configDefaults.exclude, 'e2e/**'], // the browser tests run with `make e2e`
    testTimeout: 15_000, // the first render of an antd screen is slow when many files run at once
  },
})
