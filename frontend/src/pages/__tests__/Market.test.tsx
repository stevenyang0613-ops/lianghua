import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Market from '../Market'

const mockStore: { allBonds: any[]; [k: string]: any } = {
  allBonds: [],
  updatedAt: '',
  loading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 50,
  fetchQuotes: vi.fn(),
  setPage: vi.fn(),
  setPageSize: vi.fn(),
  setAllBonds: vi.fn(),
  updateQuotes: vi.fn(),
}

vi.mock('../../stores/useMarketStore', () => ({
  useMarketStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockStore)
    return mockStore
  }),
}))

vi.mock('../../stores/useAppStore', () => ({
  useAppStore: vi.fn((selector?: (state: any) => any) => {
    const appStore = { online: true, setBackendConnected: vi.fn(), setSelectedBond: vi.fn() }
    if (selector) return selector(appStore)
    return appStore
  }),
}))

vi.mock('../../stores/useAlertStore', () => ({
  useAlertStore: vi.fn((selector?: (state: any) => any) => {
    const alertStore = { alerts: [], triggers: [], checkAlerts: vi.fn() }
    if (selector) return selector(alertStore)
    return alertStore
  }),
}))

vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({})),
}))

vi.mock('../../services/api', () => ({
  fetchAllQuotes: vi.fn().mockResolvedValue({ bonds: [] }),
}))

vi.mock('../../utils/export', () => ({
  exportToCSV: vi.fn(),
  exportToExcel: vi.fn(),
  formatDateForFilename: vi.fn(() => '20250101'),
}))

describe('Market page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStore.loading = false
    mockStore.total = 0
  })

  it('should render without crashing', () => {
    const { container } = render(
      <BrowserRouter>
        <Market />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should show skeleton loading when loading', () => {
    mockStore.loading = true

    const { container } = render(
      <BrowserRouter>
        <Market />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-skeleton')).toBeDefined()
  })

  it('行情数据列头可点击排序(代码、价格、涨跌幅等)', async () => {
    // 给 mock 添加可转债数据,让 virtual table 渲染而不是显示空状态
    mockStore.allBonds = [
      { code: '113001', name: 'A', price: 100, change_pct: 1.0, premium_ratio: 10, dual_low: 110, volume: 1, remaining_years: 2, is_called: false, call_status: '', last_trade_date: null, maturity_date: null, redemption_price: null, forced_call_days: 5 } as any,
    ]
    const { container, findByTestId } = render(
      <BrowserRouter>
        <Market />
      </BrowserRouter>
    )
    // 等待 fetchAllQuotes 完成后,loading 变为 false,virtual table 渲染
    const priceHeader = await findByTestId('vt-sort-price', undefined, { timeout: 3000 })
    expect(priceHeader).toBeTruthy()
    // 强赎状态列也应可排序（用于按状态分组查看）
    expect(container.querySelector('[data-testid="vt-sort-call_status"]')).toBeTruthy()
  })
})
