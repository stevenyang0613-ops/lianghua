import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Dashboard from '../Dashboard'

const mockLayouts = vi.hoisted(() => [
  {
    id: 'default',
    name: '默认布局',
    widgets: [
      { id: 'w1', type: 'statistic', title: '信号数', config: { field: 'total_signals' }, x: 0, y: 0, w: 1, h: 1, visible: true },
    ],
    isDefault: true,
  },
])

const mockWidgets = vi.hoisted(() => [
  { id: 'w1', type: 'statistic', title: '信号数', config: { field: 'total_signals' }, x: 0, y: 0, w: 1, h: 1, visible: true },
])

vi.mock('../../utils/dashboardLayout', () => ({
  getLayouts: vi.fn(() => mockLayouts),
  getCurrentLayout: vi.fn(() => ({ id: 'default', name: '默认布局', widgets: mockWidgets })),
  setCurrentLayout: vi.fn(),
  createLayout: vi.fn(),
  deleteLayout: vi.fn(),
  addWidget: vi.fn(),
  deleteWidget: vi.fn(),
  duplicateLayout: vi.fn(),
  exportLayout: vi.fn(),
  importLayout: vi.fn(),
}))

vi.mock('@ant-design/icons', () => ({
  SettingOutlined: () => <span>Setting</span>,
  PlusOutlined: () => <span>Plus</span>,
  DeleteOutlined: () => <span>Delete</span>,
  CopyOutlined: () => <span>Copy</span>,
  DownloadOutlined: () => <span>Download</span>,
  UploadOutlined: () => <span>Upload</span>,
  SaveOutlined: () => <span>Save</span>,
  ThunderboltOutlined: () => <span>Thunder</span>,
  CheckCircleOutlined: () => <span>Check</span>,
  HistoryOutlined: () => <span>History</span>,
  BarChartOutlined: () => <span>Chart</span>,
  WifiOutlined: () => <span>Wifi</span>,
  CloudDownloadOutlined: () => <span>Cloud</span>,
  DeleteOutlinedOld: () => <span>DeleteOld</span>,
}))

describe('Dashboard page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render without crashing', () => {
    const { container } = render(
      <BrowserRouter>
        <Dashboard />
      </BrowserRouter>
    )
    expect(container.querySelector('.ant-typography')).toBeDefined()
  })

  it('should render layout title', async () => {
    const { container } = render(
      <BrowserRouter>
        <Dashboard />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('数据看板')
    })
  })

  it('should render widget cards', async () => {
    const { container } = render(
      <BrowserRouter>
        <Dashboard />
      </BrowserRouter>
    )
    await waitFor(() => {
      expect(container.textContent).toContain('信号数')
    })
  })
})