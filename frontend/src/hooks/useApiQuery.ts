import { keepPreviousData, useQuery, type QueryKey } from '@tanstack/react-query'

import { getErrorMessage } from '../api/apiClient'

interface ApiQueryOptions {
  /** Skip the request until this is true (e.g. until an id is known). */
  enabled?: boolean
  /** Keep showing the previous page while the next one loads (tables, pagination). */
  keepPrevious?: boolean
}

/**
 * Load data from the API with caching.
 *
 *   const products = useApiQuery(['products', params], () => listProducts(params))
 *
 * Adds `errorMessage`: a readable error text for the UI (or null).
 */
export function useApiQuery<T>(
  key: QueryKey,
  fetcher: () => Promise<T>,
  options: ApiQueryOptions = {},
) {
  const query = useQuery({
    queryKey: key,
    queryFn: fetcher,
    enabled: options.enabled ?? true,
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
  })
  return { ...query, errorMessage: query.error ? getErrorMessage(query.error) : null }
}
