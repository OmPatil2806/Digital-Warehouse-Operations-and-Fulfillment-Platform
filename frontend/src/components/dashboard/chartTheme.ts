/**
 * Colours and mark sizes shared by every dashboard chart.
 *
 * Categorical slots come from the validated reference palette and are assigned in this
 * fixed order, never cycled: a ninth series folds into "Other". Checked with the
 * palette validator on the white card surface: every adjacent pair passes the
 * colour-vision-deficiency (ΔE 9.1) and normal-vision (ΔE 19.6) separation checks.
 * Slots 3, 4 and 5 are below 3:1 contrast on white, so every chart also has a table
 * view and a legend; text never uses a series colour.
 */

export const SERIES = [
  '#2a78d6', // 1 blue
  '#eb6834', // 2 orange
  '#1baf7a', // 3 aqua
  '#eda100', // 4 yellow
  '#e87ba4', // 5 magenta
  '#008300', // 6 green
  '#6250d6', // 7 violet
  '#e34948', // 8 red
] as const

/** Reserved for states (never a series colour); always shown with an icon and a label. */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

export type StatusTone = keyof typeof STATUS

/** Sequential blue ramp (light -> dark) for magnitude, e.g. how full a zone is. */
export const SEQUENTIAL = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281'] as const

/** Chart furniture: recessive grid and axes, text in ink colours. */
export const INK = {
  primary: '#0b0b0b',
  secondary: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
  baseline: '#c3c2b7',
  surface: '#ffffff',
} as const

export const MARKS = {
  lineWidth: 2,
  barRadius: 4, // rounded data end only
  markerRadius: 4, // 8 px markers
  gap: 2, // surface gap between adjacent fills
} as const

/** Colour of the n-th series (0-based), in the fixed order; "Other" takes the muted ink. */
export function seriesColor(index: number): string {
  return SERIES[index] ?? INK.muted
}
