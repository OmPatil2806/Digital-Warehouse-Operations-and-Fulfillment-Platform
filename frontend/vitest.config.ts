import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

// Reuses the Vite config (React + Tailwind plugins) and adds test settings.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
      testTimeout: 15_000, // slower machines and coverage runs
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx', 'src/vite-env.d.ts'],
        reporter: ['text-summary', 'text', 'html'],
        thresholds: { lines: 90, statements: 90, branches: 85, functions: 85 },
      },
      css: false,
      restoreMocks: true,
    },
  }),
)
