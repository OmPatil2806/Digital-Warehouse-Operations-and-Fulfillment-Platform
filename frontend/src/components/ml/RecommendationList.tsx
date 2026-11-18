import { Link } from 'react-router'

import type { ProductRecommendations } from '../../types/ml'
import { ScoringNote } from './ScoringNote'

/** Products often bought together with this one, best first. */
export function RecommendationList({
  recommendations,
  limit = 5,
}: {
  recommendations: ProductRecommendations | undefined
  limit?: number
}) {
  const items = recommendations?.items.slice(0, limit) ?? []
  if (items.length === 0) {
    return <p className="py-4 text-sm text-slate-500">No related products yet.</p>
  }
  return (
    <div>
      <ol className="space-y-1.5" aria-label="Frequently bought together">
        {items.map((item) => (
          <li key={item.product.id} className="flex items-baseline gap-2 text-sm">
            <span className="w-5 text-right text-xs text-slate-400 tabular-nums">{item.rank}.</span>
            <Link
              to={`/products/${item.product.id}`}
              className="font-medium whitespace-nowrap text-blue-700 hover:underline"
            >
              {item.product.sku}
            </Link>
            <span className="truncate text-slate-600">{item.product.name}</span>
          </li>
        ))}
      </ol>
      <div className="mt-2">
        <ScoringNote scoring={recommendations?.scoring} />
      </div>
    </div>
  )
}
