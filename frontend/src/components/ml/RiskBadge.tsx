import { AlertTriangle, CheckCircle2, CircleAlert } from 'lucide-react'

import type { RiskLevel } from '../../types/ml'
import { Badge, type BadgeTone } from '../common/Badge'
import { formatProbability } from './mlFormat'

const LEVELS: Record<RiskLevel, { tone: BadgeTone; label: string; Icon: typeof AlertTriangle }> = {
  high: { tone: 'danger', label: 'High risk', Icon: AlertTriangle },
  medium: { tone: 'warning', label: 'Medium risk', Icon: CircleAlert },
  low: { tone: 'success', label: 'Low risk', Icon: CheckCircle2 },
}

/** Risk level in words with an icon (never colour alone), optionally with the probability. */
export function RiskBadge({ level, probability }: { level: RiskLevel; probability?: number }) {
  const { tone, label, Icon } = LEVELS[level]
  return (
    <span className="inline-block whitespace-nowrap">
      <Badge tone={tone}>
        <Icon aria-hidden className="mr-1 h-3.5 w-3.5" />
        {label}
        {probability !== undefined && (
          <span className="ml-1 tabular-nums">{formatProbability(probability)}</span>
        )}
      </Badge>
    </span>
  )
}
