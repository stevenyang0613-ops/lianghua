import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  formatDateForFilename,
  exportToCSV,
  exportToExcel,
  exportTrades,
  exportPositions,
  exportFundCurve,
  exportAccountReport,
} from '../export'
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
    is_called: false,
    call_status: '',
    last_trade_date: undefined,
    maturity_date: undefined,
    redemption_price: 0,
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

describe('exportTrades (bug fix: field names + CSV escaping)', () => {
  it('should handle trades with comma in code/name without breaking CSV', async () => {
    let captured = ''
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
    const origCreate = URL.createObjectURL
    URL.createObjectURL = ((b: Blob) => {
      void b.text().then((t) => { captured = t })
      return 'blob:test'
    }) as typeof URL.createObjectURL
    try {
      const trades = [
        { id: '1', code: '113,044', name: '大秦,转债', side: 'buy', price: 120.0, volume: 10, status: 'filled', created_at: '2026-06-11T10:00:00Z' },
      ]
      exportTrades(trades, 'trades')
      await new Promise(r => setTimeout(r, 20))
      expect(captured).toContain('"113,044"')
      expect(captured).toContain('"大秦,转债"')
    } finally {
      URL.createObjectURL = origCreate
    }
  })
})

describe('exportPositions (bug fix: field names + percent)', () => {
  async function captureBlob(fn: () => void): Promise<string> {
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
    let captured = ''
    const origCreate = URL.createObjectURL
    URL.createObjectURL = ((b: Blob) => {
      void b.text().then((t) => { captured = t })
      return 'blob:test'
    }) as typeof URL.createObjectURL
    try {
      fn()
      await new Promise(r => setTimeout(r, 20))
      return captured
    } finally {
      URL.createObjectURL = origCreate
    }
  }

  it('should use correct field names: cost_price / profit_amount / profit_pct', async () => {
    const csv = await captureBlob(() => {
      exportPositions([
        { code: '113044', name: '大秦转债', volume: 10, available_volume: 10,
          cost_price: 120.0, current_price: 125.0, market_value: 1250.0,
          profit_amount: 50.0, profit_pct: 4.17 },
      ], 'positions')
    })
    expect(csv).toContain('120.00')   // cost_price
    expect(csv).toContain('125.00')   // current_price
    expect(csv).toContain('50.00')    // profit_amount
    expect(csv).toContain('4.17')     // profit_pct (not multiplied by 100)
  })
})

describe('exportFundCurve (bug fix: field names)', () => {
  async function captureBlob(fn: () => void): Promise<string> {
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
    let captured = ''
    const origCreate = URL.createObjectURL
    URL.createObjectURL = ((b: Blob) => {
      void b.text().then((t) => { captured = t })
      return 'blob:test'
    }) as typeof URL.createObjectURL
    try {
      fn()
      await new Promise(r => setTimeout(r, 20))
      return captured
    } finally {
      URL.createObjectURL = origCreate
    }
  }

  it('should read ts / total_asset / total_profit (not date / nav / total_return)', async () => {
    const csv = await captureBlob(() => {
      exportFundCurve([
        { ts: '2026-06-11T10:00:00', total_asset: 100500.0, cash: 50000.0,
          market_value: 50500.0, total_profit: 500.0 },
      ], 'fund')
    })
    expect(csv).toContain('2026-06-11T10:00:00')
    expect(csv).toContain('100500.00')
    expect(csv).toContain('500.00')
  })
})

describe('exportAccountReport (bug fix: field names)', () => {
  async function captureBlob(fn: () => void): Promise<string> {
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el)
    let captured = ''
    const origCreate = URL.createObjectURL
    URL.createObjectURL = ((b: Blob) => {
      void b.text().then((t) => { captured = t })
      return 'blob:test'
    }) as typeof URL.createObjectURL
    try {
      fn()
      await new Promise(r => setTimeout(r, 20))
      return captured
    } finally {
      URL.createObjectURL = origCreate
    }
  }

  it('should display correct account values from real field names', async () => {
    const report = await captureBlob(() => {
      const account = {
        total_asset: 100500.0, cash: 50000.0, market_value: 50500.0,
        total_profit: 500.0, daily_profit: 100.0, frozen: 0.0, updated_at: '',
      }
      const positions = [
        { code: '113044', name: '大秦转债', volume: 10, cost_price: 120.0,
          profit_amount: 50.0 },
      ]
      const orders = [
        { id: '1', status: 'filled' },
        { id: '2', status: 'pending' },
        { id: '3', status: 'cancelled' },
      ]
      exportAccountReport(account, positions, orders, 'report')
    })
    expect(report).toContain('100500.00')  // total_asset
    expect(report).toContain('50000.00')   // cash
    expect(report).toContain('500.00')     // total_profit
    expect(report).toContain('50.00')      // position profit_amount
    expect(report).not.toContain('¥0.00')  // no zero placeholders
  })
})
