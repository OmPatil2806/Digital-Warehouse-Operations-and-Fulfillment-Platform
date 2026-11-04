import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'

import { getErrorMessage } from '../api/apiClient'
import { useToast } from './useToast'

interface ApiMutationOptions<TResult> {
  /** Cached lists/details to reload after success, e.g. [['products']]. */
  invalidates?: QueryKey[]
  /** Show a success toast with this text (or a text built from the result). */
  successMessage?: string | ((result: TResult) => string)
  /** Show the error as a toast (default true). Forms that show errors inline set false. */
  toastOnError?: boolean
  onSuccess?: (result: TResult) => void
}

/**
 * Change data through the API (create, update, archive...).
 *
 *   const create = useApiMutation(createProduct, {
 *     invalidates: [['products']],
 *     successMessage: (p) => `Product ${p.sku} created`,
 *   })
 *   create.mutate(values)
 */
export function useApiMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
  options: ApiMutationOptions<TResult> = {},
) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const mutation = useMutation({
    mutationFn,
    onSuccess: async (result) => {
      await Promise.all(
        (options.invalidates ?? []).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      const message =
        typeof options.successMessage === 'function'
          ? options.successMessage(result)
          : options.successMessage
      if (message) toast.success(message)
      options.onSuccess?.(result)
    },
    onError: (error) => {
      if (options.toastOnError ?? true) toast.error(getErrorMessage(error))
    },
  })
  return { ...mutation, errorMessage: mutation.error ? getErrorMessage(mutation.error) : null }
}
