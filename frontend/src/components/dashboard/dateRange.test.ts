import { describe, expect, it } from 'vitest'

import { DEFAULT_RANGE, rangeError, rangeParams, todayUtc } from './dateRange'

describe('dateRange', () => {
  it('turns presets into both-ends-included UTC day ranges', () => {
    expect(rangeParams({ preset: '7', from: '', to: '' }, '2026-11-10')).toEqual({
      date_from: '2026-11-04',
      date_to: '2026-11-10',
    })
    expect(rangeParams(DEFAULT_RANGE, '2026-11-10')).toEqual({
      date_from: '2026-10-12',
      date_to: '2026-11-10',
    })
    expect(rangeParams({ preset: '90', from: '', to: '' }, '2026-03-01')).toEqual({
      date_from: '2025-12-02', // across a year and February
      date_to: '2026-03-01',
    })
  })

  it('passes a custom range through', () => {
    expect(rangeParams({ preset: 'custom', from: '2026-01-01', to: '2026-01-31' })).toEqual({
      date_from: '2026-01-01',
      date_to: '2026-01-31',
    })
  })

  it('checks custom ranges like the API does', () => {
    expect(rangeError('', '2026-11-10')).toBe('Choose a start and an end date')
    expect(rangeError('2026-11-11', '2026-11-10')).toMatch('must not be after')
    expect(rangeError('2025-11-10', '2026-11-10')).toBe(null) // 366 days
    expect(rangeError('2025-11-09', '2026-11-10')).toBe('Choose at most 366 days')
    expect(rangeError('2026-11-10', '2026-11-10')).toBe(null)
  })

  it('uses the UTC day for "today"', () => {
    expect(todayUtc(new Date('2026-11-10T23:30:00-05:00'))).toBe('2026-11-11')
  })
})
