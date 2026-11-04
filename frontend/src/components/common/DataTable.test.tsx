import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DataTable, type Column } from './DataTable'

interface Item {
  id: number
  sku: string
  name: string
  price: string
}

const ROWS: Item[] = [
  { id: 1, sku: 'A-1', name: 'Alpha', price: '9.99' },
  { id: 2, sku: 'B-1', name: 'Beta', price: '19.50' },
]

const COLUMNS: Column<Item>[] = [
  { key: 'sku', header: 'SKU', sortField: 'sku' },
  { key: 'name', header: 'Name', sortField: 'name', cell: (row) => <strong>{row.name}</strong> },
  { key: 'price', header: 'Price', align: 'right' },
]

function renderTable(props: Partial<Parameters<typeof DataTable<Item>>[0]> = {}) {
  return render(
    <DataTable<Item>
      caption="Products"
      columns={COLUMNS}
      rows={ROWS}
      rowKey={(row) => row.id}
      {...props}
    />,
  )
}

function bodyRows() {
  return within(screen.getAllByRole('rowgroup')[1]).getAllByRole('row')
}

describe('DataTable', () => {
  it('renders headers, cells and custom cell content', () => {
    renderTable()

    expect(screen.getByRole('table', { name: 'Products' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'SKU',
      'Name',
      'Price',
    ])
    expect(bodyRows()).toHaveLength(2)
    expect(within(bodyRows()[0]).getByText('Alpha').tagName).toBe('STRONG')
    expect(within(bodyRows()[1]).getByText('19.50')).toHaveClass('text-right')
  })

  it('clicking a sortable header sorts ascending, then descending', async () => {
    const onSortChange = vi.fn()
    const user = userEvent.setup()
    const { rerender } = renderTable({ sort: 'sku', onSortChange })

    expect(screen.getByRole('columnheader', { name: /SKU/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
    await user.click(screen.getByRole('button', { name: /SKU/ }))
    expect(onSortChange).toHaveBeenLastCalledWith('-sku') // same field again → descending

    await user.click(screen.getByRole('button', { name: /Name/ }))
    expect(onSortChange).toHaveBeenLastCalledWith('name') // new field → ascending

    rerender(
      <DataTable<Item>
        caption="Products"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        sort="-sku"
        onSortChange={onSortChange}
      />,
    )
    expect(screen.getByRole('columnheader', { name: /SKU/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
  })

  it('columns without sortField are not clickable', () => {
    renderTable({ onSortChange: vi.fn() })

    expect(screen.queryByRole('button', { name: 'Price' })).not.toBeInTheDocument()
  })

  it('shows skeleton rows while loading', () => {
    renderTable({ isLoading: true, rows: undefined })

    expect(screen.getAllByTestId('skeleton-row')).toHaveLength(5)
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
  })

  it('shows the empty message', () => {
    renderTable({ rows: [], emptyMessage: 'No products yet.' })

    expect(screen.getByText('No products yet.')).toBeInTheDocument()
  })

  it('shows an error with a retry button and hides pagination', async () => {
    const onRetry = vi.fn()
    renderTable({
      errorMessage: 'Cannot reach the server',
      onRetry,
      pagination: { offset: 0, limit: 10, total: 30, onChange: vi.fn() },
    })

    expect(screen.getByRole('alert')).toHaveTextContent('Cannot reach the server')
    expect(screen.queryByRole('navigation', { name: 'Pagination' })).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('paginates', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderTable({ pagination: { offset: 10, limit: 10, total: 25, onChange } })

    const nav = screen.getByRole('navigation', { name: 'Pagination' })
    expect(nav).toHaveTextContent('Showing 11–20 of 25')
    await user.click(within(nav).getByRole('button', { name: /Previous/ }))
    expect(onChange).toHaveBeenLastCalledWith(0)
    await user.click(within(nav).getByRole('button', { name: /Next/ }))
    expect(onChange).toHaveBeenLastCalledWith(20)
  })

  it('disables Previous on the first page and Next on the last page', () => {
    const { rerender } = renderTable({
      pagination: { offset: 0, limit: 10, total: 25, onChange: vi.fn() },
    })
    expect(screen.getByRole('button', { name: /Previous/ })).toBeDisabled()

    rerender(
      <DataTable<Item>
        caption="Products"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        pagination={{ offset: 20, limit: 10, total: 25, onChange: vi.fn() }}
      />,
    )
    expect(screen.getByRole('navigation')).toHaveTextContent('Showing 21–25 of 25')
    expect(screen.getByRole('button', { name: /Next/ })).toBeDisabled()
  })

  it('calls onRowClick', async () => {
    const onRowClick = vi.fn()
    renderTable({ onRowClick })

    await userEvent.setup().click(screen.getByText('Beta'))

    expect(onRowClick).toHaveBeenCalledWith(ROWS[1])
  })
})
