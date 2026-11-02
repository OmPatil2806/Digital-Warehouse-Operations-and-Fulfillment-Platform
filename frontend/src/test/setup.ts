// Global test setup for Vitest + React Testing Library.
import '@testing-library/jest-dom/vitest' // adds matchers such as toBeInTheDocument()

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount rendered components after every test so tests stay independent.
afterEach(() => {
  cleanup()
})
