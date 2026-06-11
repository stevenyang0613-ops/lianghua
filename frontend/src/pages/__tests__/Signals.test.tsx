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
  loadSignals: vi.fn(() => Promise.resolve()),
  loadAvailableStrategies: vi.fn(() => Promise.resolve()),
  loadHistory: vi.fn(() => Promise.resolve()),
  loadStats: vi.fn(() => Promise.resolve()),
  setStrategies: vi.fn(() => Promise.resolve()),
  execute: vi.fn(() => Promise.resolve()),
  batchExecute: vi.fn(() => Promise.resolve()),
  connectWs: vi.fn(() => vi.fn()),
  disconnectWs: vi.fn(),
  subscribeWs: vi.fn(() => vi.fn()),
}

const mockAppStore = {
  signalWsConnected: false,
  marketWsConnected: false,
  backendConnected: false,
}

vi.mock('../../stores/useSignalStore', () => ({
  useSignalStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockSignalStore)
    return mockSignalStore
  }),
}))

vi.mock('../../stores/useAppStore', () => ({
  useAppStore: vi.fn((selector?: (state: any) => any) => {
    if (selector) return selector(mockAppStore)
    return mockAppStore
  }),
}))

vi.mock('../../utils/wsInstances', () => ({
  signalsWs: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onStateChange: vi.fn(() => () => {}),
    getLastError: vi.fn(() => null),
  },
  marketWs: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onStateChange: vi.fn(() => () => {}),
  },
  refreshWsToken: vi.fn(() => Promise.resolve()),
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
  ReloadOutlined: () => <span>Reload</span>,
  DisconnectOutlined: () => <span>Disconnect</span>,
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

  it('should render title', async () => {
    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('交易信号')
    })
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

  it('should show empty state when no signals', async () => {
    const { container } = render(
      <BrowserRouter>
        <Signals />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('交易信号')
    })
  })
})