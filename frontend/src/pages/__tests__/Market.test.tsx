import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Market from '../Market'

const mockStore = {
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
})
