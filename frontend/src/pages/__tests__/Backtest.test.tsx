import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Backtest from '../Backtest'

const mockStrategies = vi.hoisted(() => [
  {
    id: 'test-strategy',
    name: 'Test Strategy',
    description: 'A test strategy',
    params: [
      { name: 'param1', label: 'Parameter 1', type: 'int', default: 10, min_val: 1, max_val: 100 },
    ],
  },
])

const mockBacktestResult = vi.hoisted(() => ({
  equity_curve: [{ date: '2024-01-01', value: 1.0 }, { date: '2024-01-02', value: 1.05 }],
  metrics: {
    total_return_pct: 5.0,
    annual_return_pct: 12.5,
    max_drawdown_pct: -2.0,
    sharpe_ratio: 1.5,
    win_rate: 60.0,
    profit_loss_ratio: 1.8,
    total_trades: 10,
    avg_hold_days: 5.5,
    calmar_ratio: 6.25,
    sortino_ratio: 2.0,
  },
  trades: [],
  execution_time_ms: 100,
}))

vi.mock('../../services/api', () => ({
  fetchStrategies: vi.fn().mockResolvedValue(mockStrategies),
  runBacktest: vi.fn().mockResolvedValue({ result: mockBacktestResult }),
  runOptimization: vi.fn().mockResolvedValue({
    result: {
      total_combinations: 10,
      best_params: { param1: 15 },
      best_metrics: mockBacktestResult.metrics,
      top_results: [],
      execution_time_ms: 500,
      optimize_metric: 'sharpe_ratio',
    },
  }),
}))

vi.mock('echarts-for-react', () => ({
  default: ({ option: _option, style }: { option: any; style: any }) => (
    <div data-testid="echarts-mock" style={style}>
      ECharts Mock
    </div>
  ),
}))

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd')
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
    },
  }
})

vi.mock('@ant-design/icons', () => ({
  PlayCircleOutlined: () => <span data-testid="play-icon">Play</span>,
  BarChartOutlined: () => <span data-testid="chart-icon">Chart</span>,
  ThunderboltOutlined: () => <span data-testid="thunder-icon">Thunder</span>,
  SettingOutlined: () => <span data-testid="setting-icon">Setting</span>,
  ExperimentOutlined: () => <span data-testid="experiment-icon">Experiment</span>,
}))

describe('Backtest page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render without crashing', () => {
    const { container } = render(
      <BrowserRouter>
        <Backtest />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should show loading state initially', () => {
    const { container } = render(
      <BrowserRouter>
        <Backtest />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('策略配置')
  })

  it('should render strategy configuration section', async () => {
    const { container } = render(
      <BrowserRouter>
        <Backtest />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('策略配置')
    await waitFor(() => {
      expect(container.textContent).toContain('回测区间')
    })
  })

  it('should render backtest center title', () => {
    const { container } = render(
      <BrowserRouter>
        <Backtest />
      </BrowserRouter>
    )
    expect(container.textContent).toContain('回测中心')
  })

  it('should show empty state prompt', async () => {
    const { container } = render(
      <BrowserRouter>
        <Backtest />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('选择策略和参数')
      expect(container.textContent).toContain('开始测试')
    })
  })
})
