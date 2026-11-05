import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../../api/catalogApi'
import * as inventoryApi from '../../api/inventoryApi'
import * as warehouseApi from '../../api/warehouseApi'
import { makeProductStock, makeRow } from '../../test/inventoryFixtures'
import { makeBinDetail, makeFit, MOUSE, productPage } from '../../test/opsMocks'
import { loggedInAs, renderWithAuth } from '../../test/renderWithAuth'
import type { Role } from '../../types/auth'
import { AdjustDialog, ReceiveDialog, TransferDialog } from './StockOperationDialogs'

vi.mock('../../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/catalogApi')>()),
  listProducts: vi.fn(),
}))
vi.mock('../../api/warehouseApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/warehouseApi')>()),
  getBinByCode: vi.fn(),
  checkFit: vi.fn(),
}))
vi.mock('../../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/inventoryApi')>()),
  getProductStock: vi.fn(),
  receiveStock: vi.fn(),
  submitTransfer: vi.fn(),
  submitAdjustment: vi.fn(),
}))
const inv = vi.mocked(inventoryApi)
const wh = vi.mocked(warehouseApi)

const MOUSE_REF = { id: MOUSE.id, sku: MOUSE.sku, name: MOUSE.name }
const STOCK = makeProductStock({
  product: MOUSE_REF,
  bins: [
    makeRow({
      id: 1,
      product: MOUSE_REF,
      bin: { id: 20, location_code: 'WH01-ZA-R01-S01-B05' },
      quantity_on_hand: 10,
      quantity_reserved: 2,
      quantity_damaged: 3,
      quantity_available: 5,
    }),
  ],
})

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

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(catalogApi.listProducts).mockResolvedValue(productPage)
  wh.getBinByCode.mockImplementation(async (code) => {
    if (code.includes('X')) throw httpError(404, 'Bin not found')
    return makeBinDetail(code, code.startsWith('WH02') ? 99 : 30)
  })
  wh.checkFit.mockResolvedValue(makeFit())
  inv.getProductStock.mockResolvedValue(STOCK)
})

function render(ui: React.ReactElement, role: Role = 'staff') {
  renderWithAuth(ui, { auth: loggedInAs(role) })
  return { user: userEvent.setup(), dialog: () => within(screen.getByRole('dialog')) }
}

async function pickMouse(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('Type a SKU or name'), 'mou')
  await user.click(await screen.findByRole('button', { name: /ACC-MOU1/ }))
}

async function enterBin(user: ReturnType<typeof userEvent.setup>, label: RegExp, code: string) {
  await user.type(screen.getByRole('textbox', { name: label }), `${code}{Enter}`)
}

describe('ReceiveDialog', () => {
  it('checks the form before sending', async () => {
    const { user } = render(<ReceiveDialog open onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Receive' }))

    expect(screen.getByText('Choose a product')).toBeInTheDocument()
    expect(screen.getByText('Enter a bin code')).toBeInTheDocument()
    expect(screen.getByText('Enter a whole number')).toBeInTheDocument()
    expect(inv.receiveStock).not.toHaveBeenCalled()
  })

  it('looks up the bin, shows the live capacity check and receives', async () => {
    const onClose = vi.fn()
    inv.receiveStock.mockResolvedValue(
      makeRow({ product: MOUSE_REF, bin: { id: 30, location_code: 'WH01-ZA-R08-S04-B06' } }),
    )
    const { user } = render(<ReceiveDialog open onClose={onClose} />)

    await pickMouse(user)
    await enterBin(user, /Put away into bin/, 'wh01-za-r08-s04-b06')
    expect(
      await screen.findByText(/WH01 · Picking A \(picking\) · shelf level 4/),
    ).toBeInTheDocument()
    expect(wh.getBinByCode).toHaveBeenCalledWith('WH01-ZA-R08-S04-B06') // upper-cased
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '20')
    expect(await screen.findByText(/Fits: 1.8 kg of 30 kg after this/)).toBeInTheDocument()
    expect(wh.checkFit).toHaveBeenLastCalledWith(30, 8, 20)
    await user.type(screen.getByRole('textbox', { name: /Delivery note/ }), 'PO-77')
    await user.click(screen.getByRole('button', { name: 'Receive' }))

    await waitFor(() =>
      expect(inv.receiveStock).toHaveBeenCalledWith(
        { product_id: 8, bin_id: 30, quantity: 20, reason: 'PO-77' },
        expect.anything(),
      ),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Received 20 × ACC-MOU1 into WH01-ZA-R08-S04-B06',
    )
    expect(onClose).toHaveBeenCalled()
  })

  it('warns when it does not fit and shows unknown bins and server errors', async () => {
    wh.checkFit.mockResolvedValue(
      makeFit({ fits: false, reasons: ['Too heavy: needs 90 kg, 30 kg available'] }),
    )
    inv.receiveStock.mockRejectedValue(httpError(409, '20 x ACC-MOU1 do not fit'))
    const { user } = render(<ReceiveDialog open onClose={vi.fn()} />)

    await pickMouse(user)
    await enterBin(user, /Put away into bin/, 'WH01-XX')
    expect(await screen.findByText('No bin with this code')).toBeInTheDocument()
    await user.clear(screen.getByRole('textbox', { name: /Put away into bin/ }))
    await enterBin(user, /Put away into bin/, 'WH01-ZA-R08-S04-B06')
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '20')
    expect(await screen.findByText(/Does not fit: Too heavy/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Receive' }))
    expect(await screen.findByText('20 x ACC-MOU1 do not fit')).toBeInTheDocument()
  })
})

describe('TransferDialog', () => {
  it('moves from a bin that holds the product, limited to its available units', async () => {
    inv.submitTransfer.mockResolvedValue({
      applied: true,
      transfer: {
        id: 4,
        quantity: 3,
        product: MOUSE_REF,
        to_bin: { id: 30, location_code: 'WH01-ZA-R08-S04-B06' },
      } as never,
    })
    const { user } = render(<TransferDialog open onClose={vi.fn()} />)

    await pickMouse(user)
    const from = await screen.findByRole('combobox', { name: /From bin/ })
    await waitFor(() =>
      expect(within(from).getByRole('option', { name: /B05 — 5 available/ })).toBeInTheDocument(),
    )
    await user.selectOptions(from, '20')
    await enterBin(user, /To bin/, 'WH01-ZA-R08-S04-B06')
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '6')
    await user.click(screen.getByRole('button', { name: 'Move' }))
    expect(screen.getByText('Only 5 possible here')).toBeInTheDocument()

    await user.clear(screen.getByRole('textbox', { name: /Quantity/ }))
    expect(screen.queryByText('Only 5 possible here')).not.toBeInTheDocument() // cleared on edit
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '3')
    await user.click(screen.getByRole('button', { name: 'Move' }))

    await waitFor(() =>
      expect(inv.submitTransfer).toHaveBeenCalledWith(
        { product_id: 8, from_bin_id: 20, to_bin_id: 30, quantity: 3, reason: undefined },
        expect.anything(),
      ),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Moved 3 × ACC-MOU1')
  })

  it('tells staff that moving to another warehouse needs approval', async () => {
    inv.submitTransfer.mockResolvedValue({
      applied: false,
      transfer: { id: 9 } as never,
    })
    const { user } = render(<TransferDialog open onClose={vi.fn()} />)

    await pickMouse(user)
    const from = await screen.findByRole('combobox', { name: /From bin/ })
    await waitFor(() => expect(from.querySelectorAll('option')).toHaveLength(2))
    await user.selectOptions(from, '20')
    await enterBin(user, /To bin/, 'WH02-ZA-R01-S01-B01')

    expect(await screen.findByText(/A manager has to approve it/)).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '1')
    await user.click(screen.getByRole('button', { name: 'Request transfer' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Transfer request #9 sent to a manager for approval',
    )
  })

  it('managers move between warehouses without a request', async () => {
    const { user } = render(<TransferDialog open onClose={vi.fn()} />, 'manager')

    await pickMouse(user)
    const from = await screen.findByRole('combobox', { name: /From bin/ })
    await waitFor(() => expect(from.querySelectorAll('option')).toHaveLength(2))
    await user.selectOptions(from, '20')
    await enterBin(user, /To bin/, 'WH02-ZA-R01-S01-B01')

    await screen.findByText(/WH02 ·/)
    expect(screen.queryByText(/A manager has to approve it/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move' })).toBeInTheDocument()
  })
})

describe('AdjustDialog', () => {
  it('staff losses become a request; the limit follows the kind', async () => {
    inv.submitAdjustment.mockResolvedValue({ applied: false, adjustment: { id: 6 } as never })
    const { user } = render(<AdjustDialog open onClose={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Request approval' })).toBeInTheDocument()
    expect(screen.getByText(/needs a manager's approval/)).toBeInTheDocument()
    await pickMouse(user)
    const bin = await screen.findByRole('combobox', { name: /^Bin/ })
    await waitFor(() => expect(within(bin).getByText(/5 available/)).toBeInTheDocument())
    await user.selectOptions(bin, '20')
    expect(screen.getByText('At most 5')).toBeInTheDocument()

    // Writing off works on damaged units: 3 here
    await user.selectOptions(screen.getByRole('combobox', { name: /What happened/ }), 'write_off')
    await user.selectOptions(screen.getByRole('combobox', { name: /^Bin/ }), '20')
    expect(screen.getByText('At most 3')).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '2')
    await user.click(screen.getByRole('button', { name: 'Request approval' }))
    expect(screen.getByText(/Explain the correction/)).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /Reason/ }), 'Broken in transport')
    await user.click(screen.getByRole('button', { name: 'Request approval' }))

    await waitFor(() =>
      expect(inv.submitAdjustment).toHaveBeenCalledWith(
        {
          product_id: 8,
          bin_id: 20,
          kind: 'write_off',
          quantity: 2,
          reason: 'Broken in transport',
        },
        expect.anything(),
      ),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Adjustment request #6 sent to a manager for approval',
    )
  })

  it('managers remove stock directly, without a request', () => {
    render(<AdjustDialog open onClose={vi.fn()} />, 'manager')

    expect(screen.getByRole('combobox', { name: /What happened/ })).toHaveValue('decrease')
    expect(screen.getByRole('button', { name: 'Save adjustment' })).toBeInTheDocument()
    expect(screen.queryByText(/needs a manager's approval/)).not.toBeInTheDocument()
  })

  it('found units go into any bin and need no approval', async () => {
    inv.submitAdjustment.mockResolvedValue({
      applied: true,
      adjustment: {
        id: 7,
        quantity: 4,
        product: MOUSE_REF,
        bin: { id: 30, location_code: 'WH01-ZA-R08-S04-B06' },
      } as never,
    })
    const { user } = render(<AdjustDialog open onClose={vi.fn()} />)

    await user.selectOptions(screen.getByRole('combobox', { name: /What happened/ }), 'increase')
    expect(screen.queryByText(/needs a manager's approval/)).not.toBeInTheDocument()
    await pickMouse(user)
    await enterBin(user, /Found in bin/, 'WH01-ZA-R08-S04-B06')
    await user.type(screen.getByRole('textbox', { name: /Quantity/ }), '4')
    await user.type(screen.getByRole('textbox', { name: /Reason/ }), 'Found behind the shelf')
    await user.click(screen.getByRole('button', { name: 'Save adjustment' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Adjustment saved: 4 × ACC-MOU1 in WH01-ZA-R08-S04-B06',
    )
    expect(inv.getProductStock).not.toHaveBeenCalled() // no source bin needed
  })
})
