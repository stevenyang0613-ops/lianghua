import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Trade from '../Trade'

const mockTradeStore = vi.hoisted(() => ({
  account: { total_asset: 100000, cash: 50000, market_value: 50000, daily_profit: 1000, total_profit: 5000, profit_pct: 1.0, frozen: 0, updated_at: '' },
  positions: [] as any[],
  orders: [] as any[],
  fundCurve: [] as any[],
  loading: false,
  setAccount: vi.fn(),
  setPositions: vi.fn(),
  setOrders: vi.fn(),
  setFundCurve: vi.fn(),
  setLoading: vi.fn(),
  fetchAccount: vi.fn(),
  fetchPositions: vi.fn(),
  fetchOrders: vi.fn(),
  fetchFundCurve: vi.fn(),
}))

const mockMarketStore = vi.hoisted(() => ({
  allBonds: [] as any[],
  bonds: new Map(),
  setAllBonds: vi.fn(),
  updateQuotes: vi.fn(),
}))

vi.mock('../../stores/useTradeStore', () => ({
  useTradeStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockTradeStore)
    return mockTradeStore
  }),
}))

vi.mock('../../stores/useMarketStore', () => ({
  useMarketStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockMarketStore)
    return mockMarketStore
  }),
}))

vi.mock('../../services/api', () => ({
  fetchAccount: vi.fn().mockResolvedValue({}),
  fetchPositions: vi.fn().mockResolvedValue([]),
  fetchOrders: vi.fn().mockResolvedValue([]),
  cancelOrder: vi.fn(),
  resetAccount: vi.fn(),
  fetchFundCurve: vi.fn().mockResolvedValue([]),
  fetchSignals: vi.fn().mockResolvedValue({ signals: [], total: 0 }),
}))

vi.mock('../../utils/export', () => ({
  exportAccountReport: vi.fn(),
}))

vi.mock('../../components/trade/TradePanel', () => ({ default: () => <div>TradePanel</div> }))
vi.mock('../../components/trade/PositionTable', () => ({ default: () => <div>PositionTable</div> }))
vi.mock('../../components/trade/OrderHistory', () => ({ default: () => <div>OrderHistory</div> }))
vi.mock('../../components/trade/FundCurve', () => ({ default: () => <div>FundCurve</div> }))

vi.mock('@ant-design/icons', () => ({
  DollarOutlined: () => <span>Dollar</span>,
  SwapOutlined: () => <span>Swap</span>,
  BarChartOutlined: () => <span>Chart</span>,
  ReloadOutlined: () => <span>Reload</span>,
  DeleteOutlined: () => <span>Delete</span>,
  HistoryOutlined: () => <span>History</span>,
  ExportOutlined: () => <span>Export</span>,
  ThunderboltOutlined: () => <span>Thunder</span>,
  DownloadOutlined: () => <span>Download</span>,
  WarningOutlined: () => <span>Warning</span>,
  CheckCircleOutlined: () => <span>Check</span>,
  ApiOutlined: () => <span>Api</span>,
}))

describe('Trade page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockTradeStore.loading = false
  })

  it('should render without crashing', () => {
    const { container } = render(
      <BrowserRouter>
        <Trade />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should show the title', () => {
    const { container } = render(
      <BrowserRouter>
        <Trade />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('交易')
  })

  it('should show account stats', async () => {
    const { container } = render(
      <BrowserRouter>
        <Trade />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('总资产')
    })
  })
})
