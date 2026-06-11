import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockPerformanceStats = vi.hoisted(() => ({
  total: 0,
  avgDuration: 0,
  maxDuration: 0,
  warningCount: 0,
  criticalCount: 0,
}))

const mockPerformanceRecords = vi.hoisted(() => [] as any[])

const mockStorageStats = vi.hoisted(() => ({
  totalKeys: 0,
  compressedKeys: 0,
  estimatedSize: 0,
  estimatedSavings: 0,
}))

const mockConfig = vi.hoisted(() => ({
  warningThreshold: 1000,
  criticalThreshold: 3000,
  enableNotifications: false,
  maxRecords: 1000,
}))

vi.mock('../../utils/performanceMonitor', () => ({
  getStats: vi.fn(() => mockPerformanceStats),
  getRecords: vi.fn(() => mockPerformanceRecords),
  clearRecords: vi.fn(),
  exportReport: vi.fn(() => '{}'),
  getConfig: vi.fn(() => mockConfig),
  updateConfig: vi.fn(),
}))

vi.mock('../../utils/compression', () => ({
  getStorageStats: vi.fn(() => mockStorageStats),
}))

vi.mock('@ant-design/icons', () => ({
  ThunderboltOutlined: () => <span data-testid="thunder-icon">thunder</span>,
  ReloadOutlined: () => <span data-testid="reload-icon">reload</span>,
  DownloadOutlined: () => <span data-testid="download-icon">download</span>,
  DeleteOutlined: () => <span data-testid="delete-icon">delete</span>,
  WarningOutlined: () => <span data-testid="warning-icon">warning</span>,
  CheckCircleOutlined: () => <span data-testid="check-icon">check</span>,
  ApiOutlined: () => <span data-testid="api-icon">api</span>,
  DashboardOutlined: () => <span data-testid="dashboard-icon">dashboard</span>,
  BugOutlined: () => <span data-testid="bug-icon">bug</span>,
  AimOutlined: () => <span data-testid="aim-icon">aim</span>,
  FireOutlined: () => <span data-testid="fire-icon">fire</span>,
  CompassOutlined: () => <span data-testid="compass-icon">compass</span>,
  RiseOutlined: () => <span data-testid="rise-icon">rise</span>,
  FallOutlined: () => <span data-testid="fall-icon">fall</span>,
  StopOutlined: () => <span data-testid="stop-icon">stop</span>,
  SyncOutlined: () => <span data-testid="sync-icon">sync</span>,
  ToolOutlined: () => <span data-testid="tool-icon">tool</span>,
  FilterOutlined: () => <span data-testid="filter-icon">filter</span>,
  SortAscendingOutlined: () => <span data-testid="sort-icon">sort</span>,
  ExclamationCircleOutlined: () => <span data-testid="exclamation-icon">exclamation</span>,
  QuestionCircleOutlined: () => <span data-testid="question-icon">question</span>,
  ClockCircleOutlined: () => <span data-testid="clock-icon">clock</span>,
  SettingOutlined: () => <span data-testid="setting-icon">setting</span>,
  PlusOutlined: () => <span data-testid="plus-icon">plus</span>,
  SearchOutlined: () => <span data-testid="search-icon">search</span>,
  EditOutlined: () => <span data-testid="edit-icon">edit</span>,
  EyeOutlined: () => <span data-testid="eye-icon">eye</span>,
  BarChartOutlined: () => <span data-testid="bar-icon">bar</span>,
  LineChartOutlined: () => <span data-testid="line-icon">line</span>,
  PieChartOutlined: () => <span data-testid="pie-icon">pie</span>,
  DatabaseOutlined: () => <span data-testid="db-icon">db</span>,
  CloudServerOutlined: () => <span data-testid="cloud-icon">cloud</span>,
  ExperimentOutlined: () => <span data-testid="experiment-icon">experiment</span>,
  InfoCircleOutlined: () => <span data-testid="info-icon">info</span>,
  CloseCircleOutlined: () => <span data-testid="close-icon">close</span>,
}))

import Performance from '../Performance'

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('Performance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPerformanceStats.total = 0
    mockPerformanceStats.avgDuration = 0
    mockPerformanceStats.maxDuration = 0
    mockPerformanceStats.warningCount = 0
    mockPerformanceStats.criticalCount = 0
    mockPerformanceRecords.length = 0
    mockStorageStats.totalKeys = 0
    mockStorageStats.compressedKeys = 0
    mockStorageStats.estimatedSize = 0
    mockStorageStats.estimatedSavings = 0
  })

  it('renders without crashing', async () => {
    const Wrapper = createWrapper()
    const { container } = render(
      <Wrapper>
        <Performance />
      </Wrapper>
    )
    await waitFor(() => {
      expect(container.querySelector('.ant-card')).toBeInTheDocument()
    })
  })

  it('shows the title "性能监控仪表板"', async () => {
    const Wrapper = createWrapper()
    const { getByText } = render(
      <Wrapper>
        <Performance />
      </Wrapper>
    )
    await waitFor(() => {
      expect(getByText('性能监控仪表板')).toBeInTheDocument()
    })
  })

  it('shows empty state when there are no records', async () => {
    mockPerformanceRecords.length = 0

    const Wrapper = createWrapper()
    const { getByText } = render(
      <Wrapper>
        <Performance />
      </Wrapper>
    )

    await waitFor(() => {
      expect(getByText('暂无请求记录')).toBeInTheDocument()
    })
  })

  it('displays statistics with zero values when no data', async () => {
    mockPerformanceStats.total = 0
    mockPerformanceStats.avgDuration = 0
    mockPerformanceStats.maxDuration = 0

    const Wrapper = createWrapper()
    const { getByText } = render(
      <Wrapper>
        <Performance />
      </Wrapper>
    )

    await waitFor(() => {
      expect(getByText('总请求数')).toBeInTheDocument()
      expect(getByText('平均响应')).toBeInTheDocument()
      expect(getByText('最大响应')).toBeInTheDocument()
      expect(getByText('异常请求')).toBeInTheDocument()
    })
  })

  it('displays storage statistics', async () => {
    mockStorageStats.totalKeys = 10
    mockStorageStats.compressedKeys = 5
    mockStorageStats.estimatedSize = 100
    mockStorageStats.estimatedSavings = 50

    const Wrapper = createWrapper()
    const { getByText } = render(
      <Wrapper>
        <Performance />
      </Wrapper>
    )

    await waitFor(() => {
      expect(getByText('存储统计')).toBeInTheDocument()
      expect(getByText('存储键数')).toBeInTheDocument()
      expect(getByText('压缩键数')).toBeInTheDocument()
    })
  })
})
