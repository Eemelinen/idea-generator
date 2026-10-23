import { defineConfig } from 'vitest/config'

/** Unit tests for the harness scripts. Hermetic: no network, no Claude, no git writes. */
export default defineConfig({
  test: {
    name: 'unit',
    environment: 'node',
    include: ['tests/unit/**/*.test.ts'],
    testTimeout: 10_000,
  },
})
