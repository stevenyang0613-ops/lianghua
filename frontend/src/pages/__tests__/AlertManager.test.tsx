import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AlertManager from '../AlertManager'

const mockAlerts: any[] = []
const mockStats = {
  total: 0,
  active: 0,
  triggered: 0,
  byType: {},
}

vi.mock('../../utils/priceAlert', () => ({
  getAlerts: vi.fn(() => mockAlerts),
  addAlert: vi.fn(),
  updateAlert: vi.fn(),
  deleteAlert: vi.fn(),
  clearAlerts: vi.fn(),
  clearTriggeredAlerts: vi.fn(() => 0),
  getAlertStats: vi.fn(() => mockStats),
  getAlertLabel: vi.fn((record) => `${record.type}: ${record.target}`),
  ALERT_TYPE_OPTIONS: [
    { value: 'price_above', label: '价格高于' },
    { value: 'price_below', label: '价格低于' },
    { value: 'change_above', label: '涨幅高于' },
    { value: 'change_below', label: '跌幅高于' },
  ],
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
  BellOutlined: () => <span data-testid="bell-icon">Bell</span>,
  PlusOutlined: () => <span data-testid="plus-icon">Plus</span>,
  DeleteOutlined: () => <span data-testid="delete-icon">Delete</span>,
  EditOutlined: () => <span data-testid="edit-icon">Edit</span>,
  WarningOutlined: () => <span data-testid="warning-icon">Warning</span>,
  ClearOutlined: () => <span data-testid="clear-icon">Clear</span>,
}))

describe('AlertManager page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render without crashing', () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AlertManager />
      </MemoryRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should show empty state when no alerts', () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AlertManager />
      </MemoryRouter>
    )
    expect(container.textContent).toContain('暂无预警')
  })

  it('should render statistics cards', () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AlertManager />
      </MemoryRouter>
    )
    expect(container.textContent).toContain('预警总数')
    expect(container.textContent).toContain('监控中')
    expect(container.textContent).toContain('已触发')
    expect(container.textContent).toContain('价格预警')
  })

  it('should render action buttons', () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AlertManager />
      </MemoryRouter>
    )
    expect(container.textContent).toContain('清除已触发')
    expect(container.textContent).toContain('清除全部')
    expect(container.textContent).toContain('添加预警')
  })
})
