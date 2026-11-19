// Global test setup for Vitest + React Testing Library.
import '@testing-library/jest-dom/vitest' // adds matchers such as toBeInTheDocument()

import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// findBy*/waitFor wait up to 5 s instead of 1 s: whole pages render slower on busy CI
// machines and in coverage runs. Passing tests finish as soon as the content appears.
configure({ asyncUtilTimeout: 5000 })

// Unmount rendered components after every test so tests stay independent.
afterEach(() => {
  cleanup()
})
