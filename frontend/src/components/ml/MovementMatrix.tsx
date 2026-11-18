import type { MovementClass, MovementSummary } from '../../types/ml'
import { formatInteger, formatPercent } from '../../utils/format'
import { SEQUENTIAL } from '../dashboard/chartTheme'
import { ScoringNote } from './ScoringNote'

const CLASSES: { key: MovementClass; label: string; hint: string; color: string }[] = [
  { key: 'fast', label: 'Fast movers', hint: 'pick close to packing', color: SEQUENTIAL[4] },
  { key: 'medium', label: 'Medium movers', hint: 'middle racks', color: SEQUENTIAL[2] },
  { key: 'slow', label: 'Slow movers', hint: 'back of the warehouse', color: SEQUENTIAL[0] },
]

/**
 * How many products move fast, medium and slow, against their share of the picks: a few
 * fast movers usually carry most of the work. Numbers are always shown as text.
 */
export function MovementMatrix({ summary }: { summary: MovementSummary | undefined }) {
  const total = summary ? Object.values(summary.counts).reduce((a, b) => a + b, 0) : 0
  if (!summary || total === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">No movement classes yet.</p>
  }
  return (
    <div>
      <table className="w-full text-sm">
        <caption className="sr-only">Movement classes</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th scope="col" className="py-2 pr-3 font-medium">
              Class
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Products
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Share of products
            </th>
            <th scope="col" className="py-2 font-medium">
              Share of picks
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {CLASSES.map(({ key, label, hint, color }) => {
            const productShare = summary.counts[key] / total
            const pickShare = summary.pick_share[key]
            return (
              <tr key={key}>
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <span className="font-medium">{label}</span>
                  <span className="block text-xs text-slate-500">{hint}</span>
                </th>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {formatInteger(summary.counts[key])}
                </td>
                {[productShare, pickShare].map((share, index) => (
                  <td key={index} className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-28 rounded bg-slate-100" aria-hidden>
                        <div
                          className="h-2 rounded"
                          style={{ width: `${share * 100}%`, backgroundColor: color }}
                        />
                      </div>
                      <span className="tabular-nums">{formatPercent(share)}</span>
                    </div>
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="mt-2">
        <ScoringNote scoring={summary.scoring} />
      </div>
    </div>
  )
}
