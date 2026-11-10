import { describe, expect, it } from 'vitest'

import { formatDays, formatHours, formatPercentage, formatShortDate, plural } from './format'

describe('dashboard formatters', () => {
  it.each([
    ['66.7', '66.7 %'],
    ['100.0', '100 %'],
    [0, '0 %'],
    [null, '—'],
  ])('formatPercentage(%s) = %s', (value, expected) => {
    expect(formatPercentage(value)).toBe(expected)
  })

  it.each([
    ['0.75', '45 min'],
    ['1.5', '1.5 h'],
    ['9.96', '10 h'],
    ['22.0', '22 h'],
    ['47.4', '47 h'],
    ['48', '2 days'],
    ['109.0', '4.5 days'],
    [null, '—'],
  ])('formatHours(%s) = %s', (value, expected) => {
    expect(formatHours(value)).toBe(expected)
  })

  it.each([
    ['4.0', '4 days'],
    ['1', '1 day'],
    ['2.25', '2.3 days'],
    ['1520.5', '1,520.5 days'],
    [undefined, '—'],
  ])('formatDays(%s) = %s', (value, expected) => {
    expect(formatDays(value)).toBe(expected)
  })

  it('formats API days in UTC, whatever the local time zone', () => {
    expect(formatShortDate('2026-11-07')).toBe('7 Nov')
    expect(formatShortDate('2026-01-01')).toBe('1 Jan')
  })
})

describe('plural', () => {
  it.each([
    [1, 'product', undefined, '1 product'],
    [0, 'product', undefined, '0 products'],
    [2, 'delivery', 'deliveries', '2 deliveries'],
    [4026, 'unit', undefined, '4,026 units'],
  ])('plural(%s, %s)', (count, word, many, expected) => {
    expect(plural(count, word, many)).toBe(expected)
  })
})
