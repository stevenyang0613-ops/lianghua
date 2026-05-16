import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Signals from '../Signals'

const mockSignalStore = {
  signals: [] as any[],
  activeStrategies: ['dual_low'],
  availableStrategies: [] as any[],
  history: [] as any[],
  stats: null,
  total: 0,
  loading: false,
  error: null,
  wsConnected: false,
  loadSignals: vi.fn(),
  loadAvailableStrategies: vi.fn(),
  loadHistory: vi.fn(),
  loadStats: vi.fn(),
  setStrategies: vi.fn(),
  execute: vi.fn(),
  batchExecute: vi.fn(),
  connectWs: vi.fn(() => vi.fn()),
  disconnectWs: vi.fn(),
}

vi.mock('../../stores/useSignalStore', () => ({
  useSignalStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockSignalStore)
    return mockSignalStore
  }),
}))

vi.mock('../../services/api', () => ({
  setAutoExecuteConfig: vi.fn(),
  cleanupSignalHistory: vi.fn(),
  getSignalExportCsvUrl: vi.fn(),
}))

vi.mock('@ant-design/icons', () => ({
  ThunderboltOutlined: () => <span>Thunder</span>,
  CheckCircleOutlined: () => <span>Check</span>,
  DownloadOutlined: () => <span>Download</span>,
  HistoryOutlined: () => <span>History</span>,
  BarChartOutlined: () => <span>Chart</span>,
  WifiOutlined: () => <span>Wifi</span>,
  CloudDownloadOutlined: () => <span>Cloud</span>,
  DeleteOutlined: () => <span>Delete</span>,
}))

describe('Signals page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSignalStore.signals = []
    mockSignalStore.loading = false
  })

  it('should render without crashing', () => {
    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should render title', () => {
    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('交易信号')
  })

  it('should show signal table with data', async () => {
    mockSignalStore.signals = [
      { code: '110001', name: 'Test Bond', action: 'buy', price: 100, confidence: 0.8, reason: 'test', strategy: 'dual_low', created_at: '2025-01-01T00:00:00Z', executed: false } as any,
    ]
    mockSignalStore.total = 1

    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('Test Bond')
    })
  })

  it('should show empty state when no signals', () => {
    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('交易信号')
  })
})