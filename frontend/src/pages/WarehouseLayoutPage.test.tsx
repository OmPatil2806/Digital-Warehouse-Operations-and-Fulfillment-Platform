import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as warehouseApi from '../api/warehouseApi'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { LayoutRack, LayoutZone, Warehouse, WarehouseLayout } from '../types/warehouse'
import WarehouseLayoutPage from './WarehouseLayoutPage'

vi.mock('../api/warehouseApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/warehouseApi')>()),
  listWarehouses: vi.fn(),
  getLayout: vi.fn(),
  getBinByCode: vi.fn(),
  generateLayout: vi.fn(),
  setZoneActive: vi.fn(),
  setRackActive: vi.fn(),
  createWarehouse: vi.fn(),
}))
const api = vi.mocked(warehouseApi)

const WH: Warehouse = {
  id: 1,
  code: 'WH01',
  name: 'Main Distribution Centre',
  address: null,
  is_active: true,
  created_at: '',
  updated_at: '',
}

let nextId = 100
function rack(zone: string, code: string, distance: string, levels = 2, bins = 2): LayoutRack {
  return {
    id: nextId++,
    zone_id: 1,
    code,
    distance_to_packing_m: distance,
    is_active: true,
    shelves: Array.from({ length: levels }, (_, i) => ({
      id: nextId++,
      rack_id: 0,
      code: `S0${i + 1}`,
      level: i + 1,
      is_active: true,
      bins: Array.from({ length: bins }, (_, j) => ({
        id: nextId++,
        shelf_id: 0,
        code: `B0${j + 1}`,
        location_code: `WH01-${zone}-${code}-S0${i + 1}-B0${j + 1}`,
        max_weight_kg: '30.000',
        max_volume_cm3: 120000,
        is_active: true,
      })),
    })),
  }
}

function zone(
  id: number,
  code: string,
  name: string,
  type: LayoutZone['zone_type'],
  racks: LayoutRack[],
): LayoutZone {
  const bins = racks.flatMap((r) => r.shelves.flatMap((s) => s.bins)).length
  return {
    id,
    warehouse_id: 1,
    code,
    name,
    zone_type: type,
    is_active: true,
    totals: {
      bins,
      active_bins: bins,
      max_weight_kg: String(bins * 30),
      max_volume_cm3: bins * 120000,
    },
    racks,
  }
}

function makeLayout(): WarehouseLayout {
  const za = zone(1, 'ZA', 'Picking A', 'picking', [
    rack('ZA', 'R01', '4.0'),
    rack('ZA', 'R02', '6.0'),
  ])
  const zc = zone(2, 'ZC', 'Cold storage', 'cold', [rack('ZC', 'R01', '18.0', 3, 4)])
  return {
    ...WH,
    totals: { bins: 20, active_bins: 20, max_weight_kg: '600.000', max_volume_cm3: 2_400_000 },
    zones: [za, zc],
  }
}

function notFound(): AxiosError {
  const response = {
    status: 404,
    data: { detail: 'No bin with this location code' },
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('nf', 'ERR', undefined, undefined, response)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listWarehouses.mockResolvedValue([WH])
  api.getLayout.mockResolvedValue(makeLayout())
})

function renderPage(role: Role = 'manager', path = '/warehouse') {
  renderWithAuth(<WarehouseLayoutPage />, { auth: loggedInAs(role), path, route: '/warehouse' })
  return userEvent.setup()
}

const location = () => screen.getByTestId('location').textContent

describe('WarehouseLayoutPage', () => {
  it('shows totals, zone tabs and the racks of the first zone', async () => {
    renderPage()

    const tabs = await screen.findAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['ZAPicking A', 'ZCCold storage'])
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('20 active / 20')).toBeInTheDocument()
    expect(screen.getByText('600 kg')).toBeInTheDocument()

    const racks = within(screen.getByRole('list', { name: 'Racks' })).getAllByRole('listitem', {
      name: /^Rack/,
    })
    expect(racks.map((r) => r.getAttribute('aria-label'))).toEqual(['Rack R01', 'Rack R02'])
    expect(within(racks[0]).getByText('4 m to packing')).toBeInTheDocument()
  })

  it('lists shelves from the top level down to the floor', async () => {
    renderPage()

    const rack = await screen.findByRole('listitem', { name: 'Rack R01' })
    const shelves = within(rack).getAllByRole('list', { name: /^Shelf/ })
    expect(shelves.map((s) => s.getAttribute('aria-label'))).toEqual(['Shelf S02', 'Shelf S01'])
  })

  it('switches zones and keeps the choice in the URL', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('tab', { name: /ZC/ }))

    expect(screen.getByRole('tab', { name: /ZC/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Zone ZC' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Bin WH01-ZC/ })).toHaveLength(12)
    expect(location()).toBe('/warehouse?zone=ZC')
  })

  it('opens bin details when a bin is clicked', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Bin WH01-ZA-R02-S01-B02' }))

    const dialog = screen.getByRole('dialog', { name: 'WH01-ZA-R02-S01-B02' })
    expect(within(dialog).getByText('ZA · Picking A')).toBeInTheDocument()
    expect(within(dialog).getByText('R02 (6 m to packing)')).toBeInTheDocument()
    expect(within(dialog).getByText('S01 (level 1)')).toBeInTheDocument()
    expect(within(dialog).getByText('120,000 cm³')).toBeInTheDocument()
  })

  it('"Find bin" jumps to the zone and highlights the bin', async () => {
    api.getBinByCode.mockResolvedValue({
      ...makeLayout().zones[1].racks[0].shelves[2].bins[3],
      warehouse: WH,
      zone: makeLayout().zones[1],
      rack: makeLayout().zones[1].racks[0],
      shelf: makeLayout().zones[1].racks[0].shelves[2],
    })
    const user = renderPage()
    await screen.findAllByRole('tab')

    await user.type(screen.getByRole('textbox', { name: 'Location code' }), 'wh01-zc-r01-s03-b04')
    await user.click(screen.getByRole('button', { name: 'Find bin' }))

    expect(api.getBinByCode).toHaveBeenCalledWith('wh01-zc-r01-s03-b04')
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /ZC/ })).toHaveAttribute('aria-selected', 'true'),
    )
    expect(screen.getByRole('button', { name: 'Bin WH01-ZC-R01-S03-B04' })).toHaveAttribute(
      'aria-current',
      'location',
    )
  })

  it('"Find bin" explains when no bin matches', async () => {
    api.getBinByCode.mockRejectedValue(notFound())
    const user = renderPage()
    await screen.findAllByRole('tab')

    await user.type(screen.getByRole('textbox', { name: 'Location code' }), 'WH99-ZZ-R01-S01-B01')
    await user.click(screen.getByRole('button', { name: 'Find bin' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('No bin with this location code')
    expect(screen.getByRole('textbox', { name: 'Location code' })).toHaveAttribute(
      'aria-invalid',
      'true',
    )
  })

  it('"Show archived" reloads the layout including archived records', async () => {
    const user = renderPage()
    await screen.findAllByRole('tab')
    expect(api.getLayout).toHaveBeenLastCalledWith(1, false)

    await user.click(screen.getByRole('checkbox', { name: 'Show archived' }))

    await waitFor(() => expect(api.getLayout).toHaveBeenLastCalledWith(1, true))
    expect(location()).toBe('/warehouse?archived=1')
  })

  it('archives a zone after confirmation', async () => {
    api.setZoneActive.mockResolvedValue({ ...makeLayout().zones[0], is_active: false })
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Archive zone' }))
    const dialog = screen.getByRole('dialog', { name: 'Archive zone ZA?' })
    expect(dialog).toHaveTextContent('All racks, shelves and bins in this zone are archived too')
    await user.click(within(dialog).getByRole('button', { name: 'Archive' }))

    await waitFor(() => expect(api.setZoneActive).toHaveBeenCalledWith(1, false))
  })

  it('archives a single rack', async () => {
    api.setRackActive.mockResolvedValue({ ...makeLayout().zones[0].racks[1], is_active: false })
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Archive rack R02' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }))

    await waitFor(() => expect(api.setRackActive).toHaveBeenCalled())
  })

  it('staff can look around but not change anything', async () => {
    renderPage('staff')

    await screen.findAllByRole('tab')
    for (const name of ['Generate bins', 'Archive zone', 'Add zone', 'New warehouse']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: /Archive rack/ })).not.toBeInTheDocument()
    // ...but can still open bins and search
    expect(screen.getByRole('button', { name: 'Find bin' })).toBeInTheDocument()
  })

  it('shows a set-up hint when there are no warehouses', async () => {
    api.listWarehouses.mockResolvedValue([])
    renderPage()

    expect(await screen.findByRole('heading', { name: 'No warehouses yet' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New warehouse' })).toBeInTheDocument()
  })

  describe('Generate bins', () => {
    async function openDialog() {
      const user = renderPage()
      await user.click(await screen.findByRole('button', { name: 'Generate bins' }))
      return {
        user,
        dialog: within(screen.getByRole('dialog', { name: 'Generate bins in zone ZA' })),
      }
    }

    it('previews how many bins will be created', async () => {
      const { user, dialog } = await openDialog()

      expect(dialog.getByRole('status')).toHaveTextContent('4 racks × 4 shelves × 6 bins = 96 bins')
      await user.clear(dialog.getByRole('textbox', { name: 'Racks' }))
      await user.type(dialog.getByRole('textbox', { name: 'Racks' }), '10')
      expect(dialog.getByRole('status')).toHaveTextContent('= 240 bins')
      expect(dialog.getByRole('button', { name: 'Generate 240 bins' })).toBeInTheDocument()
    })

    it('refuses more than 5000 bins before calling the API', async () => {
      const { user, dialog } = await openDialog()

      await user.clear(dialog.getByRole('textbox', { name: 'Racks' }))
      await user.type(dialog.getByRole('textbox', { name: 'Racks' }), '99')
      await user.clear(dialog.getByRole('textbox', { name: 'Shelves per rack' }))
      await user.type(dialog.getByRole('textbox', { name: 'Shelves per rack' }), '20')
      expect(dialog.getByRole('status')).toHaveTextContent('more than the limit of 5,000')
      await user.click(dialog.getByRole('button', { name: /Generate/ }))

      expect(await dialog.findByText('At most 5000 bins per run')).toBeInTheDocument()
      expect(api.generateLayout).not.toHaveBeenCalled()
    })

    it('sends the request and reports the created range', async () => {
      api.generateLayout.mockResolvedValue({
        racks_created: 4,
        shelves_created: 16,
        bins_created: 96,
        first_location_code: 'WH01-ZA-R03-S01-B01',
        last_location_code: 'WH01-ZA-R06-S04-B06',
      })
      const { user, dialog } = await openDialog()

      await user.click(dialog.getByRole('button', { name: 'Generate 96 bins' }))

      await waitFor(() =>
        expect(api.generateLayout).toHaveBeenCalledWith(1, {
          racks: 4,
          shelves_per_rack: 4,
          bins_per_shelf: 6,
          max_weight_kg: '30',
          max_volume_cm3: 120000,
          first_rack_distance_m: '5',
          distance_step_m: '2',
        }),
      )
      expect(
        await screen.findByText('96 bins created (WH01-ZA-R03-S01-B01 … WH01-ZA-R06-S04-B06)'),
      ).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})
