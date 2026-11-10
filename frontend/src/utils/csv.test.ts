import { afterEach, describe, expect, it, vi } from 'vitest'

import { csvCell, csvFilename, downloadCsv, toCsv } from './csv'

describe('csv', () => {
  it.each([
    ['plain', 'plain'],
    ['a,b', '"a,b"'],
    ['say "hi"', '"say ""hi"""'],
    ['two\nlines', '"two\nlines"'],
    [42, '42'],
    [0.85, '0.85'],
    ['0.85', '0.85'], // API decimals stay numbers
    ['-3', '-3'],
    [null, ''],
    [undefined, ''],
    [Number.NaN, ''],
    [true, 'true'],
  ])('csvCell(%j) = %j', (value, expected) => {
    expect(csvCell(value)).toBe(expected)
  })

  it.each([
    ['=HYPERLINK("http://evil")', `"'=HYPERLINK(""http://evil"")"`],
    ['+cmd', "'+cmd"],
    ['-2+3', "'-2+3"],
    ['@SUM(A1)', "'@SUM(A1)"],
  ])('neutralises formulas: %s', (value, expected) => {
    expect(csvCell(value)).toBe(expected)
  })

  it('writes a header and CRLF lines', () => {
    expect(
      toCsv({
        columns: ['SKU', 'Name', 'Value'],
        rows: [
          ['LAP-1601', 'Laptop 16" Creator', '1420.00'],
          ['FOO-CHE1', 'Cheddar, 400 g', null],
        ],
      }),
    ).toBe(
      'SKU,Name,Value\r\nLAP-1601,"Laptop 16"" Creator",1420.00\r\nFOO-CHE1,"Cheddar, 400 g",\r\n',
    )
  })

  it('names files after the report and period', () => {
    expect(csvFilename('inventory-report', '2026-10-12', '2026-11-10')).toBe(
      'inventory-report_2026-10-12_2026-11-10.csv',
    )
    expect(csvFilename('zones')).toBe('zones.csv')
  })

  describe('downloadCsv', () => {
    afterEach(() => vi.restoreAllMocks())

    it('saves a UTF-8 file with a BOM for Excel', async () => {
      let saved: Blob | undefined
      const createUrl = vi.fn((blob: Blob) => {
        saved = blob
        return 'blob:x'
      })
      const revoke = vi.fn()
      Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revoke })
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

      downloadCsv('report.csv', { columns: ['Value'], rows: [['€70,552.10']] })

      expect(click).toHaveBeenCalledOnce()
      expect(revoke).toHaveBeenCalledWith('blob:x')
      expect(saved?.type).toBe('text/csv;charset=utf-8')
      const bytes = new Uint8Array(await saved!.arrayBuffer())
      expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]) // BOM
      expect(new TextDecoder().decode(bytes.slice(3))).toBe('Value\r\n"€70,552.10"\r\n')
      expect(document.querySelector('a[download]')).toBeNull() // link removed again
    })
  })
})
