import type { ScoringInfo } from '../../types/ml'
import { formatShortDate } from '../../utils/format'
import { modelLabel } from './mlFormat'

/** "As of 10 Nov, LSTM model": where a prediction comes from, so readers can judge it. */
export function ScoringNote({ scoring }: { scoring: ScoringInfo | null | undefined }) {
  if (!scoring) return null
  return (
    <p className="text-xs text-slate-500">
      As of {formatShortDate(scoring.as_of)} · {modelLabel(scoring.model_name, scoring.is_baseline)}
    </p>
  )
}
