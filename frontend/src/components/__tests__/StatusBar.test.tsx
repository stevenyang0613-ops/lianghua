import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

let mockBackendConnected = true
vi.mock('../../stores/useAppStore', () => ({
  useAppStore: (selector: any) =>
    selector({ backendConnected: mockBackendConnected, setBackendConnected: vi.fn() }),
}))

vi.mock('../../stores/useMarketStore', () => ({
  useMarketStore: (selector: any) =>
    selector({ updatedAt: null, allBonds: [] }),
}))

vi.mock('../../services/api', () => ({
  healthCheck: vi.fn(() => Promise.resolve({ status: 'ok' })),
}))

import StatusBar from '../StatusBar'

describe('StatusBar', () => {
  it('should show connected status and info', () => {
    mockBackendConnected = true
    render(<StatusBar />)
    expect(screen.getByText('后端已连接')).toBeDefined()
    expect(screen.getByText('LiangHua v0.1.0')).toBeDefined()
    expect(screen.getByText('数据源: AKShare')).toBeDefined()
  })

  it('should show disconnected status', () => {
    mockBackendConnected = false
    render(<StatusBar />)
    expect(screen.getByText('后端未连接')).toBeDefined()
  })
})