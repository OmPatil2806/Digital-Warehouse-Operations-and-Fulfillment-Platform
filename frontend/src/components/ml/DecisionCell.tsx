import { Check, X } from 'lucide-react'

import type { Decision } from '../../types/ml'
import { formatDateTime } from '../inventory/movementFormat'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'

/**
 * A recommendation's decision: buttons while it is pending (managers only), otherwise
 * who decided and when, in words.
 */
export function DecisionCell({
  decision,
  canDecide,
  busy = false,
  label,
  onApprove,
  onReject,
}: {
  decision: Decision
  canDecide: boolean
  busy?: boolean
  label: string // what is decided on, for screen readers: "reorder of SKU-1"
  onApprove?: () => void
  onReject?: () => void
}) {
  if (decision.status === 'approved' || decision.status === 'rejected') {
    const approved = decision.status === 'approved'
    return (
      <div className="flex flex-col items-start gap-0.5">
        <Badge tone={approved ? 'success' : 'neutral'}>
          {approved ? (
            <Check aria-hidden className="mr-1 h-3.5 w-3.5" />
          ) : (
            <X aria-hidden className="mr-1 h-3.5 w-3.5" />
          )}
          {approved ? 'Approved' : 'Rejected'}
        </Badge>
        {decision.decided_at && (
          <span className="text-xs text-slate-500">{formatDateTime(decision.decided_at)}</span>
        )}
        {decision.decision_note && (
          <span className="text-xs text-slate-500">“{decision.decision_note}”</span>
        )}
      </div>
    )
  }
  if (!canDecide) return <Badge>Pending</Badge>
  return (
    <div className="flex gap-1.5">
      <Button
        size="sm"
        icon={<Check aria-hidden className="h-3.5 w-3.5" />}
        onClick={onApprove}
        loading={busy}
        aria-label={`Approve ${label}`}
      >
        Approve
      </Button>
      <Button
        size="sm"
        variant="secondary"
        icon={<X aria-hidden className="h-3.5 w-3.5" />}
        onClick={onReject}
        disabled={busy}
        aria-label={`Reject ${label}`}
      >
        Reject
      </Button>
    </div>
  )
}
