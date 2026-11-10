import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts'
import { describe, expect, it, vi } from 'vitest'

import { ChartCard } from './ChartCard'
import { ChartTooltip } from './ChartTooltip'
import { SERIES, seriesColor, STATUS } from './chartTheme'
import { DateRangePicker } from './DateRangePicker'
import { DEFAULT_RANGE } from './dateRange'
import { KpiCard } from './KpiCard'

describe('KpiCard', () => {
  it('shows the value, a status in words with an icon, and a detail', () => {
    render(
      <KpiCard
        label="Open alerts"
        value={8}
        status={{ tone: 'critical', label: '1 critical' }}
        detail="Low stock, delays, suppliers"
      />,
    )
    const card = screen.getByRole('region', { name: 'Open alerts' })
    expect(within(card).getByText('8')).toBeInTheDocument()
    const status = within(card).getByText('1 critical')
    expect(status.querySelector('svg')).not.toBeNull() // never colour alone
    expect(within(card).getByText('Low stock, delays, suppliers')).toBeInTheDocument()
  })

  it('shows a placeholder while loading', () => {
    render(<KpiCard label="Stock value" value="€1" detail="hidden" isLoading />)
    const card = screen.getByRole('region', { name: 'Stock value' })
    expect(card).toHaveAttribute('aria-busy', 'true')
    expect(within(card).queryByText('€1')).not.toBeInTheDocument()
    expect(within(card).queryByText('hidden')).not.toBeInTheDocument()
  })
})

describe('DateRangePicker', () => {
  it('switches between presets', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<DateRangePicker value={DEFAULT_RANGE} onChange={onChange} />)

    expect(screen.getByRole('button', { name: 'Last 30 days' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'Last 7 days' }))
    expect(onChange).toHaveBeenCalledWith({ preset: '7', from: '', to: '' })
  })

  it('applies a valid custom range and explains an invalid one', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<DateRangePicker value={DEFAULT_RANGE} onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: 'Custom range' }))
    const from = screen.getByLabelText('From')
    const to = screen.getByLabelText('To')
    await user.clear(to)
    await user.type(to, '2026-11-01')
    await user.type(from, '2026-11-05')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByRole('alert')).toHaveTextContent('must not be after')
    expect(onChange).not.toHaveBeenCalled()

    await user.clear(from)
    await user.type(from, '2026-10-01')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onChange).toHaveBeenCalledWith({
      preset: 'custom',
      from: '2026-10-01',
      to: '2026-11-01',
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('ChartCard', () => {
  const table = {
    columns: ['Day', 'Orders'],
    rows: [
      ['1 Nov', 3],
      ['2 Nov', 5],
    ],
  }

  it('switches between the chart and the same numbers as a table', async () => {
    const user = userEvent.setup()
    render(
      <ChartCard title="Orders per day" description="Placed orders" table={table}>
        <p>the chart</p>
      </ChartCard>,
    )
    const figure = screen.getByRole('figure', { name: 'Orders per day' })
    expect(within(figure).getByText('the chart')).toBeInTheDocument()

    await user.click(within(figure).getByRole('button', { name: 'Show table' }))
    const grid = within(figure).getByRole('table', { name: 'Orders per day' })
    expect(within(grid).getByRole('columnheader', { name: 'Orders' })).toBeInTheDocument()
    expect(within(grid).getByRole('rowheader', { name: '2 Nov' })).toBeInTheDocument()
    expect(within(grid).getByRole('cell', { name: '5' })).toBeInTheDocument()

    await user.click(within(figure).getByRole('button', { name: 'Show chart' }))
    expect(within(figure).getByText('the chart')).toBeInTheDocument()
  })

  it('shows empty, loading and error states instead of the chart', () => {
    const { rerender } = render(
      <ChartCard title="T" table={{ columns: ['a'], rows: [] }} emptyMessage="Nothing yet.">
        <p>the chart</p>
      </ChartCard>,
    )
    expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show table' })).not.toBeInTheDocument()

    rerender(
      <ChartCard title="T" table={table} isLoading>
        <p>the chart</p>
      </ChartCard>,
    )
    expect(screen.getByLabelText('Loading chart')).toBeInTheDocument()

    rerender(
      <ChartCard title="T" table={table} errorMessage="Server down">
        <p>the chart</p>
      </ChartCard>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Server down')
    expect(screen.queryByText('the chart')).not.toBeInTheDocument()
  })

  it('keeps the previous chart visible while refreshing', () => {
    render(
      <ChartCard title="T" table={table} isRefreshing>
        <p>the chart</p>
      </ChartCard>,
    )
    expect(screen.getByText('the chart').parentElement).toHaveClass('opacity-60')
    expect(screen.getByRole('figure')).toHaveAttribute('aria-busy', 'true')
  })
})

describe('ChartTooltip', () => {
  it('lists every series with the value first', () => {
    render(
      <ChartTooltip
        active
        label="2026-11-01"
        formatLabel={() => '1 Nov'}
        formatValue={(v) => `${v} orders`}
        payload={[
          { name: 'Placed', value: 3, color: SERIES[0] },
          { name: 'Shipped', value: 2, color: SERIES[1] },
        ]}
      />,
    )
    expect(screen.getByText('1 Nov')).toBeInTheDocument()
    const rows = screen.getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual(['3 ordersPlaced', '2 ordersShipped'])
  })

  it('renders nothing when inactive', () => {
    const { container } = render(<ChartTooltip active={false} payload={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('chart theme', () => {
  it('keeps series and status colours apart and assigns series in fixed order', () => {
    expect(new Set(SERIES).size).toBe(8)
    expect(Object.values(STATUS).some((c) => (SERIES as readonly string[]).includes(c))).toBe(false)
    expect(seriesColor(0)).toBe('#2a78d6')
    expect(seriesColor(8)).toBe('#898781') // a ninth series is "Other", never a new hue
  })

  it('works with Recharts in the test environment', () => {
    const { container } = render(
      <LineChart
        width={400}
        height={200}
        data={[
          { d: 'a', v: 1 },
          { d: 'b', v: 3 },
        ]}
      >
        <XAxis dataKey="d" />
        <YAxis />
        <Tooltip content={<ChartTooltip />} />
        <Line dataKey="v" stroke={SERIES[0]} isAnimationActive={false} />
      </LineChart>,
    )
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull()
  })
})
