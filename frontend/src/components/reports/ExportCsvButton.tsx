import { Download } from 'lucide-react'
import { useState } from 'react'

import { getErrorMessage } from '../../api/apiClient'
import { useToast } from '../../hooks/useToast'
import { downloadCsv, type CsvTable } from '../../utils/csv'
import { Button } from '../common/Button'

/** Saves a report table as a CSV file; `load` may fetch more rows than are shown. */
export function ExportCsvButton({
  filename,
  load,
  disabled,
}: {
  filename: string
  load: () => Promise<CsvTable> | CsvTable
  disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const exportFile = async () => {
    setBusy(true)
    try {
      const table = await load()
      downloadCsv(filename, table)
      toast.success(`Saved ${filename} (${table.rows.length} rows)`)
    } catch (error) {
      toast.error(`Export failed: ${getErrorMessage(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button
      variant="secondary"
      size="sm"
      icon={<Download size={14} aria-hidden="true" />}
      loading={busy}
      disabled={disabled}
      onClick={() => void exportFile()}
    >
      Export CSV
    </Button>
  )
}
