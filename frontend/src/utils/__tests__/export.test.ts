import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { formatDateForFilename, exportToCSV, exportToExcel } from '../export'
import type { ConvertibleQuote } from '../../types'

const mockBonds: ConvertibleQuote[] = [
  {
    code: '123456',
    name: '测试转债',
    price: 120.5,
    change_pct: 2.5,
    stock_price: 25.0,
    stock_change_pct: 1.5,
    conversion_price: 20.0,
    conversion_value: 125.0,
    premium_ratio: -3.6,
    dual_low: 145.0,
    ytm: -1.2,
    volume: 1.5,
    remaining_years: 3.5,
    forced_call_days: 0,
    timestamp: '2026-05-14T10:00:00Z',
  },
]

describe('formatDateForFilename', () => {
  it('should return date in YYYYMMDD format', () => {
    const result = formatDateForFilename()
    expect(result).toMatch(/^\d{8}$/)
  })

  it('should match current date', () => {
    const now = new Date()
    const expected = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
    expect(formatDateForFilename()).toBe(expected)
  })
})

describe('exportToCSV', () => {
  beforeEach(() => {
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should create a blob with correct CSV content', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    exportToCSV(mockBonds, 'test_bonds')

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob.type).toBe('text/csv;charset=utf-8;')

    revokeObjectURL.mockRestore()
    createObjectURL.mockRestore()
  })

  it('should generate CSV with header row', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')

    exportToCSV(mockBonds)

    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob).toBeInstanceOf(Blob)

    createObjectURL.mockRestore()
  })
})

describe('exportToExcel', () => {
  beforeEach(() => {
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should create a blob with XML Excel content', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')

    exportToExcel(mockBonds, 'test_bonds')

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/vnd.ms-excel;charset=utf-8;')

    createObjectURL.mockRestore()
  })
})
