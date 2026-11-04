import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../lib/queryClient'
import { TestProviders } from '../test/TestProviders'
import { useApiMutation } from './useApiMutation'
import { useApiQuery } from './useApiQuery'

function httpError(status: number, detail: string): AxiosError {
  const response = {
    status,
    data: { detail },
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('fail', 'ERR', undefined, undefined, response)
}

function ProductCount({ fetcher }: { fetcher: () => Promise<number> }) {
  const query = useApiQuery(['products', 'count'], fetcher)
  if (query.isPending) return <p>loading</p>
  if (query.errorMessage) return <p role="alert">{query.errorMessage}</p>
  return <p>count: {query.data}</p>
}

describe('useApiQuery', () => {
  it('loads data', async () => {
    render(
      <TestProviders>
        <ProductCount fetcher={() => Promise.resolve(42)} />
      </TestProviders>,
    )

    expect(screen.getByText('loading')).toBeInTheDocument()
    expect(await screen.findByText('count: 42')).toBeInTheDocument()
  })

  it('turns errors into readable messages', async () => {
    render(
      <TestProviders>
        <ProductCount fetcher={() => Promise.reject(httpError(403, 'Not allowed here'))} />
      </TestProviders>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed here')
  })
})

function CreateButton({
  action,
  onCount,
}: {
  action: (name: string) => Promise<{ name: string }>
  onCount: () => Promise<number>
}) {
  const count = useApiQuery(['products', 'count'], onCount)
  const create = useApiMutation(action, {
    invalidates: [['products']],
    successMessage: (result) => `Created ${result.name}`,
  })
  return (
    <>
      <p>count: {count.data ?? '…'}</p>
      <button onClick={() => create.mutate('Drill')}>create</button>
    </>
  )
}

describe('useApiMutation', () => {
  it('reloads affected queries and shows a success toast', async () => {
    let stored = 1
    const fetchCount = vi.fn(() => Promise.resolve(stored))
    const create = vi.fn(async (name: string) => {
      stored += 1
      return { name }
    })
    render(
      <TestProviders>
        <CreateButton action={create} onCount={fetchCount} />
      </TestProviders>,
    )
    expect(await screen.findByText('count: 1')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: 'create' }))

    expect(await screen.findByText('count: 2')).toBeInTheDocument() // list reloaded
    expect(screen.getByRole('status')).toHaveTextContent('Created Drill')
    expect(create).toHaveBeenCalledWith('Drill', expect.anything())
  })

  it('shows API errors as an error toast', async () => {
    render(
      <TestProviders>
        <CreateButton
          action={() => Promise.reject(httpError(409, 'A product with this SKU already exists'))}
          onCount={() => Promise.resolve(1)}
        />
      </TestProviders>,
    )

    await userEvent.setup().click(screen.getByRole('button', { name: 'create' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('A product with this SKU already exists'),
    )
  })
})

describe('query client retry policy', () => {
  const retry = createQueryClient().getDefaultOptions().queries?.retry as (
    count: number,
    error: unknown,
  ) => boolean

  it('never retries 4xx answers', () => {
    expect(retry(0, httpError(404, 'nope'))).toBe(false)
    expect(retry(0, httpError(401, 'nope'))).toBe(false)
  })

  it('retries network and server errors up to twice', () => {
    expect(retry(0, httpError(503, 'down'))).toBe(true)
    expect(retry(1, new AxiosError('Network Error', 'ERR_NETWORK'))).toBe(true)
    expect(retry(2, httpError(500, 'still down'))).toBe(false)
  })
})
