import { Archive, ArchiveRestore, ArrowLeft, Pencil, Plus, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import {
  catalogKeys,
  getSupplier,
  getSupplierProducts,
  removeSupplierProduct,
  updateSupplier,
} from '../api/catalogApi'
import { Badge, StatusBadge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { DataTable, type Column } from '../components/common/DataTable'
import { DetailItem, PageHeader } from '../components/common/PageHeader'
import { SupplierFormDialog } from '../components/suppliers/SupplierFormDialog'
import { SupplierProductFormDialog } from '../components/suppliers/SupplierProductFormDialog'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import type { SupplierProduct } from '../types/catalog'
import { formatInteger, formatMoney, formatPercent } from '../utils/format'
import { canEditMasterData } from '../utils/permissions'
import NotFoundPage from './NotFoundPage'

export default function SupplierDetailPage() {
  const id = Number(useParams().supplierId)
  const { user } = useAuth()
  const canEdit = canEditMasterData(user)
  const [editing, setEditing] = useState(false)
  const [addingProduct, setAddingProduct] = useState(false)
  const [confirmingStatus, setConfirmingStatus] = useState(false)
  const [removing, setRemoving] = useState<SupplierProduct | null>(null)

  const supplier = useApiQuery(catalogKeys.supplier(id), () => getSupplier(id), {
    enabled: Number.isInteger(id),
  })
  const offers = useApiQuery(catalogKeys.supplierProducts(id), () => getSupplierProducts(id), {
    enabled: Number.isInteger(id),
  })

  const toggleStatus = useApiMutation(
    (active: boolean) => updateSupplier(id, { is_active: active }),
    {
      invalidates: [catalogKeys.suppliers],
      successMessage: (s) => `${s.code} ${s.is_active ? 'restored' : 'archived'}`,
      onSuccess: () => setConfirmingStatus(false),
    },
  )
  const remove = useApiMutation(
    (offer: SupplierProduct) => removeSupplierProduct(id, offer.product.id),
    {
      invalidates: [catalogKeys.suppliers, catalogKeys.products],
      successMessage: 'Product removed from this supplier',
      onSuccess: () => setRemoving(null),
    },
  )

  const status = (supplier.error as { response?: { status?: number } } | null)?.response?.status
  if (!Number.isInteger(id) || status === 404) return <NotFoundPage />
  if (supplier.isPending)
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading…
      </p>
    )
  if (!supplier.data) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {supplier.errorMessage}
      </p>
    )
  }

  const s = supplier.data
  const columns: Column<SupplierProduct>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (o) => (
        <Link
          to={`/products/${o.product.id}`}
          className="font-medium text-blue-700 hover:underline"
        >
          <span className="font-mono text-xs whitespace-nowrap">{o.product.sku}</span> ·{' '}
          {o.product.name}
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
    ...(canEdit
      ? [
          {
            key: 'actions',
            header: '',
            align: 'right' as const,
            cell: (o: SupplierProduct) => (
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Remove ${o.product.sku}`}
                icon={<Trash2 size={14} aria-hidden="true" />}
                onClick={() => setRemoving(o)}
              />
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link
        to="/suppliers"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft size={14} aria-hidden="true" /> All suppliers
      </Link>

      <PageHeader
        title={s.name}
        description={
          <span className="inline-flex items-center gap-2">
            <span className="font-mono">{s.code}</span> <StatusBadge active={s.is_active} />
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
                variant={s.is_active ? 'danger' : 'secondary'}
                icon={
                  s.is_active ? (
                    <Archive size={14} aria-hidden="true" />
                  ) : (
                    <ArchiveRestore size={14} aria-hidden="true" />
                  )
                }
                onClick={() => setConfirmingStatus(true)}
              >
                {s.is_active ? 'Archive' : 'Restore'}
              </Button>
            </>
          )
        }
      />

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <dl className="grid gap-5 sm:grid-cols-3">
          <DetailItem label="Contact">{s.contact_name ?? '—'}</DetailItem>
          <DetailItem label="Email">
            {s.email ? (
              <a className="text-blue-700 hover:underline" href={`mailto:${s.email}`}>
                {s.email}
              </a>
            ) : (
              '—'
            )}
          </DetailItem>
          <DetailItem label="Phone">{s.phone ?? '—'}</DetailItem>
          <DetailItem label="Country">{s.country ?? '—'}</DetailItem>
          <DetailItem label="Lead time">{s.lead_time_days} days</DetailItem>
          <DetailItem label="Reliability">{formatPercent(s.reliability_score)}</DetailItem>
          {s.address && (
            <div className="sm:col-span-3">
              <DetailItem label="Address">{s.address}</DetailItem>
            </div>
          )}
        </dl>
      </section>

      <section aria-labelledby="offers-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="offers-heading" className="font-medium">
            Products offered ({offers.data?.length ?? 0})
          </h2>
          {canEdit && s.is_active && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} aria-hidden="true" />}
              onClick={() => setAddingProduct(true)}
            >
              Add product
            </Button>
          )}
        </div>
        <DataTable
          caption="Products offered by this supplier"
          columns={columns}
          rows={offers.data}
          rowKey={(o) => o.id}
          isLoading={offers.isPending}
          errorMessage={offers.errorMessage}
          emptyMessage="This supplier does not offer any products yet."
        />
      </section>

      <SupplierFormDialog open={editing} onClose={() => setEditing(false)} supplier={s} />
      <SupplierProductFormDialog
        open={addingProduct}
        onClose={() => setAddingProduct(false)}
        supplier={s}
        existingProductIds={(offers.data ?? []).map((o) => o.product.id)}
      />
      <ConfirmDialog
        open={confirmingStatus}
        title={s.is_active ? `Archive ${s.code}?` : `Restore ${s.code}?`}
        message={
          s.is_active
            ? 'Archived suppliers cannot be chosen for new products or purchase orders.'
            : 'The supplier can be used again.'
        }
        confirmLabel={s.is_active ? 'Archive' : 'Restore'}
        tone={s.is_active ? 'danger' : 'primary'}
        loading={toggleStatus.isPending}
        onConfirm={() => toggleStatus.mutate(!s.is_active)}
        onCancel={() => setConfirmingStatus(false)}
      />
      <ConfirmDialog
        open={removing !== null}
        title="Remove product from supplier?"
        message={
          removing && `${s.code} will no longer be listed as a source for ${removing.product.sku}.`
        }
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  )
}
