import { ArchiveRestore, ArrowLeft, Archive, Boxes, Pencil, Star } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { catalogKeys, getProduct, getProductSuppliers, updateProduct } from '../api/catalogApi'
import { Badge, StatusBadge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { DataTable, type Column } from '../components/common/DataTable'
import { DetailItem, PageHeader } from '../components/common/PageHeader'
import { ProductFormDialog } from '../components/products/ProductFormDialog'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import type { SupplierProduct } from '../types/catalog'
import { formatDimensions, formatInteger, formatMoney, formatNumber } from '../utils/format'
import { canEditMasterData } from '../utils/permissions'
import NotFoundPage from './NotFoundPage'

export default function ProductDetailPage() {
  const id = Number(useParams().productId)
  const { user } = useAuth()
  const canEdit = canEditMasterData(user)
  const [editing, setEditing] = useState(false)
  const [confirmingStatus, setConfirmingStatus] = useState(false)

  const product = useApiQuery(catalogKeys.product(id), () => getProduct(id), {
    enabled: Number.isInteger(id),
  })
  const offers = useApiQuery(catalogKeys.productSuppliers(id), () => getProductSuppliers(id), {
    enabled: Number.isInteger(id),
  })

  const toggleStatus = useApiMutation(
    (active: boolean) => updateProduct(id, { is_active: active }),
    {
      invalidates: [catalogKeys.products],
      successMessage: (p) => `${p.sku} ${p.is_active ? 'restored' : 'archived'}`,
      onSuccess: () => setConfirmingStatus(false),
    },
  )

  if (!Number.isInteger(id) || isNotFound(product.error)) {
    return <NotFoundPage />
  }
  if (product.isPending)
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading…
      </p>
    )
  if (product.errorMessage || !product.data) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {product.errorMessage}
      </p>
    )
  }

  const p = product.data
  const offerColumns: Column<SupplierProduct>[] = [
    {
      key: 'supplier',
      header: 'Supplier',
      cell: (o) => (
        <Link
          to={`/suppliers/${o.supplier.id}`}
          className="font-medium text-blue-700 hover:underline"
        >
          {o.supplier.code} · {o.supplier.name}
        </Link>
      ),
    },
    {
      key: 'preferred',
      header: '',
      cell: (o) =>
        o.is_preferred && (
          <Badge tone="info">
            <Star size={10} className="mr-1" aria-hidden="true" />
            Preferred
          </Badge>
        ),
    },
    { key: 'supplier_sku', header: 'Their SKU', cell: (o) => o.supplier_sku ?? '—' },
    { key: 'unit_cost', header: 'Cost', align: 'right', cell: (o) => formatMoney(o.unit_cost) },
    {
      key: 'lead',
      header: 'Lead time',
      align: 'right',
      cell: (o) => `${o.effective_lead_time_days} days`,
    },
    {
      key: 'moq',
      header: 'Min. order',
      align: 'right',
      cell: (o) => formatInteger(o.min_order_qty),
    },
  ]

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link
        to="/products"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft size={14} aria-hidden="true" /> All products
      </Link>

      <PageHeader
        title={p.name}
        description={
          <span className="inline-flex items-center gap-2">
            <span className="font-mono">{p.sku}</span> <StatusBadge active={p.is_active} />
          </span>
        }
        actions={
          canEdit && (
            <>
              <Button
                variant="secondary"
                icon={<Pencil size={14} aria-hidden="true" />}
                onClick={() => setEditing(true)}
              >
                Edit
              </Button>
              <Button
                variant={p.is_active ? 'danger' : 'secondary'}
                icon={
                  p.is_active ? (
                    <Archive size={14} aria-hidden="true" />
                  ) : (
                    <ArchiveRestore size={14} aria-hidden="true" />
                  )
                }
                onClick={() => setConfirmingStatus(true)}
              >
                {p.is_active ? 'Archive' : 'Restore'}
              </Button>
            </>
          )
        }
      />

      <section
        aria-labelledby="details-heading"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 id="details-heading" className="sr-only">
          Details
        </h2>
        <dl className="grid gap-5 sm:grid-cols-3">
          <DetailItem label="Category">{p.category.name}</DetailItem>
          <DetailItem label="Brand">{p.brand ?? '—'}</DetailItem>
          <DetailItem label="Barcode">{p.barcode ?? '—'}</DetailItem>
          <DetailItem label="Selling price">{formatMoney(p.unit_price)}</DetailItem>
          <DetailItem label="Purchase cost">{formatMoney(p.unit_cost)}</DetailItem>
          <DetailItem label="Margin">{formatMoney(p.margin)}</DetailItem>
          <DetailItem label="Weight">{formatNumber(p.weight_kg, 'kg')}</DetailItem>
          <DetailItem label="Dimensions (L × W × H)">
            {formatDimensions(p.length_cm, p.width_cm, p.height_cm)}
          </DetailItem>
          <DetailItem label="Volume">{formatNumber(p.volume_cm3, 'cm³')}</DetailItem>
          <DetailItem label="Stock limits">
            min {formatInteger(p.min_stock)} · max{' '}
            {p.max_stock == null ? 'none' : formatInteger(p.max_stock)}
          </DetailItem>
          <DetailItem label="Default supplier">
            {p.default_supplier ? `${p.default_supplier.code} · ${p.default_supplier.name}` : '—'}
          </DetailItem>
          {p.description && (
            <div className="sm:col-span-3">
              <DetailItem label="Description">{p.description}</DetailItem>
            </div>
          )}
        </dl>
      </section>

      <section
        aria-labelledby="stock-heading"
        className="rounded-xl border border-dashed border-slate-300 bg-white p-5"
      >
        <h2 id="stock-heading" className="flex items-center gap-2 font-medium">
          <Boxes size={16} aria-hidden="true" /> Stock
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Stock per bin and movement history arrive in Phase 4 (inventory operations).
        </p>
      </section>

      <section aria-labelledby="suppliers-heading" className="space-y-3">
        <h2 id="suppliers-heading" className="font-medium">
          Suppliers
        </h2>
        <DataTable
          caption="Suppliers offering this product"
          columns={offerColumns}
          rows={offers.data}
          rowKey={(o) => o.id}
          isLoading={offers.isPending}
          errorMessage={offers.errorMessage}
          emptyMessage="No supplier offers this product yet."
        />
      </section>

      <ProductFormDialog open={editing} onClose={() => setEditing(false)} product={p} />
      <ConfirmDialog
        open={confirmingStatus}
        title={p.is_active ? `Archive ${p.sku}?` : `Restore ${p.sku}?`}
        message={
          p.is_active
            ? 'Archived products are hidden from customers and cannot be ordered. You can restore them later.'
            : 'The product becomes visible and orderable again.'
        }
        confirmLabel={p.is_active ? 'Archive' : 'Restore'}
        tone={p.is_active ? 'danger' : 'primary'}
        loading={toggleStatus.isPending}
        onConfirm={() => toggleStatus.mutate(!p.is_active)}
        onCancel={() => setConfirmingStatus(false)}
      />
    </div>
  )
}

function isNotFound(error: unknown): boolean {
  return (error as { response?: { status?: number } } | null)?.response?.status === 404
}
