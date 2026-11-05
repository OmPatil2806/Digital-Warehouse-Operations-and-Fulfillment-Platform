import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/**
 * List page state (search, filters, sort, page) kept in the URL, e.g.
 *   /products?q=laptop&category=3&sort=-unit_price&offset=25
 * so a filtered view survives a reload and can be bookmarked or shared.
 *
 * Values equal to their default are removed from the URL to keep it short.
 * Changing anything other than `offset` jumps back to the first page.
 */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams()

  const values = Object.fromEntries(
    Object.entries(defaults).map(([key, fallback]) => [key, params.get(key) ?? fallback]),
  ) as T

  const update = useCallback(
    (changes: Partial<T>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          for (const [key, value] of Object.entries(changes)) {
            if (value === undefined || value === defaults[key]) next.delete(key)
            else next.set(key, value as string)
          }
          if (!('offset' in changes)) next.delete('offset')
          return next
        },
        { replace: true },
      )
    },
    // `defaults` is a constant object literal at each call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setParams],
  )

  return [values, update] as const
}
