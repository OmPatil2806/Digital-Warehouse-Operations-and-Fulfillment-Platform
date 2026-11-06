import type { Customer, Order, OrderSummary, Shipment } from '../types/orders'

export function makeCustomer(overrides: Partial<Customer> = {}): Customer {
  return {
    id: 1,
    code: 'CUST-0001',
    name: 'Chris Customer',
    customer_type: 'consumer',
    email: 'customer@example.com',
    phone: null,
    address_line: 'Marienplatz 4',
    postal_code: '70178',
    city: 'Stuttgart',
    country: 'Germany',
    user_id: 4,
    is_active: true,
    created_at: '2026-11-06T08:00:00Z',
    ...overrides,
  }
}

export function makeOrderSummary(overrides: Partial<OrderSummary> = {}): OrderSummary {
  return {
    id: 1,
    order_number: 'SO-2026-000001',
    customer: { id: 1, code: 'CUST-0001', name: 'Chris Customer' },
    status: 'created',
    priority: 'normal',
    subtotal: '1872.70',
    total_quantity: 5,
    requested_delivery_date: null,
    created_at: '2026-11-06T09:00:00Z',
    ...overrides,
  }
}

export function makeOrder(overrides: Partial<Order> = {}): Order {
  return {
    ...makeOrderSummary(),
    warehouse: null,
    ship_to_name: 'Chris Customer',
    ship_to_address: 'Marienplatz 4',
    ship_to_postal_code: '70178',
    ship_to_city: 'Stuttgart',
    ship_to_country: 'Germany',
    notes: null,
    confirmed_at: null,
    shipped_at: null,
    delivered_at: null,
    cancelled_at: null,
    cancel_reason: null,
    items: [
      {
        id: 11,
        line_number: 1,
        product: { id: 7, sku: 'LAP-1401', name: 'Laptop 14" Business' },
        quantity: 2,
        unit_price: '899.00',
        line_total: '1798.00',
        quantity_reserved: 0,
        quantity_picked: 0,
        quantity_packed: 0,
        quantity_shipped: 0,
        quantity_returned: 0,
      },
    ],
    history: [
      {
        from_status: null,
        to_status: 'created',
        note: null,
        changed_by: { id: 2, full_name: 'Maya Manager', email: 'manager@example.com' },
        created_at: '2026-11-06T09:00:00Z',
      },
    ],
    next_statuses: ['confirmed', 'on_hold', 'cancelled'],
    ...overrides,
  }
}

export function makeShipment(overrides: Partial<Shipment> = {}): Shipment {
  return {
    id: 3,
    order: { id: 1, order_number: 'SO-2026-000001', priority: 'normal', status: 'shipped' },
    carrier: { id: 1, code: 'DHL', name: 'DHL Paket', default_transit_days: 2, is_active: true },
    tracking_number: 'DHL261106000001',
    tracking_url: 'https://track.example.com/DHL261106000001',
    status: 'in_transit',
    package_count: 1,
    weight_kg: '4.500',
    shipped_at: '2026-11-06T10:00:00Z',
    expected_delivery_date: '2026-11-10',
    delivered_at: null,
    events: [
      {
        id: 1,
        event_type: 'dispatched',
        occurred_at: '2026-11-06T10:00:00Z',
        location: 'Main Distribution Centre',
        description: 'Handed to DHL Paket',
      },
      {
        id: 2,
        event_type: 'in_transit',
        occurred_at: '2026-11-06T14:00:00Z',
        location: 'DHL hub Stuttgart',
        description: null,
      },
    ],
    ...overrides,
  }
}
